# SPDX-License-Identifier: Apache-2.0
"""XPolicyLab-compatible ASPIRE policy lifecycle, single rollout only.

No socket, simulator, LLM endpoint, GPU, or service is initialized here.
Programs must be frozen/reviewed ASPIRE skills. Production deployment must
isolate the policy process: Python execution is not a security sandbox.
"""
from pathlib import Path
import math
import threading
from .bridge import EpisodeClosed, RolloutBridge
from .protocol import RobotSpec, adapt_observation
from .tools import RoboDojoTools


class Model:
    def __init__(self, model_cfg, *, program_provider=None, tool_factory=None):
        self.spec = RobotSpec.from_config(model_cfg)
        self.timeout = float(model_cfg.get("request_timeout_s", 120.))
        self.join_timeout = float(model_cfg.get("reset_timeout_s", 5.))
        for timeout in (self.timeout, self.join_timeout):
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("timeouts must be finite and positive")
        self.camera_aliases = dict(model_cfg.get("camera_aliases", {}))
        self.tool_factory = tool_factory or RoboDojoTools
        if program_provider is None:
            # Read a frozen skill once, before receiving benchmark observations.
            # No task-name file lookup, hidden seed access or online code updates.
            self.program = Path(model_cfg["program_path"]).read_text(encoding="utf-8")
            compile(self.program, str(model_cfg["program_path"]), "exec")
            self.program_provider = lambda public_obs, api_docs: self.program
        else:
            self.program_provider = program_provider
        self.bridge = None
        self.worker = None

    def reset(self):
        """Cancel outstanding control, discard episode state, and join worker."""
        if self.bridge is not None:
            self.bridge.close()
        if self.worker is not None:
            self.worker.join(self.join_timeout)
            if self.worker.is_alive():
                raise RuntimeError("skill did not stop on reset; restart isolated policy process")
        self.bridge = None
        self.worker = None

    close = reset

    def update_obs(self, obs):
        # Validate/strip observation before an actor or code-generation callback.
        public = adapt_observation(obs, self.camera_aliases)
        if self.bridge is None:
            self.bridge = RolloutBridge(self.spec, self.timeout)
            self.bridge.update({"vision": obs["vision"], "state": public["robot_state"],
                                "instruction": public["instruction"], "env_idx": obs.get("env_idx", 0)})
            tools = self.tool_factory(self.bridge, camera_aliases=self.camera_aliases)
            self.worker = threading.Thread(target=self._run, args=(self.bridge, tools), daemon=True)
            self.worker.start()
        else:
            self.bridge.update({"vision": obs["vision"], "state": public["robot_state"],
                                "instruction": public["instruction"], "env_idx": obs.get("env_idx", 0)})

    def _run(self, bridge, tools):
        try:
            public = tools.get_observation()
            code = self.program_provider(public, tools.combined_doc())
            if not isinstance(code, str):
                raise TypeError("program_provider must return executable Python text")
            # Same full-import execution model as ASPIRE's existing executor,
            # with only public helper names (no env, task internals or credentials).
            namespace = {"__name__": "__main__", "obs": public,
                         "INPUTS": public, "RESULT": None, **tools.functions()}
            exec(compile(code, "<aspire-robodojo-skill>", "exec"), namespace, namespace)
            bridge.finish()
        except EpisodeClosed:
            pass
        except BaseException as error:
            bridge.finish(f"{type(error).__name__}: {error}")

    def get_action(self):
        """Return exactly one native action dict in a list, then require feedback."""
        if self.bridge is None:
            raise RuntimeError("update_obs must precede get_action")
        return self.bridge.action()

    def update_obs_batch(self, obs_list):
        if len(obs_list) != 1:
            raise ValueError("this adapter supports exactly one active rollout")
        self.update_obs(obs_list[0])

    def get_action_batch(self, env_idx_list=None, *, obs=None):
        # demo deploy.py passes env indices under `obs`, not env_idx_list.
        if obs is not None and env_idx_list is not None:
            raise ValueError("pass env indices once")
        indices = obs if obs is not None else env_idx_list
        if indices is not None and (len(indices) != 1 or self.bridge is None or indices[0] != self.bridge.env_idx):
            raise ValueError("batch must contain the single current environment index")
        return [self.get_action()]
