---
name: manipulation
description: Non-pick-and-place manipulation patterns — drawer opening/closing, knob/switch turning, pushing, and other articulated object interactions. Grows through experiment.
---

# Manipulation — Articulated Object Patterns

> This skill covers tasks that are **not** pick-and-place: interacting with drawers, knobs,
> switches, and other articulated objects. Discovered through experiment — add entries as
> you validate them.

---


### Validated Parameters

Add scene-specific validated parameters here as you discover them.

---

## Motion Safety: Never Retry a Descent by Re-Solving From Home

**Trigger**: a `move_tcp`-style helper that verifies its Cartesian error and, on a miss, calls
`goto_home_joint_position()` and re-solves, used on a descent toward a manipulable object. The
warm-started re-solve converges to a *different, more strained* pose, so the retry passes its own
error check while the resulting motion sweeps the fingers through the object.

```python
# WRONG: a home-retry on a descent can sweep into the object
if err > tol:
    goto_home_joint_position(); j = solve_ik(pos, quat); move_to_joints(j)

# RIGHT: report the error; retry only where a re-approach cannot collide
# (the high approach pose), never mid-descent.
move_tcp(pos, quat, retries=0)
```

**Why it works + evidence**: on `libero_goal_swap/put_the_wine_bottle_on_top_of_the_cabinet`, seed 52
v1 logged `move_tcp miss 0.0526 … attempt 0` and the home retry left the wine bottle **lying flat on
the table** — knocked over, never grasped. Setting `retries=0` by default and allowing a retry only
at the high approach pose (`gz + 0.10`) turned it into a clean neck grasp. Contributed to flipping the
seven v1 failures (52, 53, 54, 58, 61, 62, 65; 8/15 → 15/15). Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_wine_bottle_on_top_of_the_cabinet/fix_code.py`
lines 71–94; 2026-09-14.

**Inside a per-candidate loop, a home reset does not just disturb the scene — it spends the episode.**
On `libero_spatial_swap/pick_up_the_black_bowl_on_the_wooden_cabinet_and_place_it_on_the_plate` the
template's `except` branch called `goto_home_joint_position()`, and seed 59's baseline trace records
**9** such calls: 8 wall attempts dead inside carry attempt 2, plus one after `place` failed. By then
every subsequent action raised `ValueError: executing action in terminated episode`, carry attempt 2
went 0-for-8, and the run ended at `reward = 0.0`. A home move is the most expensive possible recovery
*and* the least useful starting point for the next candidate. Retreat locally instead:

```python
except Exception as exc:
    print("  %s failed: %s %s" % (tag, type(exc).__name__, str(exc)[:80]), flush=True)
    try:
        c0 = tcp()
        hop_to(c0[0], c0[1], max(c0[2], bowl["top"] + 0.16), quat)   # cheap, stays local
    except Exception:
        pass
```

**Evidence**: baseline 9 home moves and `reward=0.0` on seed 59; the shipped run records **exactly 1**
home move on every seed — including seed 59 — and scores 15/15. Same `fix_code.py`, `except` branch of
the pinch loop in `run`; 2026-09-15. This is the loop-shaped case of the two rules above: home is
wrong under an object, wrong while a fixture matters, and wrong as a candidate-loop recovery.

**The pinch itself can air purely because it started from home.** The cases above are about *cost*,
*collision*, and *budget*; this one is about grip success. On
`libero_object_task/pick_up_the_chocolate_pudding_and_place_it_in_the_basket` a pinch attempted
immediately after `goto_home_joint_position()` reliably reads air, while the **second and later**
attempts at the same xy — reached from the previous pose — grip. A probe holding the tilt *fixed* and
varying only the approach path isolates it from every other variable:

| approach to the pinch | aperture after close |
|---|---|
| from home | 0.0148 (air) |
| continued from the previous pose | 0.4635 (hold) |
| continued | 0.4619 (hold) |
| from home again | air |
| continued | air |
| from home | air |

So with a homing ladder, the very same tilt and height that grips when reached from a neighbouring
pose airs when reached from home — and the ladder's first rung is then unrepresentative of the rest.
Fix: `goto_home_joint_position()` **once**, before the ladder, and never inside it; within the ladder
the arm returns straight to `(cx, cy, top + 0.10)` and descends. **Corollary — a home→far-x
`goto_pose` can settle into a fallback orientation**: one attempt reported the tool axis 60° off
vertical and the pads at x = 0.648 against a commanded 0.763. Log the achieved orientation each attempt
(`axis_z` from the reported quaternion) so a fallback pose is visible in the trace rather than
mysterious. Source:
`outputs/working_codes/libero_object_task_pick_up_the_chocolate_pudding_and_place_it_in_the_basket_fix.py`
— `grasp_target`, lines 261–275; 2026-09-16.

---

## Measure the TCP, Not the Hand: Inverting the TCP Offset

**Trigger**: any closed-loop check of a `solve_ik` move. `robot_cartesian_pos` reports the **hand**
frame, which sits ~0.10 m above the tool tip, so comparing it directly against the commanded pose
mixes a constant into the error signal.

```python
def achieved_tcp():
    """World position the gripper's TCP actually reached.

    solve_ik(position, quat) targets EE = position + R @ (0, 0, -0.1), so the
    inverse relation is TCP = EE + 0.1 * R[:, 2].
    """
    e = ee_pose()
    q = e[3:7]
    R = Rotation.from_quat([q[1], q[2], q[3], q[0]]).as_matrix()   # wxyz -> xyzw
    return e[:3] + 0.1 * R[:, 2]
```

**Why it works + evidence**: a first diagnostic probe used the sign-flipped form and reported a
constant **21.5 cm** error on every move, which nearly sent the diagnosis down a false path. With the
correct sign, the physical kinematic floor at TCP z ≈ 0.119 m appears immediately. This measurement is
what makes both the floor-aware descent (see [grasp.md](grasp.md)) and the no-home-retry rule above
possible. For a perfectly top-down gripper the relation reduces to `EE - (0,0,0.10)`; the general form
matters because a converged orientation tilts a few degrees (`R[:,2] = [0.09, 0.003, -0.996]`
measured). Source: `.../put_the_wine_bottle_on_top_of_the_cabinet/fix_code.py` lines 55–64;
2026-09-14.

**Refinement — the constant is not one offset but two, and the *pads* are the frame that matters.**
On `libero_object_task/pick_up_the_chocolate_pudding_and_place_it_in_the_basket` the reported frame
measured **0.107 m** along the tool's +z from the *commanded* point (top-down: 0.107 above — commanded
eef z 0.200 → reported 0.310, 0.100 → 0.213, and a 45° tilt → +0.078 = 0.107·cos 45°), and the finger
pads hang a further **0.025 m** below the command, so the pads sit 0.132 m along tool +z from the
reported frame. Write all three explicitly rather than carrying one number:

```python
EEF_FROM_REP = 0.107
PAD_FROM_EEF = 0.025
PAD_FROM_REP = EEF_FROM_REP + PAD_FROM_EEF

def eef_point():                    # world position of the commanded tool point
    o = cart()
    return o[:3] + quat_R(o[3:7]) @ np.array([0.0, 0.0, EEF_FROM_REP])

def pad_point():                    # estimated world position of the finger pads
    o = cart()
    return o[:3] + quat_R(o[3:7]) @ np.array([0.0, 0.0, PAD_FROM_REP])
```

The pinch height then follows from commanding the **pads**, not the reported frame:
`z_cmd = z_pad - Rz * PAD_FROM_EEF` with `Rz = (quat_R(q) @ [0, 0, 1])[2]`.

**The expensive consequence is a rejected grasp, not a visible error.** A gate that compares a
*reported* z against an *object-space* z is wrong by up to 0.13 m, and its failure mode is silence: it
rejects a pose that would have worked. Writing this down removed two false readings from one session —
a "descent floor at meas 0.222" and a "rejected: fingers still above the object top" — while the grasp
was in fact viable. Both relations were self-consistent to ~1 mm once expressed this way, which is why
a probe beats an argument: a table-contact sweep (commanded 0.200/0.100/0.050 → reported
0.310/0.212/0.163) plus an open-pad stall (reported 0.136 = 0.005 + 0.132) pins both constants in two
moves. Source: `outputs/working_codes/libero_object_task_pick_up_the_chocolate_pudding_and_place_it_in_the_basket_fix.py`
— `eef_point` / `pad_point`, lines 101–110; 2026-09-16.

**A *command*-side sign error here is silent, because a descent's floor backstop hides it.** The forms
above measure where the tool *is*. The inverse map — where to *command* the pads — is `pos = pads −
R @ offset`, and the minus is easy to drop when only the measurement direction was derived:

```python
HAND_TO_CMD  = 0.107      # solve_ik(pos, q) targets hand = pos + R @ (0,0,-0.107)
HAND_TO_PADS = 0.132      # pads hang this far below the reported hand frame
PAD_FROM_CMD = HAND_TO_PADS - HAND_TO_CMD          # 0.025

def move_pads(pads_target, quat=TOPDOWN):
    p = np.asarray(pads_target, dtype=np.float64)
    goto_pose(p - _R_of(quat) @ np.array([0.0, 0.0, PAD_FROM_CMD]), quat)   # MINUS
```

On `libero_goal_task/put_the_bowl_on_the_plate` the sign was inverted, so every descent was commanded
**2 × 0.025 = 50 mm too deep** — and the program still scored **15/15**. The tell is not a failure but a
*constant*: the grasp close landed at pad_z **0.0906 / 0.0907 on all 15 seeds**, dead identical, which is
the arm's kinematic floor at that xy (probe-measured 0.0874) rather than the intended neck pinch at
0.1076–0.1155. An unusable pinch can still close with an acceptable gap, so nothing reports an error.
**When a measurement is identical across every seed, suspect a floor, not a success.** Correcting the
sign moved the close to the intended pinch (0.1113–0.1155) with no reward change — a latent defect, not
a fix.

**Watch for the circular probe when settling a sign.** An earlier probe "confirmed" the wrong sign
because it recomputed the pad position with the *same* model under test; its numeric agreement was
circular. Settle a sign by probing the inverse map directly — command three known heights and read the
measured pads back (corrected form: commanded 0.2000 / 0.1200 / 0.1000 → measured 0.2000 / 0.1244 /
0.1066, error ≤ 6.6 mm; the old sign put them 5 cm low). Source:
`outputs/libero_fix_loop/libero_goal_task/put_the_bowl_on_the_plate/fix_code.py` — `move_pads`,
lines 76–86; probe5 under
`/mnt/nimloth/aspire_scratch/libero_goal_task/put_the_bowl_on_the_plate/`; 2026-09-17.

**Independently re-derived on `libero_goal_task/put_the_cream_cheese_in_the_bowl`, with a sharper
downstream signature.** There the sign was wrong in the *measurement* direction — `tcp_now()` added the
rotated offset instead of subtracting — so the reported TCP read **21 cm high**, the ladder was driven
through the table, and the visible damage was not a bad descent but **every grasp candidate dying at
once**: `plan_grasp` reported `gap=0.0146`, i.e. a close on air, because the ladder had pushed the pads
below the object. So the signature of this sign error is *not* a 21 cm position error you will notice —
it is a *total* loss of grasp candidates on a scene where the object is plainly graspable. Check the sign
before you debug the grasp planner. The constant and both inverse forms are the ones above;
`TCP_OFFSET = (0, 0, −0.107)` on this robot. Source:
`outputs/libero_fix_loop/libero_goal_task/put_the_cream_cheese_in_the_bowl/findings.md`; 2026-09-17.

**Corollary — `solve_ik` succeeding is NOT evidence of reachability, and a wall probe must be
laddered.** Two traps sit either side of this measurement:

```python
def reachable(pos, quat):
    """Cheap pre-screen.  NOTE: solve_ik does NOT raise for out-of-workspace poses, so this
    returns True far past the joint limit / kinematic floor and must NEVER be the reachability
    decision - use the laddered probe below instead."""
    try:
        solve_ik(np.asarray(pos, dtype=float), quat)
        return True
    except Exception:
        return False

