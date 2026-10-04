# SPDX-License-Identifier: Apache-2.0
import time
import numpy as np
import pytest
from aspire.sim.cap.robodojo import Model, RobotSpec, adapt_observation
from aspire.sim.cap.robodojo.bridge import RolloutBridge
from aspire.sim.cap.robodojo.tools import RoboDojoTools


def observation(dual=False, env_idx=0):
    state = {}
    for p in (["left_", "right_"] if dual else [""]):
        state.update({p + "arm_joint_state": np.array([.1, .2, .3]),
                      p + "ee_joint_state": np.array([.4]),
                      p + "ee_pose": np.array([1., 2., 3., 1., 0., 0., 0.])})
    return {"env_idx": env_idx, "instruction": "move the object",
            "vision": {"cam_head": {"color": np.zeros((2, 3, 3), dtype=np.uint8),
                        "approximate_depth": np.full((2, 3), 1250, dtype=np.uint16),
                        "intrinsic_matrix": np.eye(3), "extrinsic_matrix": np.eye(4)}},
            "state": state}


def model(code, dual=False, mode="joint", timeout=2.):
    return Model({"action_type": mode, "request_timeout_s": timeout,
                  "robot_action_dim_info": {"arm_dim": [3, 3] if dual else [3],
                                            "ee_dim": [1, 1] if dual else [1]}},
                 program_provider=lambda obs, docs: code)


def test_observation_depth_alias_and_public_boundary():
    native = observation()
    native['state']['object_ground_truth'] = [1, 2, 3]
    native['hidden_layout'] = 'not public'
    result = adapt_observation(native, {'agentview': 'cam_head'})
    assert result['agentview']['images']['depth'].shape == (2, 3, 1)
    np.testing.assert_allclose(result['agentview']['images']['depth'], 1.25)
    assert 'object_ground_truth' not in result['robot_state']
    assert 'hidden_layout' not in result
    result['agentview']['images']['rgb'][0] = 255
    assert not native['vision']['cam_head']['color'].any()


def test_float_depth_and_plural_extrinsics():
    obs = observation()
    c = obs['vision']['cam_head']
    c['depth'] = np.ones((2, 3, 1), dtype=np.float32) * 2
    c['extrinsics_matrix'] = c.pop('extrinsic_matrix')
    result = adapt_observation(obs)['cameras']['cam_head']
    np.testing.assert_allclose(result['images']['depth'], 2)
    np.testing.assert_allclose(result['pose_mat'], np.eye(4))


@pytest.mark.parametrize('field,value', [
    ('color', np.zeros((2, 3, 4), dtype=np.uint8)),
    ('depth', np.ones((2, 3), dtype=np.uint16)),
    ('approximate_depth', np.ones((2, 3), dtype=np.float32)),
    ('intrinsic_matrix', np.zeros((3, 3))),
    ('extrinsic_matrix', np.zeros((4, 4))),
])
def test_bad_camera_data_rejected(field, value):
    obs = observation(); obs['vision']['cam_head'][field] = value
    with pytest.raises(ValueError): adapt_observation(obs)


@pytest.mark.parametrize('bad', [
    {'arm_joint_state': [1, 2], 'ee_joint_state': [.5]},
    {'arm_joint_state': [1, 2, float('nan')], 'ee_joint_state': [.5]},
    {'arm_joint_state': [1, 2, 3], 'ee_joint_state': [2]},
    {'ee_pose': [0, 0, 0, 1, 0, 0, 0], 'ee_joint_state': [.5]},
])
def test_action_shape_mode_and_finiteness(bad):
    with pytest.raises(ValueError): RobotSpec((3,), (1,), 'joint').validate_action(bad)


