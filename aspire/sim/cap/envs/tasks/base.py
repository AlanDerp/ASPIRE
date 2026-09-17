# SPDX-FileCopyrightText: Copyright (c) 2026 Max Fu
# SPDX-License-Identifier: MIT
#
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import contextlib
import io
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, SupportsFloat

import numpy as np
from gymnasium import Env, spaces

from aspire.sim.cap.envs.base import BaseEnv, ObsType, get_env
from aspire.sim.cap.envs.configs.instantiate import instantiate as cfg_instantiate
from aspire.sim.cap.envs.configs.loader import DictLoader
from aspire.sim.cap.factual_grounding.config import RuntimeFeatureSet
from aspire.sim.cap.integrations.base_api import ApiBase, get_api
from aspire.sim.cap.knowledge.runtime import (
    KnowledgeRuntimeConfig,
    append_actor_knowledge,
    load_runtime_knowledge,
)


class Tee(io.TextIOBase):
    """This allows streaming stdout and stderr to both the console and a buffer
    (enables breakpointing for debugging!)
    """

    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
            st.flush()

    def flush(self):
        for st in self.streams:
            st.flush()


@dataclass
class CodeExecEnvConfig:
    """Configuration for a code-execution environment.

    Attributes:
        low_level: A constructed low-level env or a YAML path to its config.
        apis: List of API names to expose to user code (e.g., "graspnet-real").
        prompt: Task instruction for the agent.
        multi_turn_prompt: Instruction for the agent to regenerate the code for multi-turn.
    """

    low_level: Env | str
    apis: list[str]
    prompt: str | None = None
    task_only_prompt: str | None = None
    multi_turn_prompt: str | None = None
    oracle_code: str | None = None
    privileged: bool = False
    enable_render: bool = True
    viser_debug: bool = False
    knowledge: KnowledgeRuntimeConfig | dict[str, Any] | None = None
    runtime_features: RuntimeFeatureSet | dict[str, Any] | None = None


