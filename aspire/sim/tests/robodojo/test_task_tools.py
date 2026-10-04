import numpy as np
import pytest
from aspire.sim.cap.robodojo.protocol import RobotSpec
from aspire.sim.cap.robodojo.task_tools import TaskTools


class FeedbackBridge:
    def __init__(self):
        self.spec = RobotSpec((6, 6), (1, 1), "ee")
        self.commands = []
        self.state = {"left_ee_pose": np.array([0., 0., 1., 1., 0., 0., 0.]),
                      "right_ee_pose": np.array([1., 0., 1., 1., 0., 0., 0.]),
                      "left_ee_joint_state": [1.], "right_ee_joint_state": [0.]}

    def observe(self):
        pose = np.eye(4); pose[2, 3] = 2
        return {"instruction": "development task", "state": self.state,
                "vision": {"cam_head": {"color": np.zeros((4, 4, 3), dtype=np.uint8),
                    "depth": np.ones((4, 4), dtype=np.float32),
                    "intrinsic_matrix": np.array([[1.,0.,1.5],[0.,1.,1.5],[0.,0.,1.]]),
                    "extrinsic_matrix": pose}}}

    def send(self, action):
        action = self.spec.validate_action(action)
        self.commands.append(action)
        for key in self.state:
            self.state[key] = np.array(action[key], copy=True)


def test_public_rgbd_world_projection_and_empty_detection():
    bridge = FeedbackBridge()
    tools = TaskTools(bridge, segment_fn=lambda rgb, text: [{
        "mask": np.ones((4,4), dtype=bool), "box": [0,0,4,4], "score": .9, "label": text}])
    results = tools.localize_objects("bowl")
    assert np.allclose(results[0]["point"], [0,0,1])
    tools.segment_fn = lambda rgb, text: []
    assert tools.localize_objects("missing") == []


def test_incremental_motion_uses_feedback_and_holds_other_arm():
    bridge = FeedbackBridge(); tools = TaskTools(bridge)
    tools.move_ee([.08,0,1], tolerance=.001)
    assert len(bridge.commands) == 4
    points = np.array([a["left_ee_pose"][:3] for a in bridge.commands])
    assert np.all(np.linalg.norm(np.diff(points, axis=0), axis=1) <= .020001)
    assert np.allclose(points[-1], [.08,0,1])
    assert all(np.allclose(a["right_ee_pose"], [1,0,1,1,0,0,0]) for a in bridge.commands)


def test_motion_cannot_silently_exhaust_budget():
    bridge = FeedbackBridge(); tools = TaskTools(bridge)
    with pytest.raises(RuntimeError, match="not reached"):
        tools.move_ee([1,0,1], max_frames=2)
    with pytest.raises(ValueError): tools.wait_frames(0)


def test_raw_sam_queries_filter_low_scores_and_duplicate_masks():
    bridge = FeedbackBridge()
    mask = np.ones((4,4), dtype=bool)
    tools = TaskTools(bridge, segment_fn=lambda rgb, text: [
        {"mask":mask, "score":.1}, {"mask":mask, "score":.9}, {"mask":mask, "score":.8}])
    result = tools.localize_objects("bowl")
    assert len(result) == 1 and result[0]["score"] == .9
    with pytest.raises(ValueError): tools.localize_objects("bowl", min_score=-1)
