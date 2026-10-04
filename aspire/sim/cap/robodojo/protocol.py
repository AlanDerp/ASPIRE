# SPDX-License-Identifier: Apache-2.0
"""Public XPolicyLab observation/action contract; no simulator imports."""
from dataclasses import dataclass
from collections.abc import Mapping
import copy
import numpy as np


def vector(value, size, name):
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (size,) or not np.isfinite(result).all():
        raise ValueError(f"{name} must be a finite ({size},) vector")
    return result.copy()


@dataclass(frozen=True)
class RobotSpec:
    arm_dim: tuple[int, ...]
    ee_dim: tuple[int, ...]
    action_type: str

    def __post_init__(self):
        if self.action_type not in ("joint", "ee"):
            raise ValueError("action_type must be joint or ee (absolute world pose)")
        if len(self.arm_dim) not in (1, 2) or len(self.arm_dim) != len(self.ee_dim):
            raise ValueError("provide matching dimensions for one or two arms")
        if any(type(n) is not int or n < 1 for n in (*self.arm_dim, *self.ee_dim)):
            raise ValueError("robot dimensions must be positive integers")

    @classmethod
    def from_config(cls, cfg):
        dims = cfg["robot_action_dim_info"]
        return cls(tuple(dims["arm_dim"]), tuple(dims["ee_dim"]), cfg["action_type"])

    @property
    def prefixes(self):
        return ("",) if len(self.arm_dim) == 1 else ("left_", "right_")

    def prefix(self, arm=None):
        if len(self.arm_dim) == 1 and arm in (None, "single"):
            return ""
        if len(self.arm_dim) == 2 and arm in ("left", "right"):
            return arm + "_"
        raise ValueError("specify left/right for a dual-arm robot, single for a single arm")

    def validate_action(self, action):
        if not isinstance(action, Mapping):
            raise ValueError("action must be a dictionary")
        dimensions = {}
        for prefix, arm_dim, ee_dim in zip(self.prefixes, self.arm_dim, self.ee_dim):
            dimensions[prefix + ("arm_joint_state" if self.action_type == "joint" else "ee_pose")] = arm_dim if self.action_type == "joint" else 7
            dimensions[prefix + "ee_joint_state"] = ee_dim
        if set(action) != set(dimensions):
            raise ValueError(f"action must contain exactly {sorted(dimensions)}")
        result = {k: vector(action[k], n, k) for k, n in dimensions.items()}
        for key, value in result.items():
            if key.endswith("ee_pose") and not np.isclose(np.linalg.norm(value[3:]), 1., atol=1e-3):
                raise ValueError("pose quaternion must be unit WXYZ; pose is [x,y,z,qw,qx,qy,qz]")
            if key.endswith("ee_joint_state") and len(value) == 1 and not 0 <= value[0] <= 1:
                raise ValueError("scalar gripper command must be in [0,1]")
        return result

    def hold_action(self, state):
        keys = []
        for prefix in self.prefixes:
            keys.extend([prefix + ("arm_joint_state" if self.action_type == "joint" else "ee_pose"), prefix + "ee_joint_state"])
        missing = set(keys) - set(state)
        if missing:
            raise ValueError(f"observation lacks states required to hold robot: {sorted(missing)}")
        return self.validate_action({k: state[k] for k in keys})


def adapt_observation(obs, camera_aliases=None):
    """Map already-decoded RGB and public state to ASPIRE camera dictionaries.

    Depth is float32 meters; approximate_depth is uint16 millimeters.
    Both extrinsic_matrix (RoboDojo) and extrinsics_matrix (XPolicyLab) are
    accepted as camera-to-world transforms, without changing camera axes.
    Encoded images, private scene metadata and reward data are never forwarded.
    """
    if not isinstance(obs, Mapping) or not isinstance(obs.get("state"), Mapping) or not isinstance(obs.get("vision"), Mapping):
        raise ValueError("expected a single XPolicyLab observation with vision and state")
    instruction = obs.get("instruction", obs.get("instructions", ""))
    if not isinstance(instruction, str):
        raise ValueError("single-rollout instruction must be a string")
    state_keys = {prefix + key for prefix in ("", "left_", "right_")
                  for key in ("arm_joint_state", "ee_joint_state", "ee_pose", "tcp_pose", "delta_ee_pose")}
    result = {"instruction": instruction, "robot_state": {
        k: copy.deepcopy(v) for k, v in obs["state"].items() if k in state_keys}}
    cameras = {}
    for name, camera in obs["vision"].items():
        rgb = np.asarray(camera["color"])
        if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
            raise ValueError(f"{name}: expected decoded uint8 RGB (H,W,3)")
        images = {"rgb": rgb.copy()}
        if "depth" in camera or "approximate_depth" in camera:
            approximate = "depth" not in camera
            raw = np.asarray(camera["approximate_depth" if approximate else "depth"])
            if approximate and raw.dtype != np.uint16:
                raise ValueError("approximate_depth must be uint16 millimeters")
            if not approximate and not np.issubdtype(raw.dtype, np.floating):
                raise ValueError("depth must be floating point meters")
            if raw.shape == rgb.shape[:2] + (1,):
                raw = raw[..., 0]
            if raw.shape != rgb.shape[:2]:
                raise ValueError(f"{name}: depth and RGB dimensions do not match")
            depth = raw.astype(np.float32) / (1000. if approximate else 1.)
            depth[~np.isfinite(depth) | (depth < 0)] = 0
            images["depth"] = depth[..., None]
        adapted = {"images": images}
        if "intrinsic_matrix" in camera:
            k = np.asarray(camera["intrinsic_matrix"], dtype=np.float64)
            if k.shape != (3, 3) or not np.isfinite(k).all() or k[0, 0] <= 0 or k[1, 1] <= 0:
                raise ValueError(f"{name}: invalid camera intrinsics")
            adapted["intrinsics"] = k.copy()
        matrices = [camera[k] for k in ("extrinsic_matrix", "extrinsics_matrix") if k in camera]
        if matrices:
            t = np.asarray(matrices[0], dtype=np.float64)
            if t.shape != (4, 4) or not np.isfinite(t).all() or not np.allclose(t[3], [0, 0, 0, 1]):
                raise ValueError(f"{name}: invalid camera-to-world matrix")
            if len(matrices) == 2 and not np.allclose(t, matrices[1]):
                raise ValueError(f"{name}: conflicting camera extrinsics")
            adapted["pose_mat"] = t.copy()
        cameras[name] = adapted
    result["cameras"] = cameras
    aliases = camera_aliases or {}
    for alias, name in aliases.items():
        if alias in result or name not in cameras:
            raise ValueError(f"invalid camera alias {alias!r}: {name!r}")
        result[alias] = copy.deepcopy(cameras[name])
    return result
