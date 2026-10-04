# SPDX-License-Identifier: Apache-2.0
"""Robot-independent skill helpers. Coordinates remain RoboDojo world/WXYZ."""
import inspect
import numpy as np
from .protocol import adapt_observation, vector


class RoboDojoTools:
    def __init__(self, bridge, camera_aliases=None, segment_fn=None, grasp_fn=None):
        self.bridge = bridge
        self.spec = bridge.spec
        self.camera_aliases = camera_aliases
        self.segment_fn = segment_fn
        self.grasp_fn = grasp_fn

    def functions(self):
        return {name: getattr(self, name) for name in (
            "get_observation", "move_to_joints", "goto_pose", "set_gripper",
            "open_gripper", "close_gripper", "segment_sam3_text_prompt", "plan_grasp",
        )}

    def combined_doc(self):
        return "\n\n".join(f"{name}{inspect.signature(fn)}\n{inspect.getdoc(fn)}" for name, fn in self.functions().items())

    def get_observation(self):
        """Return public RGB/depth cameras and measured robot_state; depth is meters."""
        return adapt_observation(self.bridge.observe(), self.camera_aliases)

    def move_to_joints(self, joints, arm=None):
        """Send absolute joint targets in radians and wait for next observation.

        arm: single, left or right. Joint mode only. Other arm and grippers hold
        measured state. One call is one benchmark control action, not a promise
        that the target has been reached; inspect feedback for closed-loop motion.
        """
        if self.spec.action_type != "joint":
            raise ValueError("move_to_joints requires joint action mode")
        action = self.spec.hold_action(self.bridge.observe()["state"])
        prefix = self.spec.prefix(arm)
        action[prefix + "arm_joint_state"] = joints
        self.bridge.send(action)

    def goto_pose(self, position, quaternion, arm=None):
        """Send absolute world XYZ (meters) and unit WXYZ quaternion.

        EE mode only; RoboDojo owns IK/interpolation. Waits for fresh feedback.
        Other arm and grippers hold measured state. No Panda TCP offset is added.
        """
        if self.spec.action_type != "ee":
            raise ValueError("goto_pose requires ee action mode")
        action = self.spec.hold_action(self.bridge.observe()["state"])
        action[self.spec.prefix(arm) + "ee_pose"] = np.concatenate([
            vector(position, 3, "position"), vector(quaternion, 4, "quaternion")])
        self.bridge.send(action)

    def set_gripper(self, value, arm=None):
        """Set normalized scalar parallel-jaw opening [0,1], holding all arm poses.

        Only scalar grippers are supported by this helper, not dexterous hands.
        """
        prefix = self.spec.prefix(arm)
        index = self.spec.prefixes.index(prefix)
        if self.spec.ee_dim[index] != 1:
            raise ValueError("set_gripper supports scalar parallel-jaw grippers only")
        action = self.spec.hold_action(self.bridge.observe()["state"])
        action[prefix + "ee_joint_state"] = [value]
        self.bridge.send(action)

    def open_gripper(self, arm=None):
        """Open the normalized scalar gripper (1.0); wait for fresh observation."""
        self.set_gripper(1., arm)

    def close_gripper(self, arm=None):
        """Close the normalized scalar gripper (0.0); wait for fresh observation."""
        self.set_gripper(0., arm)

    def segment_sam3_text_prompt(self, rgb, text):
        """Segment decoded RGB with the existing A100-side SAM3 client.

        Returns client mask/box/score dictionaries. No simulator segmentation.
        Client imports happen only when this helper is invoked.
        """
        if self.segment_fn is None:
            from aspire.sim.cap.integrations.vision.sam3 import init_sam3
            self.segment_fn = init_sam3()
        return self.segment_fn(rgb, text)

    def plan_grasp(self, depth, intrinsics, segmentation, segmap_id=1):
        """Plan camera-frame grasps from depth (meters), K and instance labels.

        Returns the existing Contact-GraspNet client's native tuple. These are
        camera-frame grasp transforms, NOT RoboDojo world-frame action poses.
        Calibrate camera optical axes and gripper/TCP frames before goto_pose.
        """
        if self.grasp_fn is None:
            from aspire.sim.cap.integrations.vision.graspnet import init_contact_graspnet
            self.grasp_fn = init_contact_graspnet()
        return self.grasp_fn(np.asarray(depth).squeeze(-1) if np.asarray(depth).ndim == 3 else depth, intrinsics, segmentation, segmap_id)
