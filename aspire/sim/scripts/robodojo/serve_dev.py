"""One development trial: ASPIRE code generation through a credential-free proxy."""
import argparse
import asyncio
import base64
import io
import json
import logging
import re
from pathlib import Path

import numpy as np
from PIL import Image
import requests
from aspire.sim.cap.robodojo.policy import Model
from XPolicyLab.model_template import ModelTemplate
from XPolicyLab.utils.process_data import get_robot_action_dim_info, get_batch_size
from client_server.ws.model_server import PolicyServer, PolicyServerConfig
from aspire.sim.cap.robodojo.task_tools import TaskTools


def serialize(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


class ProgramProvider:
    def __init__(self, output):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.used = False

    def __call__(self, obs, api_docs):
        if self.used:
            raise RuntimeError("this runner allows one task-code generation only")
        self.used = True
        self.output.joinpath("public_initial_state.json").write_text(json.dumps(
            {"instruction": obs["instruction"], "robot_state": obs["robot_state"]}, default=serialize))
        content = [{"type": "text", "text": (
            "Write an ASPIRE Python skill to attempt this robot task using ONLY the public "
            "observation and listed tool functions. Return executable Python only. "
            "No file access, network calls, simulator imports, asset reading, hidden state, "
            "teleportation or reward queries. NumPy imports and ordinary math are allowed. "
            "Use bounded feedback loops. Each control call sends one action and waits for "
            "fresh observation. Coordinates are world XYZ meters and WXYZ quaternion. "
            "Both arms' measured states are available; other limbs hold measured state. "
            "Grippers use 1=open, 0=closed. localize_objects uses SAM3 and calibrated RGBD "
            "to return visible surface points, not exact centers or grasp TCPs. "
            "The selected sensor uses identity pinhole USD mounting and optical Y/Z flip. "
            "Do not use plan_grasp poses: gripper TCP orientation has not been calibrated. "
            "Preserve measured EE orientation where appropriate and use small incremental "
            "approach/lift/transport/release waypoints. Inspect updated observations and "
            "re-localize after moving objects. A lack of detections must raise, never use "
            "an invented world coordinate. Do not claim success; the evaluator decides it. "
            "No learned RoboDojo task-specific skill exists yet: this is one development "
            "attempt, not an evaluated frozen policy or a full ASPIRE learning campaign.\n\n"
            + "Instruction: " + obs["instruction"] + "\nRobot state: "
            + json.dumps(obs["robot_state"], default=serialize) + "\nAPI:\n" + api_docs)}]
        for name, camera in obs["cameras"].items():
            image = Image.fromarray(camera["images"]["rgb"])
            # Trusted coordinator records public image; policy doesn't decode.
            image.save(self.output / (name+"_initial.png"))
            buf = io.BytesIO(); image.save(buf, format="PNG")
            content += [{"type": "text", "text": "Camera: "+name},
                        {"type": "image_url", "image_url": {"url":
                         "data:image/png;base64,"+base64.b64encode(buf.getvalue()).decode()}}]
        response = requests.post("http://127.0.0.1:8112/chat/completions", json={
            "model": "deepseek-flash", "messages": [{"role": "user", "content": content}],
            "temperature": .2, "max_tokens": 20480}, timeout=240)
        response.raise_for_status()
        body = response.json()
        code = body["choices"][0]["message"]["content"]
        if not isinstance(code, str) or not code.strip():
            raise RuntimeError("model returned no task code")
        if code.strip().startswith("```"):
            match = re.fullmatch(r"```(?:python)?\s*\n(.*?)\n```", code.strip(), re.S)
            if not match:
                raise ValueError("expected one executable code block")
            code = match.group(1)
        compile(code, "<robodojo-task-skill>", "exec")
        self.output.joinpath("generated_skill.py").write_text(code+"\n")
        self.output.joinpath("model_metadata.json").write_text(json.dumps({
            "model": body.get("model"), "finish_reason": body["choices"][0].get("finish_reason"),
            "usage": body.get("usage"), "code_generation_calls": 1}))
        # Hold execution until human-readable inspection is complete. The
        # trusted coordinator writes this gate only after reviewing saved code.
        import time
        deadline = time.monotonic()+300
        while not self.output.joinpath("skill_reviewed.ok").exists():
            if time.monotonic() > deadline:
                raise TimeoutError("task code review gate not satisfied")
            time.sleep(.5)
        return code


class TrialModel(Model, ModelTemplate):
    """XPolicyLab wrapper; action dimensions come from the shared robot metadata."""
    def __init__(self, model_cfg, *, program_provider=None, tool_factory=None):
        cfg = dict(model_cfg)
        dims = get_robot_action_dim_info(cfg["env_cfg_type"])
        if "robot_action_dim_info" in cfg and cfg["robot_action_dim_info"] != dims:
            raise ValueError("adapter action dimensions differ from official robot metadata")
        if get_batch_size(cfg["env_cfg_type"]) != 1:
            raise ValueError("this development runner permits only one rollout")
        cfg["robot_action_dim_info"] = dims
        super().__init__(cfg, program_provider=program_provider or ProgramProvider(cfg.get("output_dir", "/work")),
                         tool_factory=tool_factory or TaskTools)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--offline-smoke", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--reviewed-skill", help="Frozen development skill already reviewed by the coordinator")
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text())
    if args.self_check:
        import os
        assert not Path("/home/user/.claude/settings.json").exists()
        assert not Path("/home/xuanzhi/.config/aspire-robodojo/provider.json").exists()
        assert not any(os.environ.get(key) for key in (
            "OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_AUTH_TOKEN", "DEEPSEEK_API_KEY"))
        print("Policy imports passed; host credential paths and keys are absent")
        return
    def offline_program(obs, docs):
        rgb = obs["cameras"]["cam_head"]["images"]["rgb"]
        assert rgb.shape == (8, 8, 3) and rgb.dtype == np.uint8
        assert rgb[0, 0, 0] > 200 and rgb[0, 0, 2] < 10
        assert "hidden_goal" not in obs["robot_state"]
        return "open_gripper(arm='left')"
    if args.reviewed_skill:
        frozen = Path(args.reviewed_skill).read_text()
        compile(frozen, args.reviewed_skill, "exec")
        provider = lambda obs, docs: frozen
    else:
        provider = offline_program if args.offline_smoke else ProgramProvider(args.output)
    model = TrialModel(cfg, program_provider=provider, tool_factory=TaskTools)
    server = PolicyServer(model, PolicyServerConfig(host="127.0.0.1", port=19081, ws_ping_timeout_s=120))
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(server.serve_forever())
    finally:
        model.close()


if __name__ == "__main__":
    main()