def probe_reach_x(pcy, z, quat=TOP_DOWN):
    """Ladder OUT to the wall in small hops. A single long lunge lands on a different IK branch."""
    x = X_START
    while x < X_MAX:
        goto_pose(np.array([x + HOP, pcy, z]), quat)
        if tcp_xy()[0] < x + HOP - TOL:      # stopped short: this is the real wall
            break
        x = tcp_xy()[0]
    return x
```

First trap: a `try/except` guard around `solve_ik` returns True while the arm in fact stops 3.4 cm
short, so it never fires — the failure is a *constant* Cartesian error in one axis across a whole
descent, with no exception raised. Reachability has to come from a `goto_pose` read-back, which is
exactly the `achieved_tcp()` measurement above. Second trap: probing the wall with **one long lunge**
under-reports it. On
`libero_spatial_swap/pick_up_the_black_bowl_between_the_plate_and_the_ramekin_and_place_it_on_the_plate`
commanding straight to x = 0.95 from home read back `x_max = 0.696–0.697`, while laddering out in
small hops at the same height and y reached **0.750** — a ~5 cm error, on a different IK branch,
because the solver converges differently for a 0.35 m jump than for the incremental approach the real
descent uses. A laddered probe is therefore mandatory before *disqualifying* a column. On the fixed
runs the closed-loop correction never fired (achieved-vs-commanded 0.0003–0.0020 m), independently
confirming the chosen column was genuinely inside. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_between_the_plate_and_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— `reachable`, `probe_reach_x`, and the correction inside `attempt()`; 2026-09-15.

**…and the cheap screen IS legitimate for *ordering* — just never for disqualifying.** The warning
above ("must NEVER be the reachability decision") is about *deciding*, and it holds. But when a wall is
one of several candidates and you are about to spend a full pinch ladder on it, a cheap read-back
screen at a *safe height* — before any descent — is the right tool for choosing where to look first,
because the cost difference is large and one-sided:

```python
def quick_reach(tx, ty, z, quat):
    """Screen at a height clear of everything. Returns (xy_err, achieved_tcp)."""
    c0 = tcp()
    go(np.array([c0[0], c0[1], max(c0[2], z + APPROACH_Z)]), quat)
    hop_to(tx, ty, z, quat, step=0.050, xy_tol=0.014, z_tol=0.040, max_iter=3)
    got = tcp()
    return math.hypot(got[0] - tx, got[1] - ty), got

for u in walls:                       # pre-sorted by alignment with the goal direction
    err, _ = quick_reach(tx, ty, zr + 0.10, quat)
    if err > 0.020:
        continue                      # deprioritise; the LADDER remains the decision
```

Measured on `libero_spatial_task/pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate`:
the screen rejects walls (0,−1) and (1,0) on **every** seed with `err` 0.13–0.24 m, in **3 iterations
each**; without it, the ladder's own `cmd_err > 0.022` gate catches the same walls only after ~14–17
re-issued commands each. `solve_ik` returned an answer for both rejected walls, and `move_to_joints`
reported success — the substitution of a fallback orientation for an unreachable pose is invisible from
the return values, which is why the distance has to be *read back*. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— `quick_reach` lines 129–146, call site `grasp_bowl` 570–579; 2026-09-16.

#### This measurement belongs in *planning*, not only in diagnosis — and the z axis lags too

The section above uses `achieved_tcp()` to *explain* a failure. Use it to *choose* the plan, because a
commanded pose is not an attained pose and the gap is systematic:

- **A hard x clamp.** Measured on a second task, the clamp reproduces at the same value: commanded
  `(+0.800,+0.100,+0.360)` reads back `(+0.750,+0.099,+0.370)`, and the arm never exceeds `x ≈ 0.750`
  at any height. Two independent tasks arriving at the same number is the reason this is a workspace
  property to plan against, not a per-seed quirk.
- **A z lag of ~1.2 cm.** The controller *tracks* the z command rather than attaining it: a descent
  commanded to `z 0.045` measures `0.058`. This is the axis the sections above do not cover, and it is
  the one that silently changes how hard a release is.

The consequence is that an **open-loop release on a commanded depth** produces a different true release
height on every seed — the object is set down from a varying height, and whether it bounces or is
pressed sideways is left to chance. Close the last descent on the *measured* z:

```python
zc = float(tcp()[2])
for _ in range(16):
    if zc <= z_g + 1e-6:
        break
    zc = max(z_g, zc - HOP)
    goto_pose(np.array([tx, ty, zc]), q)
```

**Evidence**: with the commanded-depth release the landing z-extent varied centimetres between seeds;
with the measured-depth loop the object lands flat at z-extent `0.044–0.045` on all 15 development
seeds, and the sweep went 12/15 → 15/15. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate/fix_code.py`
— `tcp` lines 106–115, `descend_to` 128–158; 2026-09-15.

#### Detect a reach clamp from a *constant* residual — then stop, do not fight it

The clamp above is a fact about the arm. The transferable skill is the **detection**, which needs no
knowledge of the clamp value:

> After any horizontal `goto_pose`, compare the commanded xy with the achieved xy. If the magnitude of
> `(commanded − achieved)` is essentially **constant across two successive iterations**, the joint is
> clamped — every further nudge is wasted motion and wasted horizon.

```python
X_MAX = 0.745          # solve_ik clamps the HAND x to <= 0.75

# Before the final approach, predict the TCP x the placement needs and do not
# burn iterations nudging past the clamp:  tcp_x_needed = place_x + offset_x
if rel_xy[0] > X_MAX:
    print("  place target x=%.3f beyond reach (clamp %.3f); residual %.3f m"
          % (rel_xy[0], X_MAX, rel_xy[0] - X_MAX), flush=True)
```

A closed-loop centring loop is *designed* to drive its residual to zero, so when the residual instead
pins at a constant 2.5–4.0 cm the loop keeps issuing commands that cannot change the outcome — it
looks like convergence in progress and it is not. Contrast with the section above: there the residual
was a *grasp* offset that closed to 0.0003–0.0020 m once the column was right; here it never moves
because the target is genuinely outside the envelope.

**Evidence**: on
`libero_spatial_swap/pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_cabinet_and_place_it_on_the_plate`
seeds 51 and 61 stall at `x = 0.748–0.751` for **three consecutive nudges** (`cmd=[0.768,0.084] →
ach=[0.748,0.083]`, then `cmd=[0.776,…] → ach=[0.750,…]`) and verify at `dist = 0.040` / `0.039` — a
3.9–4.2 cm residual against the ~3 cm the sim accepts (`dist = 0.029` scored reward 1.0 on seed 52).
These two seeds are **not fixable by control on this arm**: the required TCP x exceeds the reachable
envelope for this object/target pair. The honest outcome is to detect and report, not to keep nudging.
Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_cabinet_and_place_it_on_the_plate/fix_code.py`
— `nudge` loop in `carry_and_place`, lines 288–301; 2026-09-15.

### Corollary — know *which* pose a hold re-commands: a hold is not idempotent either way

**Trigger**: any helper that buys sim time by re-issuing the current tool pose (`settle`, `hold`,
`wait`) — the standard trick, since perception advances no sim steps (see `transport.md` *"Physics
Settling After Release"*). If that helper reads the pose back and re-commands **what it measured**, it
is not a hold: it is a closed loop through a servo that lands short of its own target, so every call
ratchets the tool by a few millimetres.

```python
_CMD = {"p": None}                     # the last COMMANDED grip-site pose

def go(p, quat):                       # every Cartesian command goes through here
    p = np.asarray(p, dtype=np.float64).copy()
    _CMD["p"] = p
    goto_pose(p, quat)
    return p

def settle(quat, repeats=2):
    for _ in range(repeats):
        p = _CMD["p"]
        if p is None:                  # nothing commanded yet: hold what we measure, ONCE
            cur = tcp()                # tcp() is the grip site; raw robot_cartesian_pos is GZ higher
            p = np.array([float(cur[0]), float(cur[1]), float(cur[2]) - GZ])
        go(p, quat)
```

`goto_home_joint_position()` invalidates `_CMD`: after it, no previously commanded pose is a valid
hold target. Two things make this invisible in a normal trace — the ratchet is only a few mm per call,
and the trace prints the **achieved** height as if it were the commanded one.

**Why it matters + evidence**: the term it controls is the release height, which is exactly the term
that decides marginal seeds. Same descent, same payload, varying only how many post-release holds ran:
seed 53 released at `gripz=0.053` (cmd 0.049, **+4 mm**, 1.0), then `gripz=0.062` (cmd 0.051,
**+11 mm**, 0.0), then `gripz=0.053` (cmd 0.051, +2 mm, 1.0). Eleven millimetres above a 12 cm plate
is a drop, not a placement. With `_CMD`, `after release` equals `release` on every tested seed instead
of creeping. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate/v6.py`
— `_CMD`/`go`/`settle` lines 159–185; 2026-09-16.

