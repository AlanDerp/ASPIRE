# ASPIRE-side RoboDojo adapter

Implemented in `cap/robodojo/`. This is the **policy-side code adaptation** phase.
No RoboDojo/XPolicyLab installation, websocket server, simulator, robot service,
asset download or dual-host deployment is included or started.

## Entry point and existing ASPIRE integration

`aspire.sim.cap.robodojo.policy.Model` implements XPolicyLab's lifecycle:
`reset()`, `update_obs(obs)`, `get_action()`, and the one-environment batch
variants. A future XPolicyLab `policy/ASPIRE/model.py` can import/re-export this
class. Launch scripts, deploy.yml and the environment-side client belong to the
next phase; they are deliberately not created here.

The adapter executes reviewed ASPIRE Python skills through curated helper
functions. The default reads `program_path` once at construction (a frozen skill,
not a weights checkpoint). Alternatively the existing code-generation / skill
selection coordinator can supply `program_provider(public_obs, api_docs) -> str`
when constructing `Model`. The callback sees only public observation and tool
documentation. It must preserve development/held-out boundaries; do not run
failure-driven skill updates on held-out layouts. Existing LIBERO coordinators,
knowledge files and modified LLM client are unchanged.

The adapter starts a daemon skill thread on the first observation. A blocking
control helper yields one validated action; `get_action()` returns `[action]`.
The helper resumes only when the client supplies the next observation. Every
chunk has one action, so subsequent skill logic uses fresh feedback. Completed
programs hold measured state until the official evaluator ends the episode.
A skill exception fails the policy request; it is not disguised as a hold or a
success. The adapter does not invent rewards or simulator success predicates.

Reset cancels queued commands and joins the old worker. A non-cooperative skill
causes reset to fail and requires restarting the isolated policy process. Threads
are a lifecycle mechanism, **not a security sandbox**. Production execution must
use the repository's isolated-worker/container boundaries without secrets or
sensitive mounts. Unrestricted Python imports remain possible, as with ASPIRE's
existing in-process executor. No simulator handle or ground-truth helper is
injected into generated code.

## Configuration

`env_configs/robodojo/adapter.example.json` is an adapter configuration example,
not a simulator launch config. Its joint counts and camera names must be checked
against the chosen official robot config before deployment. No robot, task,
seed, model or experiment protocol is selected by this example.

Required fields:

- `action_type`: `joint` (absolute radians) or `ee` (absolute world pose).
- `robot_action_dim_info`: explicit `arm_dim` and `ee_dim` for one/two arms.
- `program_path`: absolute path to a reviewed, frozen RoboDojo skill (unless an
  explicit program_provider callback is passed in-process).

Optional fields: `camera_aliases` maps ASPIRE aliases to native camera names;
`request_timeout_s` bounds action/feedback waits; `reset_timeout_s` bounds cleanup.
Use `Model.close()` in caller cleanup even when the final action ends an episode.
The one-environment batch adapter accepts `get_action_batch(obs=[env_idx])`, as
used by the public XPolicyLab demo deploy loop, and rejects multiple environments.

## Observation / action semantics

- Input images are already-decoded uint8 RGB; no JPEG decoding or channel swap.
- `depth` is floating-point meters; `approximate_depth` is uint16 millimeters and
  is converted to meters. Invalid/negative depth is zeroed; absent depth or
  calibration is not synthesized.
- Public images become `cameras[name]["images"]["rgb"/"depth"]`. Explicit aliases
  can provide `agentview`, etc. Camera intrinsics map to `intrinsics`.
- Both native `extrinsic_matrix` and documented `extrinsics_matrix` map to
  `pose_mat`. Their camera-to-world matrix is preserved **without assuming an
  optical-axis correction**. RoboDojo currently reports the camera mount xform;
  calibrate the optical frame before transforming GraspNet grasps into world
  actions. Do not blindly reuse LIBERO optical frame/TCP assumptions.
- Robot state is whitelisted into `robot_state`; hidden scene/goal metadata is
  excluded. Required hold-state fields must be present; no all-zero defaults.
- EE actions use `[x,y,z,qw,qx,qy,qz]`, unit WXYZ quaternion, world coordinates.
  No Franka/Panda offset or kinematic model is reused. Official RoboDojo owns IK.
- Single-arm actions use unprefixed keys. Dual-arm actions use `left_`/`right_`.
  Every action includes both arms and grippers; inactive limbs hold measured
  state. Scalar grippers use normalized opening 0=closed, 1=open. Dexterous hand
  actions can use the dimension contract, but scalar gripper helpers reject them.

## Curated helpers

`get_observation`, `move_to_joints`, `goto_pose`, `set_gripper`, `open_gripper`,
`close_gripper`, `segment_sam3_text_prompt`, `plan_grasp`.

Motion helpers send one target action and wait for one feedback frame. They do
not claim that the target is reached. Write closed-loop checks using measured
state. Do not mix joint and EE actions in one policy configuration. Dual-arm
calls require `arm="left"` or `arm="right"`; the other arm holds position.

SAM3 / Contact-GraspNet reuse existing ASPIRE clients via lazy imports only when
called; imports/constructors never contact services. `plan_grasp` passes 2-D
meter depth, intrinsics, segmentation labels and `segmap_id` to the existing
client, returning its `(grasps, scores, contact_points)` tuple in camera frame.
No pose conversion to the new gripper is fabricated. Public calibration and TCP
validation are required before using the grasp as an EE action.

Example reviewed skill fragment (EE mode, correct robot/calibration assumed):

```python
obs = get_observation()
state = obs["robot_state"]
pose = state["left_ee_pose"].copy()
# An illustrative relative movement based only on measured robot state.
goto_pose(pose[:3] + [0, 0, 0.01], pose[3:], arm="left")
```

This is an interface example, not an oracle or a benchmark task solution.

## Offline validation only

From `aspire/sim`, use the existing interpreter with NumPy and pytest. On the
A100 server this is `.venv-libero`; these tests only use its CPU Python packages:

```bash
PYTHONPATH=../.. .venv-libero/bin/python -m pytest tests/robodojo -q
```

Tests use synthetic observations and injected perception functions. They verify
closed-loop action/feedback ordering, dual-arm holds, coordinate ordering,
depth units, invalid actions, reset cancellation, timeout/error propagation,
single-env batch keywords and frozen skill loading. They do not instantiate
Isaac/MuJoCo, call LLMs, contact perception services or access a physical robot.

## Upstream contracts checked on 2026-10-03

- https://github.com/XPolicyLab/XPolicyLab/blob/main/policy/demo_policy/model.py
- https://github.com/XPolicyLab/XPolicyLab/blob/main/policy/demo_policy/deploy.py
- https://github.com/RoboDojo-Benchmark/RoboDojo/blob/main/env/observation_manager/obs_manager.py
- https://github.com/RoboDojo-Benchmark/RoboDojo/blob/main/env/camera_manager/camera_manager.py
- https://github.com/RoboDojo-Benchmark/RoboDojo/blob/main/src/eval_client/eval_env.py

Deployment must pin and recheck upstream versions. Transport, real camera/TCP
calibration, held-out protocol eligibility, memory peaks and benchmark success
rates have not been validated in this phase.