def test_dual_arm_closed_loop_preserves_other_arm_and_waits_for_feedback():
    m = model("move_to_joints([.5,.6,.7], arm='left')\n"
              "assert get_observation()['robot_state']['left_arm_joint_state'][0] == .5\n"
              "close_gripper(arm='right')", dual=True)
    obs = observation(True)
    try:
        m.update_obs(obs)
        first = m.get_action()[0]
        np.testing.assert_allclose(first['right_arm_joint_state'], [.1,.2,.3])
        np.testing.assert_allclose(first['left_ee_joint_state'], [.4])
        with pytest.raises(RuntimeError, match='twice'): m.get_action()
        obs['state'].update(first); m.update_obs(obs)
        second = m.get_action()[0]
        assert second['right_ee_joint_state'][0] == 0
        np.testing.assert_allclose(second['left_arm_joint_state'], [.5,.6,.7])
        obs['state'].update(second); m.update_obs(obs)
        # Completed skill holds measured robot; no all-zero fallback.
        hold = m.get_action()[0]
        np.testing.assert_allclose(hold['left_arm_joint_state'], [.5,.6,.7])
    finally: m.close()


def test_ee_pose_uses_world_xyz_and_wxyz_without_panda_offset():
    m = model("goto_pose([.4,.5,.6], [1,0,0,0])", mode='ee')
    try:
        m.update_obs(observation())
        action = m.get_action()[0]
        np.testing.assert_allclose(action['ee_pose'], [.4,.5,.6,1,0,0,0])
        assert 'arm_joint_state' not in action
    finally: m.close()


def test_reset_cancels_pending_action_and_clears_namespace():
    m = model("assert 'leak' not in globals()\nleak = 1\nopen_gripper()")
    try:
        m.update_obs(observation()); m.get_action()
        m.reset()
        assert m.bridge is None
        m.update_obs(observation()); assert m.get_action()[0]['ee_joint_state'][0] == 1
    finally: m.close()


def test_skill_failure_is_not_silently_converted_to_hold():
    m = model("raise ValueError('bad skill')")
    try:
        m.update_obs(observation())
        with pytest.raises(RuntimeError, match='bad skill'): m.get_action()
    finally: m.close()


def test_only_single_rollout_and_batch_keyword_contract():
    m = model("open_gripper()")
    try:
        with pytest.raises(ValueError): m.update_obs_batch([observation(), observation()])
        m.update_obs_batch([observation(env_idx=3)])
        with pytest.raises(ValueError): m.get_action_batch(obs=[4])
        assert len(m.get_action_batch(obs=[3])[0]) == 1
    finally: m.close()


def test_feedback_timeout_closes_episode():
    m = model("open_gripper()", timeout=.1)
    try:
        m.update_obs(observation()); m.get_action()
        time.sleep(.2)
        with pytest.raises(RuntimeError, match='closed'): m.get_action()
    finally: m.close()


def test_encoded_images_are_not_decoded_again():
    obs = observation(); obs['vision']['cam_head']['color'] = b'jpeg'
    with pytest.raises(ValueError): adapt_observation(obs)


def test_grasp_client_receives_segmap_id_and_2d_depth():
    received = []
    bridge = RolloutBridge(RobotSpec((3,), (1,), 'joint')); bridge.update(observation())
    tools = RoboDojoTools(bridge, grasp_fn=lambda *args: received.append(args) or ('grasps','scores','points'))
    assert tools.plan_grasp(np.ones((2,3,1)), np.eye(3), np.ones((2,3)), 7)[0] == 'grasps'
    assert received[0][0].shape == (2,3)
    assert received[0][3] == 7


def test_frozen_program_file_is_loaded_once(tmp_path):
    path = tmp_path / 'skill.py'; path.write_text('close_gripper()')
    m = Model({'program_path': str(path), 'action_type': 'joint',
               'robot_action_dim_info': {'arm_dim': [3], 'ee_dim': [1]}})
    path.write_text('open_gripper()')
    try:
        m.update_obs(observation()); assert m.get_action()[0]['ee_joint_state'][0] == 0
    finally: m.close()


@pytest.mark.parametrize('timeout', [0, -1, float('nan'), float('inf')])
def test_invalid_timeout_rejected_before_execution(timeout):
    with pytest.raises(ValueError, match='finite and positive'):
        RolloutBridge(RobotSpec((3,), (1,), 'joint'), timeout)
    for key in ('request_timeout_s', 'reset_timeout_s'):
        with pytest.raises(ValueError, match='finite and positive'):
            Model({'action_type': 'joint', key: timeout,
                   'robot_action_dim_info': {'arm_dim': [3], 'ee_dim': [1]}},
                  program_provider=lambda obs, docs: '')