**The commanded-pose hold is a mechanism fix, NOT a measured outcome win — do not sell it as one.** Two
full 15-seed dev sweeps of each variant (four draws) gave the commanded-pose hold **23/30** and the
shipped measured-pose hold **26/30**: it fixes the seed whose failure the ratchet explains (that seed
fails both draws under the measured-pose hold, passes one of two under this one), and loses another seed
outright plus one draw of a third. The reason is the mirror of the failure above — a hold that
re-asserts a **command** keeps driving the tool toward it, so when the command itself is slightly wrong
(and a release command is derived from a measured hang) the servo shortfall the measured-pose hold was
accidentally absorbing is gone. **Prefer the commanded pose when holds must be countable or the command
is known-good; do not adopt it expecting a score gain.** Always print the **commanded** and the achieved
height on the same line — that print is what made both halves of this measurable.

**Corroborated on a second task, where the drag was measured directly.** On
`libero_spatial_task/pick_up_the_black_bowl_on_the_ramekin_and_place_it_on_the_plate` the same re-command
appeared as a post-`open_gripper()` "settle" loop at a strained low release pose, and it was worse than
the millimetre ratchet above: re-solving IK there moved the tool **upward 2.4 cm** (`tcp_z` 0.0598 →
0.0839) while the payload was still between the fingers, dragging the bowl off the plate. Deleting the
loop and replacing it with `open_gripper()` followed by a single +0.045 m climb hop took **seed 51 from
0.0 to 1.0** with no other change. Same mechanism: at a pose the servo cannot hold, re-commanding is a
*displacement*, not a hold — and it is largest exactly at the low, strained release poses where a
placement is decided. Source: that task's `fix_code.py` release block and its `findings.md` root causes
10 / P3; 2026-09-16.

---

## The Reach and Height "Walls" Are `solve_ik` Clamps, Not Physics — Read the Source

**Trigger**: a top-down command whose achieved x saturates at a fixed value no matter how much further
past the object you command, or a descent that stops at a fixed z. Before designing a workaround — a
wrist tilt, a hop ladder, a longer ladder — read the API source. Every such wall measured so far is a
constant in the integration layer, shared by every task in every suite.

```python
# cap/integrations/franka/libero_reduced.py:383  (inside solve_ik)
pos = np.clip(pos, [-0.1, -0.5, 0.005], [0.75, 0.5, 0.9])   # x <= 0.75, z >= 0.005

# cap/integrations/franka/common.py:29
DEFAULT_TCP_OFFSET = np.array([0.0, 0.0, -0.107])
```

Three consequences, in order of how often they bite:

1. **The reach wall is `x <= 0.75`, and the kinematic floor is `z >= 0.005` — for every task.** So the
   0.107 hand-to-TCP offset measured empirically on one task is *not* a per-task measurement: it is
   `DEFAULT_TCP_OFFSET`, and constants derived from it are portable after all.
2. **A tilt does not defeat the wall — it moves the pads off the hand axis.** The clamp applies to the
   commanded *hand* position; a tilted orientation puts the pads somewhere else relative to that point,
   which is why a wrist tilt reaches an object the top-down pose cannot (see
   [grasp.md](grasp.md), "Reach Past a Kinematic Wall by Tipping the Wrist"). Framing it as defeating
   a physical limit invites the wrong follow-up — "ladder harder" — when the wall is a parameter.
3. **`solve_ik` retries a four-step orientation ladder and reports success on the first that
   converges** (`libero_reduced.py:389–400`): requested → top-down → `[0.707,0.707,0,0]` 45-tilt →
   side-approach, logging only a warning. A successful `solve_ik` therefore does **not** mean the
   orientation you asked for was honoured: a command near the clamp, or with an awkward orientation,
   can quietly settle into a 45° or side approach. If the orientation matters, verify it from the
   measured pose rather than from the return value.

**Evidence**: verified by reading the source, not inferred. On
`libero_object_task/pick_up_the_milk_and_place_it_in_the_basket` the target sits at x 0.708–0.717 —
inside the clamp — and a plain top-down command reaches it, `gap after close` 0.0388–0.0392 on all 15
development seeds with no tilt. The sibling `libero_object_task/pick_up_the_chocolate_pudding…` has its
object at x 0.763 > 0.75 and needed the tilt ladder; this is the same constant seen from both sides.
Source: `outputs/libero_fix_loop/libero_object_task/pick_up_the_milk_and_place_it_in_the_basket/fix_code.py`
— the frame/clamp constants at lines 30–48 and `cmd_of` at 109–115; 2026-09-16.

### The clamp is a software floor, not a wall — reach past it with `solve_ik` + `move_to_joints`

**Trigger**: a tool-tip depth you need that is **below `IK_MIN_Z = 0.005`**, where no tilt or yaw will
substitute for it. The section above establishes that the clamp is a `np.clip` on the *commanded*
target rather than physics; this is the legal composition that reaches past it. Both APIs involved are
allowed, and neither `goto_pose` nor `solve_ik` is asked to do anything it refuses:

```python
jA = np.asarray(solve_ik(np.array([cx, yt, zA]), q), float)          # a target at the clamp
jB = np.asarray(solve_ik(np.array([cx, yt, zA + 0.020]), q), float)  # ...and 20 mm above it
slope = (jB - jA) / 0.020                       # joints per metre of tip height
aim   = zA - 0.006                              # the linear extrapolation UNDER-shoots
for it in range(4):
    move_to_joints(jA + slope * (aim - zA))     # note: move_to_joints, NOT goto_pose
    got = tip_z()                               # ALWAYS read the achieved tip back
    if got <= deep + 0.0005:
        break
    # ...correct `aim` from the measured response (below)
if tip_z() < deep - 0.003:                      # overshot towards the support surface: back off
    move(move_to_joints, jA + slope * (aim + 0.002 - zA))
```

**Three things make this safe, and all three are measured rather than assumed:**

1. **Verify the achieved tip, never the command.** `move_to_joints` executes the joint vector it is
   given without consulting the clamp, so nothing downstream will catch a wrong one — not `solve_ik`,
   not `move_to_joints`, not `goto_pose`. Read the tip back after every step.
2. **The response along an IK-derived joint line is strongly NON-MONOTONIC.** Measured here, the
   tip-height gain for *identical* step sizes ranged from **~0.1× to >6×**, and a step that descends
   can be followed by one that ascends. Any fixed-gain controller on this line is unreliable; the only
   usable gain is the **local measured** one, clamped to `[0.25, 4.0]` with a fallback to 1.0 outside
   that band.
3. **Bound the excursion, and size it from the object, not from the reach.** `aim - step < -0.0095`
   aborts. The extrapolated `tip_z` is the **tool tip** (midway between the fingers), *not* the pad
   contact, so a negative tip is not automatically a table collision — but the excursion must be
   justified by the object's own measured geometry (here: pads 9 mm below the object's top, magnitude
   bounded to `[-0.0035, 0.012]`). This is safe because it is 6–10 mm and verified, **not** because the
   clamp was wrong; treating it as a general-purpose bypass is how a tip ends up inside the table.

**Negative results — measured on this task, and worth not repeating.** Flipping the sign of the slope
when a step stalls drives the pads *up*: the response is weak at small steps (backlash), so the flip
fires spuriously, and seeds 58/65 reached tip 0.0142–0.0165 and closed on nothing (gap 0.0012).
Growing the step on a stall amplifies the same non-linearity (tip ran away to 0.037–0.086). A
gain-scaled adaptive line search, tried in two forms, either stalls short or overshoots, and scored
**0** on seed 51 — a seed the shipped code passes. Re-seating shallower after a slipped grip does not
help (retry closed at 0.0151, no better than the first attempt).

**Evidence**: achieved tips of −0.0015 … −0.0021 from a clamped target of 0.005, turning a **0/15**
initial program into **11/15** on development seeds. Source:
`outputs/libero_fix_loop/libero_goal_task/put_the_bowl_on_the_stove/fix_code.py` — the extrapolation
block inside the `if wide:` branch; 2026-09-17.

---

### A low seat that comes up short is an IK-*branch* problem — re-condition it, do not re-aim

**Trigger**: a `seat()` / `goto_pose` at a low, off-vertical target returns a pose parked tens of
centimetres away, so the pads never get near the object. The clamp section above covers a *reach* wall;
this is the softer failure next to it — the pose is reachable, but the warm-started solver settled into
a fallback branch.

**Detect the shortfall on the returned pad point, not on the command**, and re-seat from high to low
before giving up. A descending ladder is what re-conditions the branch:

```python
c_ok = seat(tgt, Q_LAT, tag="lat-pinch")
short = float(np.linalg.norm(c_ok - tgt))
if short > 0.018:                       # an ordinary successful seat measures ~0.0095
    for h in (0.22, 0.14, 0.06):        # the ladder re-conditions the IK branch
        goto_pose(tgt + np.array([0.0, 0.0, h]) + 0.02 * axis, Q_LAT)
    c_ok = seat(tgt, Q_LAT, tag="lat-retry")
    if float(np.linalg.norm(c_ok - tgt)) > 0.032:
        return False                    # genuinely unreachable at this xy
```

Do **not** pay for `goto_home_joint_position()` here: the ladder alone is what re-conditions the branch,
and a home reset costs ~150–250 steps of a 4000-step horizon. **Calibrate the trigger above the error an
ordinary successful seat produces**, or the recovery fires on healthy seats — here the threshold was
raised 0.008 → 0.018 because a good seat on seed 62 measures 0.0095.

**Evidence**: seed 54, `seat lat-far → (0.658, 0.113, 0.176)` against a target of
`(0.679, 0.115, 0.042)` — 0.169 m short — and after the descending ladder
`seat lat-retry → (0.604, 0.115, 0.024)`, 0.026 m off the pad line. Source:
`outputs/libero_fix_loop/libero_goal_task/open_the_top_drawer_and_put_the_bowl_inside/fix_code.py` —
`lateral_grasp`; 2026-09-17.

### Never command a low z as the first pose after a reorientation

**Trigger**: re-orienting the wrist between two `goto_pose` calls — here from the drawer-pull pose
(tool z = −y) to top-down — and following it immediately with a low target or a `hop_to` that descends.

The transition derails: the arm is thrown up and back. **Seat the first post-reorientation pose at the
full stand-off height and descend from there.** On this task the first pose after the SIDE → TOP_DOWN
pull was seated at `pinch_z + 0.20` (tag `"above"`) with the descent below it; a single low `go` right
after the same transition parked the pad point at tcp z **0.2117** instead of the ~0.016 intended, and
the grasp then closed on nothing. Source: same `fix_code.py` — `grasp_box()`; probe15, 2026-09-17.

### Refinement — the clamped floor is *quantised*, and which level you land on can decide the task

The floor is not a smooth limit you approach continuously; at a given (azimuth, radius) a
floor-saturated descent settles on **one of a few discrete depths**, and the level is stable within a
seed. Measured on `libero_goal_task/put_the_bowl_on_top_of_the_cabinet`, commanding well past the floor:

| landed `hand_z` | fingertip | seeds | outcome |
|---|---|---|---|
| **0.1155** | ~+0.0021 | 6/15 | **6/6 straddled the rim** (aperture 0.0084–0.0094) |
| **0.1183–0.1188** | ~+0.0049…+0.0054 | 9/15 | **0/9 straddled** — pads just above the material, close read air (0.0010) |

A **3 mm** difference in the settled depth is the whole difference between "in the object" and "3 mm
above it". The practical rule: the achieved depth is per-(azimuth, radius) and is *not* a continuous
function of the command, so when a floor-saturated descent lands above the target band, **change azimuth
or radius rather than commanding deeper** — pressing harder cannot move you to the lower level. Print the
achieved `hand_z` and compare it against the band, don't assume the command was honoured.

```python
z = eef()[2]
if z > band_hi:            # this pose's floor is the shallow level
    # do NOT command deeper - walk the azimuth/radius
    continue
```

**Executed source**: `libero_goal_task/put_the_bowl_on_top_of_the_cabinet` `fix_code.py`, `creep_to`
(line 303) and the `hand_z`/`fingertip~` readout (lines 373–379), with the azimuth/floor table from
`fix_seed_51_probe.log`. Complements `grasp.position-dependent-kinematic-floor-lateral-drift`. **Diagnostic
evidence only** — that task is 0/15 on both programs for the geometric reason in `grasp.md` ("recognise a
gripless shell"), so this records the quantisation itself, not a reward improvement.

## Ladder Every Cartesian Motion Into ≤30 mm Hops

**Trigger**: one large Cartesian hop. `solve_ik` clips the target, applies the `(0,0,-0.1)` TCP
offset, and runs a warm-started `solve_ik_with_convergence(max_iters=5)` — a large jump falls outside
that solver's basin of convergence. **`move_to_joints` still returns `completed: true`**, so nothing
in the program notices.

```python
def hop_to(px, py, step=0.030, tol=0.016, max_iter=16, tag=""):
    """Walk to (px, py) at the current z in <=step-sized hops, re-solving each time."""
    for _ in range(max_iter):
        t = achieved_tcp()
        d = np.array([px, py]) - t[:2]
        if float(np.linalg.norm(d)) < tol:
            break
        nxt = t[:2] + d * min(1.0, step / max(float(np.linalg.norm(d)), 1e-6))
        move_tcp([nxt[0], nxt[1], t[2]], TOPDOWN, tol=tol, retries=0)
    return achieved_tcp()
```

Each hop lands inside the solver's basin, and the *measured* TCP is re-read before the next hop, so
error cannot accumulate silently.

**Why it works + evidence**: on `libero_goal_swap/put_the_wine_bottle_on_the_rack`, commanding
`x = 0.78` in a single hop landed at **0.686** and `y = −0.32` landed at **−0.182** — both reported
as successful moves. With `hop_to` the TCP tracks the target to a few millimetres and 15/15
development seeds place correctly. This is the same class of defect as "Measure the TCP, Not the
Hand" above: the API's success report is about the *hand*, and about the *command*, not about where
the tool actually got to. Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_wine_bottle_on_the_rack/fix_code.py` — `hop_to`,
lines 91–115; 2026-09-14.

#### …but bracket the hop size — and detect stalls by progress *toward the target*, not by motion alone

The ≤30 mm rule above is a safety bound that works because every hop **re-measures**. It is not a
licence to shrink the hop indefinitely: below the arm's realised-command floor, a hop costs a full
`goto_pose` and moves almost nothing.

| commanded | actually moved (measured TCP) |
|---|---|
| 0.020 m | **0.0079 m** |
| 0.045 m | 0.033 m |
| 0.10 m | 0.10 m |

So use **0.05–0.12 m** commands for a long move and let the re-measurement keep it honest.

The stall test needs the same care. A ladder that stops when the TCP "did not move" never stops at a
kinematic limit: **the arm oscillates ±3 mm there, so every hop still registers ~0.0065 m of motion.**
Test progress *toward the target* instead — two consecutive hops that fail to reduce the remaining
distance:

```python
def hop_to(px, py, pz, q, step=0.100, eps=0.008, budget=14, stall=2):
    tgt = np.array([px, py, pz], dtype=np.float64)
    c = tcp()
    dn = float(np.linalg.norm(tgt - c)); bad = 0
    for _ in range(budget):
        if dn <= eps: break
        goto_pose(c + (tgt - c) * (min(step, dn) / dn), q)   # <= step per command
        c = tcp()
        n2 = float(np.linalg.norm(tgt - c))
        if dn - n2 < 0.002:            # PROGRESS toward the target, not raw motion
            bad += 1
            if bad >= stall: break
        else:
            bad = 0
        dn = n2
    return c
```

**Evidence**: on `libero_spatial_task/pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_cabinet_and_place_it_on_the_plate`
hops fell **109 → 32–39** per trial, the two `Truncated: True` seeds (51, 52) became normal
terminations, and the sweep went 0/15 → 15/15; the episode budget is finite at ~4000 control
steps ≈ 108 hops of ~37 steps each. The pre-fix single 0.5 m lunge from home stalled ~25 cm short
(arm wedged near the cabinet) and closed the fingers on air on 10/15 dev seeds. Source: same
`fix_code.py` — `hop_to` lines 224–262, `tcp` 69–75; 2026-09-16.

**…but the motion test is not dead — it catches a *different* stall, and the two thresholds are
distinguishable.** The paragraph above rejects "did not move" because at a **kinematic limit** the arm
*dithers*. A pose that is **unreachable** is a different failure: the arm stops outright, and the
motion reading collapses to ~0 rather than settling at ~0.0065 m. So both tests belong in the loop, and
the measured gap between the two regimes is what makes the pair safe:

| stall | measured motion per hop | correct test |
|---|---|---|
| kinematic limit (oscillating at the clamp) | ~0.0065 m — never drops below | progress toward the target |
| unreachable pose (arm stopped dead) | below the 0.004 m floor | raw motion |

```python
now = tcp()
if prev is not None and float(np.linalg.norm(now - prev)) < 0.004:
    break                          # the arm has stopped moving: this pose is not attainable
prev = now
```

On `libero_spatial_task/pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate` the
pre-fix screen loop ran **14 and 17 iterations** on the two unreachable walls before giving up; with
the motion break the same screens cost **3 iterations each**. Note the break is a *cheap exit*, not a
diagnosis: it says "stop asking", not "this wall is impossible" — which is why it belongs alongside the
progress test and the read-back screen above, not instead of them. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— `hop_to` lines 103–128; 2026-09-16.

**…and the 0.004 m floor above sits *inside* the arm's ordinary tracking residual, which makes it a
false-positive generator unless you calibrate it.** The table above partitions motion readings into
"kinematic limit ≈ 0.0065 m" and "stopped dead < 0.004 m". Measured on
`libero_goal_task/put_the_cream_cheese_in_the_bowl`, the residual on an *ordinary, successful* hop is
**3–5 mm** — so the two regimes are not separated by a comfortable gap, and a convergence tolerance set
at 0.004 m leaves the ladder unable to converge on a reachable target. The observed consequence is
that the loop exits through its **progress guard on every seed**, not through convergence: the
`arm stopped moving` break fired on **60 of 105 ladder invocations**, on all 15 development seeds,
including every one that reached its target. So:

- **Set the convergence tolerance above the tracking residual** (`0.004` was too tight here; the
  successful ladders satisfied their targets to ~5 mm). Otherwise the stall branch *becomes* the normal
  exit and its message is printed on success, which is exactly how a diagnostic turns into noise.
- **Do not read the stall message as a failure signal.** A printed `arm stopped moving` on a run that
  then scores is the guard working, not a symptom. Three of the four ladder types that tripped it here
  were on successful moves; only one — the pinch-height ladder — was a real kinematic-floor stall.
- The distinction to keep: a **kinematic limit** means "stop asking, we are at the floor"; the message
  alone does not tell you which you are looking at. Corroborate with the target reached.

Source: `outputs/libero_fix_loop/libero_goal_task/put_the_cream_cheese_in_the_bowl/findings.md`
(`goto_laddered`, shipped tolerance `0.004`); 2026-09-17.

**A *windowed net-travel* backstop beats a single-hop test, and the target stop belongs in front of
both.** On a pure vertical descent toward a commanded height, a single-hop "did it go down" test fires
on any one hesitant hop and abandons a reachable target; no test at all drives the pads into the
support. Put the arrival stop first, and make the backstop measure **net travel over a window**:

```python
STALL_WIN, STALL_NET = 3, 0.004        # hops, metres of net travel

def descend(xy, z_from, z_to, step, tag="", touchdown=None, max_hops=26):
    move_pads([xy[0], xy[1], z_from], tag=tag)
    hist = [float(pad_pos()[2])]; z = z_from
    for _ in range(max_hops):
        if float(pad_pos()[2]) <= z_to + 0.002:      # primary: arrived at the command
            break
        z = max(z_to, z - step)
        move_pads([xy[0], xy[1], z], tag=tag)
        now = float(pad_pos()[2])
        if touchdown is not None and gap() > touchdown + TOUCH_DELTA:
            break                                    # payload landed early
        hist.append(now)
        if len(hist) > STALL_WIN:
            hist.pop(0)
            if hist[0] - hist[-1] < STALL_NET:       # backstop: no NET progress in 3 hops
                break
    return float(pad_pos()[2])
```

Three deliberate choices: the arrival stop is `z_to + 0.002` so a descent that reaches its command ends
*on the command* rather than on the backstop; the backstop compares the oldest and newest readings in a
3-hop window (`hist[0] - hist[-1]`) so a single hesitant hop is absorbed instead of ending the loop; and
every reading is `pad_pos()` — a **measured world quantity**, never the command read back.

**Why it works + evidence**: on `libero_goal_task/put_the_bowl_on_the_plate` the two-tier form fires
once per descent and stops within 14 mm of the command on every descent (grasping at pad_z
0.1113–0.1155, releasing at 0.1189–0.1270) with no overshoot into the table. Under the previous
single-hop test the same task logged up to **36 mm** of finger travel sliding down past a payload that
had already landed — a 29 mm bimodality between seeds. Note the relationship to the rule above: *that*
one is about the **horizontal** ladder at a reach clamp, where progress must be measured toward the
target because the arm dithers; this one is a **vertical** descent whose target may be below the
kinematic floor, where the window is what distinguishes "hesitating" from "blocked". Source:
`outputs/libero_fix_loop/libero_goal_task/put_the_bowl_on_the_plate/fix_code.py` — `descend`,
lines 187–214; 2026-09-17.

### The **approach** is usually the largest move in the pick — ladder it too

Every template in this library ladders the *descent* and the *transport*, and then issues the lateral
move from home (or from the previous candidate) to the grasp pose as **one** `goto_pose`. That is the
single biggest command in a pick, so it is the one most likely to land outside the solver's basin.
Measured on `libero_spatial_swap/pick_up_the_black_bowl_on_the_wooden_cabinet_and_place_it_on_the_plate`
with a TCP-tracking probe from home:

| commanded | achieved | error |
|---|---|---|
| `(0.703, −0.289, 0.42)` | `(0.453, −0.208, 0.227)` | **0.250 m** in x |
| `(0.653, −0.239, 0.42)` | `(0.756, −0.279, 0.473)` | 0.103 m, and 0.053 m high |
| `(0.603, −0.289, 0.42)` | `(0.603, −0.288, 0.430)` | tracked correctly |

Note the second row: the landing point is not merely *inaccurate*, it is **unrelated to the magnitude
of the command** — only the `−x` direction happened to be inside the warm-started basin. And
`move_to_joints` reports success every time, so the code believes it is at the bowl wall. The
consequence is not a near miss but a *different* failure: the pinches read `gap 0.0012–0.0019` (air
grasps) and the misplaced descent **shoves the object** (seed 59 baseline: all four `frac 0.62` walls
air-grasped; bowl moved `(0.717,−0.341) → (0.692,−0.331)`).

```python
hop_to(cur[0], cur[1], z_start, quat)     # rise clear at the current xy
hi = hop_to(tx, ty, z_start, quat)        # ladder the lateral move at altitude
err = float(np.hypot(hi[0] - tx, hi[1] - ty))
if err > 0.020:                           # one more pass, starting from where it ACTUALLY is
    hi = hop_to(tx, ty, z_start, quat)
```

**Evidence**: with the laddered approach on 2.5 cm hops the shipped file scores **15/15** with **zero
air grasps**, hold gap `0.0080–0.0082` uniform across all 15 seeds, and the first wall candidate
`radial_-y_62` succeeds on every seed (baseline used 2–5 candidates). Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_on_the_wooden_cabinet_and_place_it_on_the_plate/fix_code.py`
— `hop_to` lines 92–114 (its docstring records the probe table), the `hop_to` triple in `grasp()`;
2026-09-15.

---

## Size a Clearance Footprint by the Object's Radius, Not Its Bounding Box

**Trigger**: choosing a release column on a cluttered surface (raised edges, leaning boards, a
griddle lip) by scanning for free space. An axis-aligned square footprint sweeps up geometry the
object can never touch, so cells that are actually free read as obstructed.

```python
m = np.hypot(cloud[:, 0] - gx, cloud[:, 1] - gy) < r_object      # circle, not |dx|,|dy|
above = cloud[m][cloud[m][:, 2] > surface_z + 0.02]
clear = 1.0 if len(above) == 0 else float(above[:, 2].min() - surface_z)
score = (clear >= h_object + 0.04, -np.hypot(gx - burner[0], gy - burner[1]))
# sort by score descending: the clearest cell CLOSEST to the goal centre wins
```

Two rules that go with it: (1) the footprint radius is the **object's** radius, measured from the
object's own cloud — not half its bounding box, which over-covers for a round object; (2) keep the
distance-to-target term as the tie-breaker, because on a tight goal test "clear but off the goal"
is still a failure.

**Why it works + evidence**: on `libero_goal_swap/put_the_bowl_on_the_stove` a square footprint of
the bowl's width swept the plate's raised right edge (a 4–5 cm sliver at x ≈ 0.66–0.72), so every
cell right of the burner read as obstructed and the chosen place drifted ~5 cm right — outside the
±4 cm goal tolerance (seed 51, reward 0). The circular footprint selects the burner cell itself in
all 15 development seeds, at clearance 0.096–0.101 m. Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_bowl_on_the_stove/fix_code.py` — `choose_places`,
lines 168–200; 2026-09-14.

---

## Verify a Placement Against Position AND Rest Height

**Trigger**: any drop/place skill's self-check. XY proximity alone is satisfiable while the object is
still *held* — a bowl hanging in the gripper above the target reads as placed.

```python
pts = localize(rgb, d, K, E, OBJECT_PROMPTS, ref_xy=place_xy, radius=r_object + 0.04)
c    = np.median(pts, axis=0)
zlo  = float(np.percentile(pts[:, 2], 2))          # 2nd percentile, not min
ok = (math.hypot(c[0] - place_xy[0], c[1] - place_xy[1]) < 0.07 and
      (surface_z - 0.03) < zlo < (surface_z + 0.07))
```

Use the 2nd percentile rather than `min` so a single stray point (a reflection, a detached pixel)
cannot make a correct placement fail. The band is one-sided on purpose: too low means the object
fell through or missed the surface, too high means it is still in the gripper.

**Why it works + evidence**: on `libero_goal_swap/put_the_bowl_on_the_stove` the v1 check
(XY plus `z_min > surface_z - 0.03`) printed "PLACED ON STOVE" with environment reward **0** on
5 seeds whose bowl was still held high in the gripper (seeds 51, 52, 54, 55, 57). The two-sided
check reports success only on the 15 runs the environment also scored 1.0. Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_bowl_on_the_stove/fix_code.py` —
`placed_on_stove`, lines 216–230; 2026-09-14.

**Negative result — do not "correct" a small cloud-centroid residual.** If the placed object's
visible-cloud centroid sits a centimetre or two from the *target's* cloud centroid, resist the urge
to re-aim. On `libero_goal_swap/put_the_bowl_on_the_plate` the placed bowl's cloud centroid sat a
consistent **1.3–2.2 cm toward −x** of the plate's cloud centroid on all 15 development seeds, with
the direction **independent of the approach side** — so it was not grasp drag. Every alternative
estimator tested (trimmed median, mean, upper-60 % of the cloud, 2nd/98th percentiles) moved the
estimate by only a few millimetres, and the final keyframe showed the bowl **visually centred inside
the plate's rim** with reward 1.0 on all 15. The residual is an artefact of two *different* masks —
a bowl rim and a thin plate disc seen from an oblique camera — not a physical offset. Re-aiming by
1.5 cm would have been a coin flip on the held-out set. Emit the number as a readout; never gate
control on it. Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_bowl_on_the_plate/fix_code.py` — `placed_on_plate`;
2026-09-14.

---

## Never Return Home While a Fixture You Opened Still Matters

**Trigger**: a program that opens (or positions) a drawer, door, or other movable fixture and then
needs that fixture to *stay* open for a later step — grasp the object inside it, place into it, look
into it. The retreat from the fixture is what breaks it.

```python
# WRONG: home drags the open drawer shut
goto_home_joint_position()

# RIGHT: retreat straight back along the approach axis, keeping the wrist configuration
move_tcp([x, y + 0.16, z + 0.26], SIDE_QUAT, iters=3, axis=SIDE_AXIS)
```

**Why it works + evidence**: on `libero_goal_swap/open_the_top_drawer_and_put_the_bowl_inside` the
panel front measured `y = −0.0093` immediately after the pull but `y = −0.0885` after
`goto_home_joint_position()` — 8 cm of the 15 cm opening lost, enough that the later placement
corridor is gone. Retreating straight up preserves the full 0.130–0.146 m opening on every
development seed. This is the same rule as "NEVER call `goto_home_joint_position()` while holding a
grasped object" in [transport.md](transport.md), extended from *held objects* to *positioned
fixtures*. Source:
`outputs/libero_fix_loop/libero_goal_swap/open_the_top_drawer_and_put_the_bowl_inside/fix_code.py` —
`open_top_drawer`; 2026-09-14.

---

## The Score Is the Episode's FINAL State — Never Act After a Placement

**Trigger**: any loop that iterates after a *successful* release — a re-localise-and-retry loop, a
candidate sweep, a verification pass that then continues.

`env.step(code)` runs the whole program block, and the reward is the goal predicate evaluated on the
**last inner step**. Nothing remembers that the object was on the plate three steps ago. So every
action after a completed placement is pure downside: the best case is that it changes nothing, and the
common case is that the loop re-grasps the object it just placed and carries it off the goal.

```
seed 64: release xy=(0.706,0.154) plate=(0.714,0.209)
         attempt 1 targets bowl c=(0.711,0.203)   <- the bowl it had JUST placed
         re-grasps it (close width 0.0967 -> lift widths [0.0856,0.0773,0.0715,0.0667])
         carries it off the plate; the 999-frame video ends with an EMPTY plate, reward 0.000
```

Guard the loop head, not the exit — check *before* the next grasp whether the work is already done:

```python
if carries > 0:
    tc = np.asarray(tgt["c"], dtype=float)
    if on_plate(tc, goal_xy, plate_r, plate_surf):     # wide band here: dxy <= 0.045
        print("   target already rests on the plate -- settling and stopping", flush=True)
        settle_at_rest(topdown(0.0), n=4)
        break
```

Use the **wide** tolerance for a loop-top reading taken from an OBB centre and the **strict** one
(`dxy <= 0.030`) for a raw post-release cloud — the raw cloud is the one that can read optimistically
(see the settling section in [transport.md](transport.md)). With the guard, seed 64's carried state is
preserved and the seed scores 1.0 (development measurement; the shipped 9/15 sweep loses 64 to a
different signature). Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_next_to_the_cookie_box_and_place_it_on_the_plate/fix_code.py`
— the loop-top guard at 652–666, `on_plate` 557–574, `settle_at_rest` 575–583; 2026-09-16.

## Budget API Calls Against the Episode Horizon

**Trigger**: any multi-phase program that opens, inspects, re-grasps, and then runs a retry loop —
i.e. almost every non-trivial task. The episode ends silently mid-phase.

```python
HORIZON = 4000          # env low_level.max_steps; ~150-170 API calls total
# every goto_pose / close_gripper costs ~23-27 sim steps: budget per attempt, not per program
# treat ValueError("executing action in terminated episode") as "the episode is over"
```

Exceeding the horizon raises `ValueError: executing action in terminated episode` from inside
whatever call happens to cross the line — commonly `close_gripper` — so the program dies *mid-phase*
with no chance to clean up. Note the replay video is 4× subsampled: `999` video frames = 4000 sim
steps, so keyframe indices are not sim-step indices.

**Why it works + evidence**: on `libero_goal_swap/open_the_top_drawer_and_put_the_bowl_inside` the
trace call count was 149 for a truncated run (seed 65) against 160 for a successful one (seed 61).
The direct fix is to detect a failed grasp from the measured gripper gap (see
"Verify a Grasp by the Measured Gripper Gap" in [grasp.md](grasp.md)) rather than from a planned
trajectory, so a failed attempt costs one check instead of a re-planned sequence. Source: harness
constant at `cap/envs/simulators/libero.py:72` (`horizon=max_steps`) with
`env_configs/libero/franka_libero_traced.yaml` (`max_steps: 4000`); evidence from the task's
`trace.json`; 2026-09-14.

**Refinement — budget by *carries*, not by sweep iterations.** In a candidate-walking retry loop,
most early candidates fail *without touching the object* (an air grasp returning a near-zero
aperture), so a single `MAX_ATTEMPTS` counter lets an episode end having never once carried the
object. Track the two costs separately:

```python
MAX_CARRY_ATTEMPTS = 3      # full pick-and-place attempts an episode can afford
MAX_ITERS = 5               # total candidate sweeps (air misses are ~half the cost)
carries = 0
for n in range(MAX_ITERS):
    ...
    if res != "air":        # the pinch took hold -> this cost a real pick-and-place
        carries += 1
        if carries >= MAX_CARRY_ATTEMPTS:
            break
```

Measured costs to budget with: an air grasp **16** API calls, a carried attempt **~30**, a clean run
**53**, against a horizon of roughly 160 calls — so the worst case above is `3×30 + 2×16 + preamble
≈ 137`. On `libero_goal_swap/put_the_bowl_on_the_plate` this was inert on all 15 development seeds
(max 2 sweeps used) and re-verified 15/15; it is insurance, not a fix, and should be reported as
such. Source: `outputs/libero_fix_loop/libero_goal_swap/put_the_bowl_on_the_plate/fix_code.py` —
`run`; 2026-09-14.

**Measure the retry cost by *injecting* the failure — the horizon is not as tight as it looks.**
Before trimming legitimate observation calls "for headroom", bound what a retry actually costs:

| run | trace steps |
|---|---|
| clean carry | **142** |
| one forced first-pinch failure + successful retry | **175** (+33) |

On
`libero_spatial_swap/pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate` a first pinch
forced to fail (stopped above the bowl, z 0.119 > 0.070) cost 33 extra steps, and the program then
re-localized, pinched the next wall (hold gap 0.0081) and still scored 1.0 with `task_completed=1`.
So **one full retry fits comfortably** and the widely-quoted ~160-API-call horizon is a soft figure,
not a hard wall — only a run that fails several pinches in a row risks it. The lesson is procedural:
derive the retry budget from a measurement, not from an estimate that pressures you into cutting
observations you actually need. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate/fix_code.py`
— retry loop in `run`, lines 489–580 (loop from 522); 2026-09-15.

**Refinement — count the commands you issue, and gate *retries* with the count.** Every figure above
is a *forecast*; a program that shadows the API entry points can instead account for what it has
already spent. Measured per-primitive costs on
`libero_spatial_task/pick_up_the_black_bowl_between_the_plate_and_the_ramekin_and_place_it_on_the_plate`:
`goto_pose` ≈ **30** env steps, `open_gripper` / `close_gripper` exactly **30** each, one full attempt
≈ **1400** steps (a 354-frame pass at `_subsample_rate=4` = 1416) — so with `HORIZON = 4000` only 2–3
attempts fit, and the pre-fix 8-candidate retry died at 3916 steps mid-episode:

```python
HORIZON, HOP_COST, GRIP_COST, ATTEMPT_BUDGET = 4000, 30, 30, 1400
_MOTION = {"hops": 0, "grips": 0}
def spent():
    return HOP_COST * _MOTION["hops"] + GRIP_COST * _MOTION["grips"]
...
if HORIZON - spent() < ATTEMPT_BUDGET:      # gate the RETRY, never the first attempt
    break
```

Two disciplines: the gate must be **measured from the program's own commands**, not estimated per
candidate — and it must **never be able to cut a first attempt short**, or the retry guard becomes a
new failure mode. A probe that ran 4 pinches (~76 `goto_pose`) exhausted the episode, which is how
the cost table was derived. Source: same `fix_code.py` — `spent` lines 34–35, the shadowed gripper
calls 89–98, `go` 99–113 (hop count), the retry gate 523–528; 2026-09-16.

**Refinement — `mask_to_world_points` is where the budget actually goes, so cap masks per prompt.**
The two refinements above budget *motion*. On a scene with several same-class objects, perception
dominates instead: **one `mask_to_world_points` call per candidate mask**, and a finder that loops
over 5 prompts × 8 masks costs up to **40 calls for a single object** — a quarter of the whole
horizon, before any motion. Three caps pay for a retry:

```python
tries = 0
for prompt in PROMPTS:                    # ordered best-prompt-first
    if have_enough(cands): break
    masks = segment_sam3_text_prompt(rgb, prompt)
    if not masks: continue
    for m in sorted(masks, key=lambda x: -x["score"])[:5]:     # 1. cap masks per prompt
        if have_enough(cands) or tries >= 8: break             # 2. cap the total
        tries += 1
        ...
        return result                     # 3. first feasible hit wins -- do NOT keep
                                          #    scanning for a 'better' one
```

Rule 3 is the one that is easy to get wrong: continuing past the first feasible candidate to compare
scores buys nothing (the screen already encodes what "feasible" means) and can double the cost. Pair
these with two motion-side economies: **drop padding `get_observation()` settle calls** — the climb
back to carry height is itself the settling time — and keep transport interpolation to 3 waypoints
instead of 4.

**Evidence**: on
`libero_spatial_swap/pick_up_the_black_bowl_next_to_the_cookie_box_and_place_it_on_the_plate` the same
seed-51 episode cost **154 API calls** before (`mask_to_world_points` 89, `segment_sam3_text_prompt`
17) and **70–72** after (`mask_to_world_points` 18, `segment_sam3_text_prompt` 9) — with *identical*
success. That ~80-call saving is what makes a second carry attempt affordable inside the horizon;
without it the retry path is unreachable in practice. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_next_to_the_cookie_box_and_place_it_on_the_plate/fix_code.py`
— `find_containers` 176–210, `find_box` 213–255, transport interpolation 529–535; 2026-09-15.

**Refinement — in a *grasp-search* loop the sink is `close_gripper`, so cap closes separately.** The
budgets above meter motion and perception; a radii × directions × retries search spends neither. Each
iteration is a descent plus a close, and a close is what crosses the horizon line:

```python
MAX_CLOSES = 12                     # a close is the actual unit of cost in a grasp search
closes = 0
for direction in pinch_directions():
    if closes >= MAX_CLOSES: break
    for offset in PINCH_OFFSETS:
        if closes >= MAX_CLOSES: break      # check BOTH loops -- an inner-only cap
        closes += 1                         # cannot bound a 5 x 6 search
        ...
```

Two properties are worth copying. First, **the cap must be checked in every enclosing loop**, not just
the innermost one — the natural bug is a cap that bounds the radius sweep while the direction loop
keeps re-entering it. Second, pair the cap with a **guard that ends the search outright when the object
is no longer graspable**: a bowl on its side measures 0.066–0.076 m tall against 0.044 m upright, and at
that point every radius in every direction air-grasps (see [grasp.md](grasp.md), "Scan the Pinch
*Radius*"), so the remaining budget is provably worthless:

```python
if (b_hi - b_lo) > max(0.055, 1.35 * h_upright):
    break                           # toppled: no rim exists at any radius -- stop, do not scan
```

**Evidence**: with `max_steps: 4000` at ~30 steps per API call, an unguarded radius search died
mid-motion with `ValueError: executing action in terminated episode` (seed 53), and a scan that kept
retrying on a toppled bowl burned **25 closes on one bowl** (seed 60) — more than twice the cap, all of
them provably hopeless. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_on_the_cookie_box_and_place_it_on_the_plate/fix_code.py`
— constants and `run`; 2026-09-15.

---

## Release Into a Drawer at the Middle of the Landing Corridor

**Trigger**: placing into an open drawer, tray, or bin whose entry is narrower than the object's drop
path. The gripper *body* hits the fixture's top plane, so the object must necessarily be released
above the container floor — a free drop, not a set-down.

```python
cavity_y = drawer_face - 0.075        # middle of a measured ~5 cm landing corridor
place    = np.array([x_ref, cavity_y, floor_z + bottom_gap + 0.020])
```

**…and the corridor's *x* is the cavity's, not the handle's.** The rule above fixes the *depth* of the
landing; the same drawer can still fail on the lateral axis because **the handle and the cavity are not
aligned**. Measured on `libero_goal_task/open_the_top_drawer_and_put_the_bowl_inside`: cavity floor
z = 0.152 over x 0.59–0.72, y −0.155…−0.03; panel top strip z = 0.213; **cavity centre x ≈ 0.655 is
4.5 cm left of the handle x = 0.700**. A 7.7 cm box released at the handle's x sits half on the cavity
wall, rests at rim height, and the reward stays 0 with no error anywhere. Read the cavity from the depth
image (points inside the drawer's z-slot between floor and rim), then carry to **the centre of the
measured cavity** and descend until the arm stalls — the passing runs log
`descended: lowest free cmd z=0.17x`. The handle is a control, not a landmark. Source: same
`fix_code.py` — `open_drawer()` / `cavity()` / `carry_and_release()`; 2026-09-17.

**Why it works + evidence**: on `libero_goal_swap/open_the_top_drawer_and_put_the_bowl_inside`
landing offsets of −0.059 … −0.122 m behind the panel face all succeeded, while −0.131 … −0.140
(too deep) and −0.032 (too shallow) failed; aims of 0.100 and 0.115 behind the face were each tested
and each converted one passing tail into a failure. The landing is a **knife edge**: a 1–2 cm change
anywhere in the trajectory flipped 5 of 13 development seeds (3 gained, 2 lost). Practical
consequence — treat single-seed development results on this kind of placement as noise and report
the seed *count*, never the seed identity. Source: same `fix_code.py` — the run block; 2026-09-14.

---

## Pushing / Sliding

Add entries for pushing objects without grasping: contact approach, force direction, step size,
distance control.

### Descend in the Corridor, Then Do Everything Else by Horizontal Slide

**Trigger**: a non-prehensile push/slide where a vertical descent at the object's own `xy` stalls far
above the table (measured TCP z 0.09–0.23) and moves nothing. The object's own position is simply not
a point the arm can descend at.

```python
BASE  = np.array([0.26, -0.05])   # a free point the arm CAN reach at low z - find yours
Z_LOW = 0.005                     # the lowest z the arm can be commanded to

def descend_at(x, y):             # descend ONCE, at the free point
    for z in (0.30, 0.12, 0.03, Z_LOW, Z_LOW):
        cmd([x, y, z])
    # the repeat of Z_LOW is deliberate: the first low command half-travels

def low(x, y):                    # every horizontal move happens at Z_LOW
    cur = ee_tcp()
    d = np.array([x, y]) - cur[:2]
    n = max(1, int(np.ceil(float(np.linalg.norm(d)) / 0.05)))   # <=5 cm waypoints
    for i in range(1, n + 1):
        q = cur[:2] + d * (i / n)
        cmd([q[0], q[1], Z_LOW])
```

**Why it works + evidence**: on `libero_goal_swap/push_the_plate_to_the_front_of_the_stove` seed 51
the `+X` push moved the plate 0.118 m using exactly `descend_at(BASE)` followed by `low(...)`, while a
direct descent at the plate's own `xy` stalled at z 0.09–0.23 and moved nothing. Note the honest
footing: that task reached **0/15 development seeds** — this pattern produces real motion, it did not
solve the task. Source:
`outputs/libero_fix_loop/libero_goal_swap/push_the_plate_to_the_front_of_the_stove/fix_code.py` —
`low`, `descend_at`, lines 79–97; 2026-09-14.

### Verify a Push by Re-Segmenting the Object, Never by the TCP

**Trigger**: any non-prehensile push/slide. "The gripper moved" does not imply "the object moved" —
the finger can pass over or beside the object and the TCP trace will look identical.

```python
before, r_b = plate_now()
low(end_x, y)                      # the push itself
after,  r_a = plate_now()
print("dx=%.3f dy=%.3f" % (after[0] - before[0], after[1] - before[1]))
```

**Why it works + evidence**: on `libero_goal_swap/push_the_plate_to_the_front_of_the_stove` seed 51
this is how a **0.283 m TCP travel** was shown to be only **0.025 m of plate motion** — the fingertip
was sliding over the plate rather than driving it — and how a real 0.118 m push was confirmed
(plate re-detected at x 0.442 → 0.560). Without it the program would have reported success on a
non-event. Source: same `fix_code.py`, the `AFTER-1` / `AFTER-2` re-measurement blocks, lines 139–152;
2026-09-14.

### Roll the Hand to Make a Table-Level Paddle — a Wrist That Cannot Descend Still Has a Low Finger

**Trigger**: a non-prehensile push of an object the wrist cannot get down to. `robot_cartesian_pos` z
**stops dead at ~0.1175 at every xy** — a hard pose floor, not a table contact — so a top-down pinch
closes on air (aperture 0.0148–0.0172 at *every* commanded depth) and a closed top-down gripper slid
12 cm straight through the object's footprint and moved it **0.0001 m**. The object was 1.76 cm tall,
so no top-down pose reaches under its top edge.

```python
def _roll_quat(deg=25.0):
    t = np.deg2rad(deg)
    _Rx = np.array([[1, 0, 0],
                    [0, np.cos(t), -np.sin(t)],
                    [0, np.sin(t), np.cos(t)]])
    return rotation_matrix_to_quaternion(_Rx @ np.array([[1.0, 0, 0],
                                                          [0, -1.0, 0],
                                                          [0, 0, -1.0]]))

_Q_PADDLE = _roll_quat(25.0)
_PAD_DY = 0.0103      # low fingertip offset from the hand, world y
_PAD_DZ = -0.1166     # low fingertip offset from the hand, world z
_Y_BIAS = 0.047       # commanded-y offset the rolled pose needs to hit a target
```

**Why it works — and why it does not contradict the tilt below.** A roll about **world x** puts the
*low* fingertip at `z_hand - (0.11·cos t + 0.04·sin t)`, which is **minimised at
`t = atan(0.04/0.11) ≈ 20°`** (25° was used). The roll therefore **gains** vertical reach for the low
finger: at 25° it sits 6.6 mm below the top-down fingertip while the other fingertip stays 1.4 cm
clear, and because it is also offset `+0.0103` in world y it sweeps along the table as the hand
translates — a paddle, not a pinch. **The apparent conflict with "A Tilted Gripper Extends Reach — and
Costs Vertical Reach" (below, same task, sibling suite) is a difference of *which point you measure*:
that entry measured the TCP, `EE + 0.1·R[:,2]`, which lies *on the tool axis* and does lose height as
the pose tips. An off-axis finger can gain what the axis loses.** Roll for the fingertip, tilt for the
TCP, and always work out which of the two your contact actually needs.

**Evidence**: on `libero_goal_task/push_the_plate_to_the_front_of_the_stove` (runtime language "Push
the cream cheese to the front of the stove") a 5.0 cm rolled slide in −x moved the object **−0.0501 m**
with 0.0067 m of lateral drift, against 0.0001 m for the same commanded slide unrolled; seed 51 passes
in 9 moves. The rolled pose carries a constant **+0.047 m commanded-y bias** which one feedback
iteration removes — treat it as part of the pose and re-derive it if the roll angle changes. Source:
`outputs/libero_fix_loop/libero_goal_task/push_the_plate_to_the_front_of_the_stove/fix_code.py` —
`_roll_quat` and `_PAD_DY/_PAD_DZ/_Y_BIAS`, lines 39–52; probes 13–14; 2026-09-17. Ingested as
`knowledge/skill-code-instances/manipulation/manipulation.roll-the-hand-to-trade-a-wrist-floor-for-fingertip-reach-at-table-level.yaml`.

### Align the Push Axis First, Then Push Until the Reference Physically Blocks It

**Trigger**: pushing an object along −x toward a large reference it will eventually hit, while the
object sits near the reference's **edge**. Every push also drifts the object sideways — on seed 51 `y`
slid 0.1128 → 0.0740 over five iterations — until it **slips around the reference's corner** (reaching
x = 0.5175, i.e. behind the stove's front face) instead of stalling. The stall detector then never
fires and the loop pushes on, burning the horizon.

```python
# 1. align y onto the reference's centre line FIRST, then push along x
# 2. a push that moves the object < 8 mm means the reference blocked it -> done.
#    No need to look up the reference's front face at all.
```

Aligning y first turns the contact into a **self-detecting stall**: the object stops because something
solid is in the way, so the program never has to trust the reference mask's foreshortened far edge —
here the "stove" mask reported its front face at x = 0.488 while the true face is at 0.524, and the
object physically stops at 0.528. **The y alignment is the whole difficulty, because that is also
where the goal region is**: on this task the goal is the reference's **camera-facing side, centred on
the reference's own y centre line** — reward 0 at object y = 0.1121 / 0.1187 / 0.1263 and reward 1 at
y ≈ 0.196–0.202 (reference y centre 0.2014–0.2027) at *both* x = 0.5689 and x = 0.6208, a 5 cm-wide x
window. Source: same `fix_code.py` — `_try_push` and its caller; the
`iter 0..4 y 0.1128 → 0.0740, x 0.5630 → 0.5175` trace; 2026-09-17.

### After a stalled pull, *release* and probe under no load — that separates "the object stopped" from "the arm ran out"

**Trigger**: any pull or push that stalls short of its commanded distance. Both causes produce the same
observation — the tool did not advance — and they call for **opposite** responses: a drawer that stopped
against its own end-stop is a **success**, while an arm that ran out of reach means change the approach or
abandon. Attribution is not optional; the score depends on it.

**The discriminator is to remove the load and try again.**

```python
open_gripper()                       # drop the load first
for _ in range(3):
    before = _tcp()
    goto_pose(before + PULL_STEP, quat)        # <= 4 cm, along the pull axis
    if np.linalg.norm(_tcp() - before) > 0.03:
        return "object stopped"                # the arm can still move: the object was the limit
return "arm limit"                             # no advance under no load: the arm is the limit
```

**Measured on `libero_goal_task/open_the_middle_drawer_of_the_cabinet`**: on all **12** successful pulls
the tool advanced **4.1–4.5 cm** under no load after the stall, while the bar itself had moved only
**0.160–0.163 m** — so the *drawer* had stopped, not the arm, and those pulls were real. On the
out-of-reach drawer the same probe advances nothing, which is the arm's floor talking.

**If the verdict is "arm limit", the next question is the orientation family, not a harder push.** Same
task, same xy, stall z by approach family: **side 0.096** / 45° 0.157 / 60° 0.204 / 90° 0.206, with yawed
front approaches stalling at z ≥ 0.233. Side is the lowest-reaching family by a wide margin, and the free
space in front of the obstacle floors at **0.0961** — so measure the *free-space* floor once to know the
arm's own limit before blaming the scene. Refs `detect-a-reach-clamp-do-not-fight-it`,
`solve-ik-success-is-not-reachability`, `a-short-reachability-probe-is-a-false-negative-generator`.

**Executed source**: `libero_goal_task/open_the_middle_drawer_of_the_cabinet` `fix_code.py` — tail of
`_pinch_and_pull` (shipped revision), first proven in `probe20/22.py`; orientation floors from
`probe14/15/17/21.py`. **Diagnostic evidence only**: that task is **0/15** on both programs (the drawer
bar sits at z 0.0419–0.0421 while the lowest reachable tool z at that xy is 0.0901–0.1032, short by
0.0481–0.0613 m on all 15 seeds), so this records the attribution test, not a reward improvement.

### Development-only: score several candidate goal states in ONE episode

When the success predicate is unknown (`.bddl` reading is forbidden) and no baseline is available,
a **replay file** can be split into `# Code block N` sections: the harness executes each block as its
own `env.step(code)`, printing the reward after each, and breaks the episode as soon as one scores
1.0. Globals persist across blocks and exceptions are caught per block.

```python
# Code block 0   -> move the object to candidate goal A   (reward printed)
# Code block 1   -> move it from A to candidate B         (reward printed)
# Code block 2   -> move it from B to candidate C
```

**This is a debugging tool, not robot code.** It belongs in a *development probe*, never in a shipped
`fix_code.py`, and it accesses nothing a camera could not. Evidence: on
`push_the_plate_to_the_front_of_the_stove` seed 51 three candidate readings of "in front of the stove"
were scored in a single replay (all 0), which ruled out two hypotheses without burning three
episodes. Harness: `scripts/libero/replay_trial.py` `_parse_code_blocks` and the per-block `env.step`.
Source: the task's `findings.md` Pattern A; **not ingested as a skill-code instance** because its
executed source is not `fix_code.py`; 2026-09-14.

### A Tilted Gripper Extends Reach — and Costs Vertical Reach

**Trigger**: you must contact a feature that lies outside the top-down TCP workspace at low z (e.g.
the far/−Y side of a flat object). Tilting the wrist moves the fingertip laterally, because
`TCP = EE + 0.1 * R[:, 2]`.

```python
# (w,x,y,z); 135 deg about X  =>  approach axis (0,-0.707,-0.707)
TILT = np.array([0.382683, 0.923880, 0.0, 0.0])
move_to_joints(solve_ik(np.array([x, y, z]), TILT))
# TCP_y = EE_y - 0.0707,  TCP_z = EE_z - 0.0707   <- always recompute with the ACTUAL quaternion
```

**Why it is a trap as often as a tool**: on `push_the_plate_to_the_front_of_the_stove` seed 51 the
tilted fingertip reached y = −0.142 at x = 0.451 — 0.083 m further −Y than the top-down limit — but
the descent then stalled at TCP z 0.077–0.091, ~7 cm above the plate, so **no contact occurred**. Use
it only for objects taller than ~3 cm, and recompute the TCP from the achieved quaternion before
trusting any position derived from it (see "Measure the TCP, Not the Hand" above). Source: that
task's `findings.md` Pattern E, executed in `/tmp/fix_v3.py` — **not ingested as a skill-code
instance** because its executed source is not `fix_code.py`; 2026-09-14.

**Counterpart — a roll about world x is the mirror image, and the two entries do not contradict.**
The paragraph above measures the **TCP** (`EE + 0.1·R[:,2]`), a point on the tool axis, so tipping
costs it height — hence "use it only for objects taller than ~3 cm". A roll aimed at the **off-axis
low finger** gains height instead, and is what gets a paddle onto the table under a 0.1175 m pose
floor; on `libero_goal_task`'s run of this same task it pushed a 1.76 cm object that the top-down pose
could not touch at all. See "Roll the Hand to Make a Table-Level Paddle" above. Same task, same arm,
opposite sign — because the two entries are about two different points on the hand.

---

## Measure the Container's Reach Regime Per Seed — Do Not Tune Against One Seed's Outcome

**Trigger**: the same placement succeeds on some seeds and fails on others with a byte-identical
release pose. The instinct is to blame the controller and start tuning against the seed you just
watched. Check the **container's own pose** across seeds first — a couple of centimetres of
difference in where the container sits changes which reachability regime the arm is in.

```python
# localize the container with a geometry screen, and PRINT its pose every seed
c, zlo, zhi, ext = cloud_geom(pts)
if zhi - zlo < 0.020 or max(ext) > 0.20:        # a container has depth and a bounded extent
    continue
print(f"  bowl: prompt={prompt!r} c=({c[0]:.3f},{c[1]:.3f},{c[2]:.3f}) "
      f"z=[{zlo:.4f},{zhi:.4f}] ext={np.round(ext,4).tolist()} n={len(pts)}", flush=True)
# ... and print the ACHIEVED TCP again at contact
print(f"  over bowl: tcp=({tcp()[0]:.3f},{tcp()[1]:.3f},{tcp()[2]:.4f}) gap={gap():.4f}")
```

Those two lines, compared across seeds, are what exposes the regime. When a placement is a
**kinematic contact outcome** — the arm either stalls of its own accord or drives all the way in —
the success/failure boundary can sit inside a few millimetres of final reported z, which no amount
of reading a single trace will reveal.

**Why it works + evidence**: on `libero_goal_swap/put_the_cream_cheese_in_the_bowl` the bowl sits at
`y ≈ −0.062` on most seeds and at `y ≈ −0.045` on seeds 54/56 — 2 cm nearer. In the far regime the
arm stalls at reported z ≈ 0.1918 with the pads 3.7 cm above the rim (safe); in the near regime it
descends to ≈ 0.1205–0.1233, the pads enter the mouth, and the retreat drags the whole bowl off the
table. Seed 54 scored **1.0 at tcp z 0.1205 and 0.0 at 0.1233** across otherwise-identical
controllers, and seed 56 failed at 0.1235 before the pinch-settle was added and passed at 0.1235
after — i.e. the outcome flips on ~3 mm. That seed was correctly left blocked rather than chased.
Source: `outputs/libero_fix_loop/libero_goal_swap/put_the_cream_cheese_in_the_bowl/fix_code.py` —
`localize_bowl`, lines 225–248, plus the `over bowl:` print in `main()`; 2026-09-14.

**…and a single dev run is one *draw*, not a property of the seed — re-run before you diagnose.** The
same seed can flip under **byte-identical** code, so a first failure carries almost no information
while a first success carries even less. On
`libero_spatial_task/pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate` seed 58 scored 0.0
in the sweep and 1.0 on a repeat (the release landed 3 mm higher, nothing else changed), and seed 59
did the same; only seed 63 failed twice with a consistent mechanism. The discipline that follows:

- When a failing seed's trace shows a *plausible* placement (payload base at the surface, centre within
  a few mm of the target's own measurement), re-run that seed once **before** building a geometric
  explanation. Contact-level detail below the perception noise floor is what decides these.
- Justify a fix by **mechanism plus a printed quantity that changed**, not by the flip it produced.
- **Report a sweep as one draw.** A one- or two-seed difference between two program versions is not
  evidence for the better one — on this task the shipped program measured 14/15 and a mechanically
  better variant measured 13/15 on single draws, with the difference entirely inside the variance above.
  Compare versions by repeating the sweep, or by a quantity that is measured rather than scored.

Source: that task's `findings.md` §2 root cause 7 and §7; dev seeds only; 2026-09-16.

---

## Rotate an Articulated Control In Place — Top-Down Pinch Plus a Wrist Yaw Sweep

**Trigger**: a turn/rotate task — a knob, dial, valve lever, switch — where the success predicate is
a **joint angle** and the control rises above its mounting surface. Symptom of the wrong approach: a
side/horizontal pinch reports a *marginal* contact width (~0.04 normalized) and the articulated
state never changes. Any Cartesian translation of the gripper drags or tips the control instead of
rotating it.

```python
def topdown(yaw_deg):
    """Top-down gripper orientation; fingers close along (sin y, -cos y)."""
    R = Rotation.from_euler("z", yaw_deg, degrees=True).as_matrix() @ np.array(
        [[1, 0, 0], [0, -1, 0], [0, 0, -1]])
    q = Rotation.from_matrix(R).as_quat()          # xyzw
    return np.array([q[3], q[0], q[1], q[2]])      # wxyz

# pinch the control's RAISED BAND, not its whole cloud
zlo, zhi = np.percentile(pts[:, 2], [2, 98])
band = pts[pts[:, 2] > zlo + BAND_FRAC * (zhi - zlo)]      # BAND_FRAC ~ 0.55
tx, ty = np.median(band[:, :2], axis=0)                    # band's OWN median XY
gz = max(np.median(band[:, 2]) - PINCH_DROP, zlo + 0.010)  # PINCH_DROP ~ 0.008
yaw0 = closing_yaw(band[:, :2])                            # see grasp.md
goto_pose(np.array([tx, ty, gz + APPROACH_Z]), topdown(yaw0))
goto_pose(np.array([tx, ty, gz]), topdown(yaw0))
close_gripper()
if gap() <= AIR_GAP:                                       # air: nothing to turn
    goto_pose(np.array([tx, ty, gz + APPROACH_Z + 0.02]), topdown(yaw0))
else:
    for k in range(1, 13):                                 # same position, yaw only
        goto_pose(np.array([tx, ty, gz]), topdown(yaw0 + k * SWEEP_STEP))
    open_gripper()
```

Three things carry it:

1. **A top-down orientation has tool z = `(0,0,−1)` for every yaw**, so re-issuing the *same position*
   with only the yaw changed is a **pure in-place rotation about the vertical axis**. The wrist
   carries the pinched control with it and no lateral force ever reaches the object. Step the yaw in
   small increments (~10°) so the IK stays on the same j7 branch, and cap consecutive step misses.
2. **Pinch the band's own median XY and z**, not the whole cloud's OBB centre — a wide base drags
   that centre down and sideways, putting the fingers below the pinchable part.
3. **Verify by the measured gap before sweeping.** `gap() <= AIR_GAP` means the fingers closed on air
   and there is nothing to rotate; retreat and retry at a different height rather than sweeping.

**Sweep in a fixed WORLD-frame direction, and retry in the same direction.** Deriving the direction
from a per-seed visual quantity (a point-prompted sub-part centroid, the approach side) makes the
commanded direction vary even though the joint axis is fixed. A bounded joint can only be pushed
further toward its limit, so a **same-direction retry can never undo a partial turn** while a
reversed retry can. Offer the opposite direction at most once, and only after *every* pinch has
closed on air — i.e. only when nothing has been rotated yet, which makes it free insurance.

> **⚠ Suite scope — the *which* fixed direction is NOT fixed across suites.** "Fixed" here means
> *constant within an episode, and independent of per-seed visual noise*. It does **not** mean the
> same constant works everywhere. The **same identifier** `turn_on_the_stove` needs **opposite world
> directions in the two suites**: `libero_goal_swap` needs **+120° (world CCW)**, while
> `libero_goal_task` runs the instruction **"Turn off the stove"** and needs **−120° (world CW)** —
> a single −10° CW step scores 1.000 there while the full +120° CCW sweep never leaves 0.000. In a
> `_task` suite, derive the sign from the **polarity of `env.handle.task_language`**, never from a
> constant, and keep it constant within the episode. See [localize.md](localize.md), "The remap
> reaches a third suite" (ninth row). Measured 2026-09-17: `lib: libero_goal_swap/turn_on_the_stove`
> `a48105fb…` vs `lib: libero_goal_task/turn_on_the_stove` `adfca80f…`.

**Budget note**: `solve_ik` **raises** on total failure (`RuntimeError: IK failed for position … with
all orientation fallbacks`), so no `if joints is not None` guard is needed — wrap each sweep step in
`try/except` instead. This whole pattern costs **28 API calls** for a full episode.

**Why it works + evidence**: on `libero_goal_swap/turn_on_the_stove` the control is an articulated
post off the cooktop's −x edge whose upper band is 8 cm long but only **2.4 cm across**. A top-down
pinch of that band plus a fixed +120° world-CCW sweep turned the stove on for **all 15 development
seeds** on the first tested program — gap 0.0243 m after the pinch and 0.0171 m after the sweep on
every seed, episode = 28 API calls against a ~160-call horizon, and the epilogue keyframe shows the
burner glowing red. The side-approach alternative read `gripper_width` 0.039–0.040 m (marginal
contact) and failed. Source: `outputs/libero_fix_loop/libero_goal_swap/turn_on_the_stove/fix_code.py`
— `attempt`, lines 116:142, `sweep`, lines 97:113, `run`, lines 145:178; 2026-09-14.

---

## General Notes

- Add observations about which joint (e.g. j6 wrist) is most useful for in-place rotation
- Add notes on approach directions that avoid wrist limits
- Add notes on force/contact detection via gripper width or IK failure signals