class SimpleExecutor:
    """Minimal in-process code executor with full imports allowed.

    Executes user code with globals: env (low-level env), APIS (name->api), INPUTS, RESULT.
    The user code may import any installed package and can interact with `env` directly
    for closed-loop control.
    """

    def __init__(self, env: BaseEnv, apis: dict[str, ApiBase]) -> None:
        self._env = env
        self._apis = apis

    def run(self, code: str, *, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        g: dict[str, Any] = {
            "__name__": "__main__",
            "env": self._env,
            "APIS": self._apis,
            "INPUTS": inputs or {},
            "RESULT": None,
        }
        try:
            exec(code, g, g)
            return {"ok": True, "result": g.get("RESULT")}
        except BaseException as exc:  # defensive; propagate minimal info
            return {"ok": False, "error": repr(exc)}


class CodeExecutionEnvBase(Env):
    """High-level env that runs Python code and interacts with a low-level env."""

    prompt: str | None = None
    regenerate_prompt: str | None = None

    def __init__(self, cfg: CodeExecEnvConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self.low_level_env: BaseEnv = self._build_low_level(
            cfg.low_level, cfg.privileged, cfg.enable_render, cfg.viser_debug
        )  # type: ignore[assignment]
        # Create APIs once; maximize sharing inside a worker via lru_cache in get_api
        self._apis: dict[str, ApiBase] = {n: get_api(n)(self.low_level_env) for n in cfg.apis}
        # for api in self._apis.values():
        #     api.set_env(self.low_level_env)
        self._executor = SimpleExecutor(self.low_level_env, self._apis)
        self._step_count = 0
        self.action_space = spaces.Text(max_length=4096)
        self.observation_space = spaces.Dict({"task_prompt": spaces.Text(max_length=4096)})

        # Prompt priority: YAML config (cfg.prompt) overrides the class attribute (self.prompt).
        # The class attribute serves as the single source of truth for the default task prompt.
        # YAML configs should only set prompt when they need to override the class default
        # (e.g., multi-turn variants that add extra instructions).
        self._task_prompt = cfg.prompt if cfg.prompt is not None else self.prompt
        self._runtime_knowledge = load_runtime_knowledge(cfg.knowledge)
        self._runtime_features = (
            cfg.runtime_features
            if isinstance(cfg.runtime_features, RuntimeFeatureSet)
            else RuntimeFeatureSet.from_dict(cfg.runtime_features)
        )

        # Oracle code: YAML config overrides class attribute
        if cfg.oracle_code is not None:
            self.oracle_code = cfg.oracle_code
        self._system_prompt = (
            "You are a helpful assistant that generates Python code to directly solve the task."
        )
        self._full_prompt = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": [{"type": "text", "text": self._get_complete_prompt()}]},
        ]

        # Persistent execution namespace to retain variables across steps
        self._exec_globals: dict[str, Any] = {}
        self._init_exec_globals()

    # Functions that can be overridden by subclasses
    def compute_reward(self) -> float:
        """
        Computes the reward for the current state by delegating to the
        low-level environment.

        Returns:
            float: The reward at the current base simulator state.
        """
        return self.low_level_env.compute_reward()

    # ---- Private methods ----
    def _get_complete_prompt(self) -> str:
        """
        Get the complete prompt for the task.
        Returns:
            str: The complete prompt for the task.
        """
        docs = []
        for _name, api in self._apis.items():
            text = api.combined_doc()
            # NOTE: we need to discuss this further down the line
            # docs.append(f"- {name}:\n{text.strip()}")
            docs.append(f"\n{text.strip()}")
        prompt = f"{self._task_prompt}\nAPIs:\n" + "\n".join(docs)
        return append_actor_knowledge(prompt, self._runtime_knowledge)

    def _exec_user_code(self, code: str) -> dict[str, Any]:
        obs = self._get_observation()
        # Update dynamic obs while retaining previously defined variables
        self._exec_globals["obs"] = obs
        self._exec_globals["env"] = self.low_level_env
        self._exec_globals["APIS"] = self._apis
        # Ensure API helper functions remain bound/current
        for api in self._apis.values():
            for fn_name, fn in api.functions().items():
                self._exec_globals[fn_name] = fn

        stdout_buffer = io.StringIO()
        tee_out = Tee(sys.stdout, stdout_buffer)
        stderr_buffer = io.StringIO()
        tee_err = Tee(sys.stderr, stderr_buffer)
        ok = True
        try:
            with (
                contextlib.redirect_stdout(tee_out),
                contextlib.redirect_stderr(tee_err),
            ):
                exec(code, self._exec_globals, self._exec_globals)
        except BaseException:  # defensive; propagate minimal info
            ok = False
            # Always print full traceback to the redirected stderr (tee -> console and buffer)
            traceback.print_exc(file=tee_err)

        return {
            "ok": ok,
            "stdout": stdout_buffer.getvalue(),
            "stderr": stderr_buffer.getvalue(),
            "result": self._exec_globals.get("RESULT"),
        }

    def _exec_user_code_public(self, code: str) -> dict[str, Any]:
        """Execute dynamic-v2 code with only public observation and API helpers.

        The low-level environment and API objects are intentionally absent. Private
        audit modes additionally dispatch this namespace through the OS-isolated
        JSON-RPC worker configured by the trial harness.
        """
        from aspire.sim.cap.envs.execution_boundary import validate_public_python

        try:
            validate_public_python(code)
        except (SyntaxError, ValueError) as error:
            return {"ok": False, "stdout": "", "stderr": f"PublicExecutionRejected: {error}", "result": None}
        obs = self.public_observation()
        public_globals: dict[str, Any] = {
            "__name__": "__main__", "obs": obs, "INPUTS": obs, "RESULT": None,
        }
        for api in self._apis.values():
            public_globals.update(api.functions())
        private_root = getattr(self, "_fg_private_artifact_root", None)
        if private_root is not None:
            from aspire.sim.cap.envs.generated_worker import execute_isolated_python

            helpers = {
                name: function for api in self._apis.values()
                for name, function in api.functions().items()
            }
            return execute_isolated_python(
                code, obs, helpers, private_root=Path(private_root)
            )
        stdout_buffer, stderr_buffer = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                exec(code, public_globals, public_globals)
            ok = True
        except BaseException:
            ok = False
            traceback.print_exc(file=stderr_buffer)
        return {"ok": ok, "stdout": stdout_buffer.getvalue(), "stderr": stderr_buffer.getvalue(), "result": public_globals.get("RESULT")}

    def _init_exec_globals(self) -> None:
        """
        Initialize the persistent globals dictionary for user code execution.
        This is called at construction time and on reset to avoid leakage across episodes.
        """
        g: dict[str, Any] = {
            "__name__": "__main__",
            "env": self.low_level_env,
            "APIS": self._apis,
            # Populated per-step/reset; keep reference stable across execs
            "INPUTS": {},
            # Users can set and reuse RESULT across steps if desired
            "RESULT": None,
        }
        # Bind helper functions from APIs into the global namespace for convenience
        for api in self._apis.values():
            for fn_name, fn in api.functions().items():
                g[fn_name] = fn
        self._exec_globals = g

    def _build_low_level(
        self, src: Env | str, privileged: bool = False, enable_render: bool = True, viser_debug: bool = False
    ) -> BaseEnv:
        """
        Builds the low level environment from the given source.
        Args:
            src: Env | str: the source of the low level environment
        Returns:
            BaseEnv: the low level environment
        """
        if isinstance(src, str):
            if src.endswith(".yaml") or src.endswith(".yml"):
                cfg = DictLoader.load(src)
                if isinstance(cfg, dict) and "_target_" in cfg:
                    return cfg_instantiate(cfg)  # type: ignore[no-any-return]
                return cfg  # type: ignore[return-value]
            else:
                return get_env(src, privileged=privileged, enable_render=enable_render, viser_debug=viser_debug)
        return src

    def _get_observation(self) -> dict[str, Any]:
        """
        Gets the observation of the environment. This should be consistent for all environments, where observation from low level environment
        along with the full prompt is returned
        Returns:
            Dict[str, Any]: The observation of the environment.
        """
        obs = self.low_level_env.get_observation()
        obs.update({"full_prompt": self._full_prompt})
        return obs

    # ---- Public facing methods ----
    # Public facing methods that should be consistent for all environments
    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[ObsType, dict[str, Any]]:
        """
        Resets the environment to an initial internal state, returning an initial observation and info.
        Args:
            seed: The seed to reset the environment with.
            options: The options to reset the environment with.
        Returns:
            tuple[ObsType, dict[str, Any]]: A tuple containing the observation and info.
        """
        self._step_count = 0
        obs, info = self.low_level_env.reset(seed=seed, options=options)
        obs.update(self._get_observation())
        # Reinitialize globals for a fresh episode and prime INPUTS with the reset observation
        self._init_exec_globals()
        self._exec_globals["INPUTS"] = obs
        info.update(
            {
                "task_prompt": self._task_prompt,
                "knowledge": self._runtime_knowledge.telemetry,
            }
        )
        return obs, info

    def step(self, action: str) -> tuple[ObsType, SupportsFloat, bool, bool, dict[str, Any]]:
        """
        Default implementation: execute code with helpers, report reward and logs.
        Subclasses can override hooks to customize inputs and helper bindings.
        """
        self._step_count += 1
        exec_result = self._exec_user_code(action)
        obs = self._get_observation()
        # Force viser 3D view update after code execution so the scene
        # reflects the final state (sim substep updates may have been skipped).
        if hasattr(self.low_level_env, "viser_debug") and self.low_level_env.viser_debug:
            self.low_level_env._update_viser_server()
        reward = self.compute_reward()
        if hasattr(self.low_level_env, "task_completed"):
            task_completed = self.low_level_env.task_completed()
        else:
            task_completed = None
        terminated = reward == 1.0

        truncated = getattr(self.low_level_env, "_sim_step_count", 0) >= getattr(
            self.low_level_env, "max_steps", 999999
        )  # type: ignore[arg-type]

        if not exec_result["ok"] and exec_result["stderr"] == "":
            print("Uhh we shouldn't be here, sandbox return code 1 but stderr appears empty")
            # import pdb; pdb.set_trace()
            raise RuntimeError("Sandbox return code 1 but stderr appears empty")

        info = {
            "sandbox_rc": 0 if exec_result["ok"] else 1,
            "stdout": exec_result["stdout"],
            "stderr": exec_result["stderr"],
            "task_prompt": self._task_prompt,
            "task_completed": task_completed,
            "knowledge": self._runtime_knowledge.telemetry,
        }
        return obs, reward, bool(terminated), bool(truncated), info

    def step_public(self, action: str) -> tuple[ObsType, SupportsFloat, bool, bool, dict[str, Any]]:
        """Dynamic-v2 step which withholds raw environment and API objects."""
        self._step_count += 1
        exec_result = self._exec_user_code_public(action)
        obs = self._get_observation()
        reward = self.compute_reward()
        task_completed = self.low_level_env.task_completed() if hasattr(self.low_level_env, "task_completed") else None
        terminated = reward == 1.0
        truncated = getattr(self.low_level_env, "_sim_step_count", 0) >= getattr(self.low_level_env, "max_steps", 999999)
        return obs, reward, bool(terminated), bool(truncated), {
            "sandbox_rc": 0 if exec_result["ok"] else 1,
            "stdout": exec_result["stdout"], "stderr": exec_result["stderr"],
            "task_prompt": self._task_prompt, "task_completed": task_completed,
            "knowledge": self._runtime_knowledge.telemetry,
        }

    def step_skill(self, skill_id: str, arguments: dict[str, Any] | None = None) -> tuple[ObsType, SupportsFloat, bool, bool, dict[str, Any]]:
        """Execute one curated public API helper by exact registered name."""
        helpers = {
            name: function for api in self._apis.values()
            for name, function in api.functions().items()
        }
        if skill_id not in helpers:
            raise ValueError(f"public skill is not registered: {skill_id}")
        stdout_buffer, stderr_buffer = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                result = helpers[skill_id](**(arguments or {}))
            ok = True
        except BaseException:
            ok, result = False, None
            traceback.print_exc(file=stderr_buffer)
        obs = self._get_observation()
        reward = self.compute_reward()
        task_completed = self.low_level_env.task_completed() if hasattr(self.low_level_env, "task_completed") else None
        truncated = getattr(self.low_level_env, "_sim_step_count", 0) >= getattr(
            self.low_level_env, "max_steps", 999999
        )
        return obs, reward, reward == 1.0, bool(truncated), {
            "sandbox_rc": 0 if ok else 1, "stdout": stdout_buffer.getvalue(),
            "stderr": stderr_buffer.getvalue(), "result": result,
            "task_prompt": self._task_prompt, "task_completed": task_completed,
            "knowledge": self._runtime_knowledge.telemetry,
        }

    def public_observation(self) -> dict[str, Any]:
        """ObservationBroker source without prompt or private simulator handles."""
        value = dict(self.low_level_env.get_observation())
        value.pop("full_prompt", None)
        return value

    def public_tick(self) -> int:
        """Expose a monotonic control/simulator tick without private state values."""
        return int(getattr(self.low_level_env, "_sim_step_count", self._step_count))

    def run_public_probe(self, probe_id: str) -> None:
        """Ask the low-level integration to acquire one registered public probe."""
        runner = getattr(self.low_level_env, "run_public_probe", None)
        if not callable(runner):
            raise ValueError(f"public probe is unsupported by this environment: {probe_id}")
        runner(probe_id)

    def render(self, mode: str = "rgb_array"):
        return self.low_level_env.render(mode=mode)

    def render_wrist(self) -> np.ndarray | None:
        if hasattr(self.low_level_env, "render_wrist"):
            return self.low_level_env.render_wrist()
        return None

    # Video passthrough for demo compatibility
    def enable_video_capture(
        self,
        enabled: bool = True,
        *,
        clear: bool = True,
        wrist_camera: bool = False,
    ) -> None:
        import inspect

        sig = inspect.signature(self.low_level_env.enable_video_capture)
        if "wrist_camera" in sig.parameters:
            self.low_level_env.enable_video_capture(
                enabled, clear=clear, wrist_camera=wrist_camera
            )
        else:
            self.low_level_env.enable_video_capture(enabled, clear=clear)

    def get_video_frames(self, *, clear: bool = False) -> list[np.ndarray]:
        return self.low_level_env.get_video_frames(clear=clear)

    def get_video_frame_count(self) -> int:
        if hasattr(self.low_level_env, "get_video_frame_count"):
            return self.low_level_env.get_video_frame_count()
        if hasattr(self.low_level_env, "_frame_buffer"):
            return len(self.low_level_env._frame_buffer)
        return 0

    def get_video_frames_range(self, start: int, end: int) -> list[np.ndarray]:
        if hasattr(self.low_level_env, "get_video_frames_range"):
            return self.low_level_env.get_video_frames_range(start, end)
        if hasattr(self.low_level_env, "_frame_buffer"):
            return [f.copy() for f in self.low_level_env._frame_buffer[start:end]]
        return []

    def get_wrist_video_frames(self, *, clear: bool = False) -> list[np.ndarray]:
        if hasattr(self.low_level_env, "get_wrist_video_frames"):
            return self.low_level_env.get_wrist_video_frames(clear=clear)
        if hasattr(self.low_level_env, "_wrist_frame_buffer"):
            frames = [f.copy() for f in self.low_level_env._wrist_frame_buffer]
            if clear:
                self.low_level_env._wrist_frame_buffer.clear()
            return frames
        return []

    def get_wrist_video_frames_range(self, start: int, end: int) -> list[np.ndarray]:
        if hasattr(self.low_level_env, "get_wrist_video_frames_range"):
            return self.low_level_env.get_wrist_video_frames_range(start, end)
        if hasattr(self.low_level_env, "_wrist_frame_buffer"):
            return [f.copy() for f in self.low_level_env._wrist_frame_buffer[start:end]]
        return []


# Use user's BaseEnv for low-level envs

_EXEC_ENV_FACTORIES: dict[str, Callable[[], CodeExecutionEnvBase]] = {}


def register_exec_env(name: str, factory: Callable[[], CodeExecutionEnvBase]) -> None:
    _EXEC_ENV_FACTORIES[name] = factory


def get_exec_env(name: str) -> Callable[[], CodeExecutionEnvBase]:
    if name not in _EXEC_ENV_FACTORIES:
        raise KeyError(f"Execution Environment '{name}' not registered")
    return _EXEC_ENV_FACTORIES[name]


def list_exec_envs() -> list[str]:
    return list(_EXEC_ENV_FACTORIES.keys())


_CONFIG_FACTORIES: dict[str, CodeExecEnvConfig] = {}


def register_config(name: str, factory: CodeExecEnvConfig) -> None:
    _CONFIG_FACTORIES[name] = factory


def get_config(name: str) -> CodeExecEnvConfig:
    if name not in _CONFIG_FACTORIES:
        raise KeyError(f"Configuration '{name}' not registered")
    return _CONFIG_FACTORIES[name]


def list_configs() -> list[str]:
    return list(_CONFIG_FACTORIES.keys())


__all__ = [
    "register_exec_env",
    "get_exec_env",
    "list_exec_envs",
    "register_config",
    "get_config",
    "list_configs",
    "SimpleExecutor",
    "CodeExecEnvConfig",
    "CodeExecutionEnvBase",
]
