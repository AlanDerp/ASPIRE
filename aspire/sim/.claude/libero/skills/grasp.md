---
name: grasp
description: Structural template for pick-and-place programs. Covers the standard grasp-lift-place code skeleton, make_topdown_quat(), pre-grasp/lower/close sequence, and placement pattern. No task-specific strategies — those are discovered through experiment.
---

# Grasp — Code Template

> This skill provides the **structural skeleton** for pick-and-place programs.
> Task-specific strategies (object-specific offsets, SAM3 prompts, placement geometry)
> are discovered through experiment and added here as the skill library grows.

---

## Standard Pick-and-Place Template

```python
import numpy as np
from scipy.spatial.transform import Rotation

def make_topdown_quat(yaw_deg=0):
    """Top-down gripper orientation, rotated yaw_deg around Z."""
    R = Rotation.from_euler('z', yaw_deg, degrees=True).as_matrix() @ \
        np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]])
    q = Rotation.from_matrix(R).as_quat()  # xyzw
    return np.array([q[3], q[0], q[1], q[2]])  # wxyz for API

# --- Observe ---
obs = get_observation()
cam = obs["agentview"]
rgb = cam["images"]["rgb"]
depth = cam["images"]["depth"]
depth_img = depth[:, :, 0] if len(depth.shape) == 3 else depth
K = cam["intrinsics"]
E = cam["pose_mat"]

# --- Localize pick object via SAM3 ---
masks = segment_sam3_text_prompt(rgb, "<object prompt>")
if not masks:
    raise RuntimeError("SAM3: no masks for pick object")
best = max(masks, key=lambda d: d["score"])
obj_pts = mask_to_world_points(best["mask"].astype(np.uint8), depth_img, K, E)
obj_center = obj_pts.mean(axis=0)

# --- Grasp via GraspNet (preferred for irregular objects) ---
grasp_poses, grasp_scores = plan_grasp(depth, K, best["mask"])
best_grasp_world, _ = select_top_down_grasp(grasp_poses, grasp_scores, E)
if best_grasp_world is None:
    best_grasp_world = E @ grasp_poses[grasp_scores.argmax()]
grasp_pos, quat = decompose_transform(best_grasp_world)

open_gripper()
goto_pose(grasp_pos, quat, z_approach=0.15)
goto_pose(grasp_pos, quat)
close_gripper()

# --- OR: Grasp via make_topdown_quat (simple flat objects) ---
# quat = make_topdown_quat(yaw_deg=0)
# grasp_pos = np.array([obj_center[0], obj_center[1], obj_center[2] + <z_offset>])
# open_gripper()
# joints = solve_ik((grasp_pos + np.array([0, 0, 0.08])).tolist(), quat.tolist())
# if joints is not None: move_to_joints(joints)
# joints = solve_ik(grasp_pos.tolist(), quat.tolist())
# if joints is not None: move_to_joints(joints)
# close_gripper()

# --- Lift ---
lift_pos = np.array([grasp_pos[0], grasp_pos[1], grasp_pos[2] + 0.15])
joints = solve_ik(lift_pos.tolist(), quat.tolist())
if joints is not None: move_to_joints(joints)

# --- Re-observe for placement target ---
obs2 = get_observation()
rgb2 = obs2["agentview"]["images"]["rgb"]
d2 = obs2["agentview"]["images"]["depth"]
d2 = d2[:, :, 0] if len(d2.shape) == 3 else d2
K2 = obs2["agentview"]["intrinsics"]
E2 = obs2["agentview"]["pose_mat"]

target_masks = segment_sam3_text_prompt(rgb2, "<target prompt>")
if not target_masks:
    raise RuntimeError("SAM3: no masks for target")
best_t = max(target_masks, key=lambda d: d["score"])
tgt_pts = mask_to_world_points(best_t["mask"].astype(np.uint8), d2, K2, E2)
tgt_center = tgt_pts.mean(axis=0)
surface_z = tgt_pts[:, 2].max()

# --- Transport ---
above_target = np.array([tgt_center[0], tgt_center[1], lift_pos[2]])
joints = solve_ik(above_target.tolist(), quat.tolist())
if joints is not None: move_to_joints(joints)

# --- Place ---
release_pos = np.array([tgt_center[0], tgt_center[1], surface_z + 0.03])
joints = solve_ik(release_pos.tolist(), quat.tolist())
if joints is not None: move_to_joints(joints)
open_gripper()
```

---

## Key Conventions

**Depth normalization** — always do this before any 3D call:
```python
depth_img = depth[:, :, 0] if len(depth.shape) == 3 else depth
```

**SAM3 result** — list of dicts, pick highest score:
```python
best = max(masks, key=lambda d: d["score"])
obj_pts = mask_to_world_points(best["mask"].astype(np.uint8), depth_img, K, E)
```

**GraspNet TCP offset** — `plan_grasp` already applies a 0.12 m offset along the grasp Z axis
to its returned poses; do not add another TCP compensation on top of GraspNet grasps.

**GraspNet grasp selection** — use `select_top_down_grasp`, not a manual z-axis loop:
```python
grasp_poses, grasp_scores = plan_grasp(depth, K, mask)
best_grasp_world, _ = select_top_down_grasp(grasp_poses, grasp_scores, E)
if best_grasp_world is None:
    best_grasp_world = E @ grasp_poses[grasp_scores.argmax()]
```

**GraspNet produces a DIRECTION, not a position** — its pose can sit systematically *outside* the
object's silhouette at that height (see "Rim-Snapped Grasp" below). Never assume `plan_grasp` +
`select_top_down_grasp` returns a contact point on the object surface. Its top-down filter is also
loose (threshold 0.8 admits ~28° of tilt).

---

## Rim-Snapped Grasp for Wide, Shallow Objects

**Trigger**: `close_gripper` returns a near-zero gripper width (fingers closed on nothing), or the
object is wider than the gripper opening (~0.08 m) so a centred grasp cannot straddle it. Trace
symptom: `plan_grasp` succeeds with a plausible-looking pose, but the fingertip lands some
centimetres *outside* the object's silhouette at that height.

**Code** — measure the shell from the object's own point cloud and put the fingertip *on* it, with a
strictly vertical top-down orientation whose closing axis is radial:

```python
def shell_radius(pts, c, z, half):
    """Median in-plane radius of the visible surface in a thin z slab."""
    sel = np.abs(pts[:, 2] - z) < half
    if sel.sum() < 15:
        return None
    return float(np.median(np.linalg.norm(pts[sel][:, :2] - c, axis=1)))

# c     = object XY centroid from mask_to_world_points
# rim_z = 97th percentile of the object's z  (the rim / top of the wall)
gz = rim_z - 0.014                       # grasp a little below the rim
r_g = shell_radius(pts, c, gz, 0.014) or 0.045
d = np.array([np.cos(np.radians(phi)), np.sin(np.radians(phi))])
tcp = np.array([c[0] + r_g * d[0], c[1] + r_g * d[1], gz])
q = make_topdown_quat(phi + 90.0)        # closing axis radial to the object
open_gripper()
goto_pose(tcp, q, z_approach=0.09)
close_gripper()
```

The grasp direction `phi` is taken from the GraspNet top-down pick
(`np.degrees(np.arctan2(pos[1] - c[1], pos[0] - c[0]))`) and swept through +90/+180/+270, then
+45/+225 with `r_g *= 0.88`, until the grasp is confirmed.

**Why `make_topdown_quat(phi + 90)`**: with this `make_topdown_quat`, the gripper's finger-closing
axis in world XY is `(sin(yaw), -cos(yaw))`. Passing `phi + 90` makes the two fingers close
*radially* — one inside the cavity, one outside — and converge on the shell. `phi + 180` would close
tangentially instead.

**Why it works + evidence**: on `libero_goal_swap/put_the_bowl_on_top_of_the_cabinet` the bowl's
outer radius at GraspNet's chosen height (z≈0.010) is only ~0.030 m while the proposed fingertip sat
~0.06 m from the centroid, so the fingers closed ~0.03 m outside the wall. Rim-snapping flipped
development seeds 51–58, 61, 63–65 from reward 0.000 to 1.000, each on the **first** grasp attempt
(gripper width 0.071–0.097). Source: `outputs/libero_fix_loop/libero_goal_swap/put_the_bowl_on_top_of_the_cabinet/fix_code.py`
lines 145–178; 2026-09-14.

---

## Walk a Radial Candidate List When the Object Is Wider Than the Gripper

**Trigger**: the object is wider than the gripper opening (~0.08 m), so the default
`plan_grasp` + `select_top_down_grasp` pinch descends through the mouth and closes on air
(`gripper_width` after close ≈ 0.015–0.02). Same geometry as the rim snap above, but here the pinch
height and the sweep direction are *derived* from the object's measured shell rather than taken from
the planner, and the candidates are **walked in order** instead of commanded once.

```python
# zr    = z_lo + 0.62 * object_height      (high grasp band)
# zr_lo = z_lo + 0.35 * object_height      (low band)
# Rw    = half the 98th-2nd percentile spread of the object cloud in a thin z slab at zr
tcp = np.array([bx + Rw * np.cos(phi), by + Rw * np.sin(phi), zr])
q = yaw_quat(phi + 90.0)          # closing axis radial to the wall
open_gripper()
goto_pose(tcp, q, z_approach=0.09)
close_gripper()
w = gripper_width()
if w < AIR_GRASP_WIDTH:           # 0.05 -> air; retreat and try the NEXT candidate
    retreat(tcp, q, 0.25)         # do not abort the episode here
```

Candidate order: `radial_+x_high`, `radial_-x_high`, `radial_+y_high`, `radial_-y_high`, a low-band
`radial_+x`, a `rim_side` pinch, then a GraspNet top-down fallback.

**Why the list matters more than the entry**: `solve_ik` stops ~5 cm above the requested height on
one side at a given `xy` (the kinematic floor, see "Stop a Descent at the Measured Kinematic Floor"),
so the first candidate air-grasps on 8 of 15 seeds and the *mirrored* side succeeds on the second
attempt. A single commanded candidate with no fall-through loses those seeds.

**Why it works + evidence**: on `libero_goal_swap/put_the_bowl_on_the_stove` the bowl is ~11 cm wide
against an ~8 cm gripper opening; the Stage-0 baseline scored 4/15 (only seeds 52, 54, 59, 63, where a
finger happened to catch the rim) and every baseline failure logged a GraspNet top-down pinch whose
width after close was 0.015–0.02. With the radial candidate list every development seed logs
`width = 0.090–0.102` and the bowl lifts; 15/15. Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_bowl_on_the_stove/fix_code.py` — `candidates`;
2026-09-14.

#### Order the list by where each azimuth puts the *RELEASE*, not by a fixed azimuth order

The order above (`+x`, `-x`, `+y`, `-y`, …) is a default, not a rule. When the object hangs
off-centre from the TCP — true of every wall pinch here — **which azimuth you pinched decides where
the release column lands**, and if the goal container sits near the far edge of the workspace the
wrong azimuth puts the release column outside the arm's reach.

```python
def hanging_offset(tcp, bx, by):
    """Where the object sits relative to the TCP for a given pinch."""
    return np.clip(np.array([bx - tcp[0], by - tcp[1]]), -0.08, 0.08)

def release_column(tcp, bx, by, place):
    """TCP xy that puts the object's centre on `place` for this pinch."""
    off = hanging_offset(tcp, bx, by)
    return np.array([place[0] - off[0], place[1] - off[1]]), off

# rank candidates by the x of their release column, ascending: pinching the NEAR side of
# the object keeps the release column about one radius closer to the base than the far side.
#   wall gate FIRST -- a clamped offset can fabricate a small, plausible release column:
#   wall = |tcp_xy - object_xy| <= 1.6 * Rw + 0.010
rows.append((0 if wall else 1, 1 if viol > 1e-6 else 0, round(viol, 4), float(rel[0]), i, d, ...))
```

**Why it works + evidence**: on
`libero_spatial_swap/pick_up_the_black_bowl_between_the_plate_and_the_ramekin_and_place_it_on_the_plate`
the default `radial_+x_high` puts the TCP on the far side, hanging the bowl 49 mm toward −x, so the
release TCP must be commanded to `plate_x + 0.049 ≈ 0.784` — **outside the workspace** (measured wall
at the release height: cmd 0.780 → achieved 0.750; cmd 0.750 → 0.7500). A systematic 3.4 cm x
shortfall on every descent hop released the bowl over the plate's rim and tipped it. 9 of 15 seeds
failed this way, and **which seeds passed was decided purely by how far out the plate happened to be**
(plate x 0.719–0.726 passed, 0.731–0.740 failed) — not by the bowl, the grasp or the perception. All
four azimuths grasp this bowl equally well (measured widths 0.085–0.111, all lifted); only the release
differs. Ranking by release column selects `radial_-x_high` (release x 0.686, 6 cm *inside* the wall)
and the miss drops 0.034 → 0.0003–0.0020 m, 15/15. The `wall` gate matters because a clamped offset
turns a planner pose 0.195 m from the bowl into `release_x = 0.646`, the smallest of all candidates,
promoting it to first and burning an attempt on seeds 60/64 (201 → 159 and 232 → 159 API calls after
the gate). Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_between_the_plate_and_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— `hanging_offset`, `release_column`, `order_candidates`; 2026-09-15.

#### The general form: rank the walls by their alignment with the *goal direction*

The rule above ranks by the release column's `x`, which is the right proxy only when the goal happens
to lie along x. The direction-free form is to score each wall normal by how *anti-aligned* it is with
the vector from the object to the goal:

```python
walls = [(1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)]
# grasp wall u (tool = centre + u*r) -> the payload hangs at -u*r from the tool;
# we want that hang direction aligned with the goal direction d, i.e. u = -d first
walls.sort(key=lambda u: float(np.array(u) @ d))
```

The physical statement is the one worth remembering: **pinch the wall AWAY from the goal, so the
payload hangs on the goal side of the tool.** A payload pinched on the goal-facing wall hangs *behind*
the tool, so putting its centre on the goal requires driving the tool one payload radius *past* the
goal — into the reach clamp. Pinched on the far wall, the release column is one radius *short* of the
goal, comfortably inside the box.

**Why it matters that this is derived from the goal, not from x**: the x-ranking above is what you get
when the goal is at larger x than the object; swap the scene around and it inverts. Sorting by
`u @ d` needs no such assumption.

**Evidence** (a second, independent task arriving at the same conclusion through the same clamp): on
`libero_spatial_swap/pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate` the
goal-facing-wall version commanded release columns `x = 0.764–0.789` against the arm's hard clamp
(`x ≈ 0.750` — the same wall measured in the section above), stalling 2–4 cm short and leaving the
bowl on the plate's *near edge*. Because every landing then sat **on** the tolerance boundary, reward
flipped between near-identical trials — 5.1 cm passed while 3.6 cm failed, so the measured distance to
the plate was *not* predictive of reward. That non-predictiveness is the diagnostic signature of a
marginal placement, and it is worth recognising before you go looking for a perception bug. The
away-wall version commands `x ≈ 0.685`; drop accuracy `0.028–0.051 m → 0.003–0.008 m`, dev reward
12/15 → 15/15 (seeds 58, 59, 63 fixed). Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate/fix_code.py`
— `candidates` lines 291–321; 2026-09-15.

**Third confirmation, and it removes the last excuse for a fixed azimuth.** On
`libero_spatial_swap/pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate` the **goal moves
while the object does not** (plate x 0.447–0.473, y 0.186–0.213; bowl fixed at 0.389–0.405,
−0.153…−0.139 across seeds). A hardcoded azimuth there is right only by luck — the goal direction
happens to be +y on these seeds, but nothing guarantees it. Sorting by `u @ d` picked
`radial_-y_62` first on all 15 seeds, the measured hanging offset came out `(+0.000,+0.046)`, and the
release column landed at `plate_y − 0.046` — short of the plate and inside the workspace, first try,
every seed. Two further notes worth carrying: the grasp `z` is computed from the **object's own base**
(`base + frac × height`), so the identical code grasps a bowl on the table and one 3.7 cm up on a
support; and the wall radius is **re-measured in a z-slab at that height** rather than taken from the
object's widest extent. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate/fix_code.py`
— `candidates` lines 316–342; 2026-09-15.

**Corollary — once the release is *servoed*, the ordering stops being an accuracy device.** On
`libero_spatial_swap/pick_up_the_black_bowl_on_the_ramekin_and_place_it_on_the_plate` the release is
closed on the held object's own cloud (`transport.md`, "When the offset is NOT constant across grasps"),
which removes the hanging offset from the accuracy budget entirely. The same task also showed the
ordering costing nothing: `radial_-x_high` — the candidate the release-column ordering promotes to
first — air-grasps on **13 of 15** seeds (`width 0.014–0.016`), the second candidate succeeds, and with
the corrected centre the failed pinch no longer displaces the object (seed 61: (0.443,0.213) →
(0.437,0.219)), so the fall-through costs one attempt and nothing else. So when a servo owns the
release, **order the candidates for grasp reliability and ignore their release columns** — the ordering
rule above exists to protect a release that is computed, not measured. Source:
`.../pick_up_the_black_bowl_on_the_ramekin_and_place_it_on_the_plate/fix_code.py` — `order_candidates`
lines 396–432, `candidates` 368–382; 2026-09-15.

---

## Scan the Pinch *Radius* — a Fixed Offset From the Rim Is a Coin Flip

**Trigger**: an object **wider than the gripper can straddle**, so it has to be pinched against one of
its own walls. The direction list above is only half the search; the *radius* is the other half, and a
single `r_rim + constant` grips only sometimes — the radius that grips varies with the object's pose and
with where the wall actually is in depth.

**Judge the pinch by the opening it leaves, then scan.** Every lift that worked on
`libero_spatial_swap/pick_up_the_black_bowl_on_the_cookie_box_and_place_it_on_the_plate` left an opening
of **0.058–0.077**; every close that did not left **0.015–0.043**. There is no overlap, so the post-close
opening decides without a tuned threshold:

```python
PINCH_OFFSETS = (0.012, -0.003, -0.008, -0.013, 0.002)     # offsets from r_rim
for R2, cand in pinches:
    off = np.asarray(cand, dtype=float)[:2] - tcp_xy()
    if float(np.linalg.norm(off)) > REACH_TOL:             # one measured correction
        goto_pose(np.array([cand[0], cand[1], zr]), q)
        off = np.asarray(cand, dtype=float)[:2] - tcp_xy()
    if float(np.linalg.norm(off)) > REACH_TOL: continue    # cannot be there, skip
    close_gripper()
    width = gripper_width()
    if width >= AIR_GRASP_WIDTH: break                     # wall between the fingers
    open_gripper()
```

`r_rim + 0.012` alone gripped **12 of 15** development seeds; the rest needed `r_rim − 0.013` (seed 53),
`r_rim − 0.008` (seed 60) or `r_rim + 0.002` (seed 65). Four consequences, each measured:

- **Keep the descent radius equal to the first pinch radius.** A descent at 0.016 that then *slides
  inwards* to a 0.012 pinch drags the object ~3 cm at grasp height — seeds 63, 64 and 65 each read a
  solid 0.062–0.074 opening and then failed the lift with "bowl still on table". With descent == pinch
  all three lift and pass.
- **A close that fails to lift DRAGS the object — do not repeat the same radius on it.** The drag
  measured 20 mm then 50 mm on seed 57, and 18 → 18 → 40 mm on seed 64, always towards the tool axis,
  until the object toppled. Treat a non-lifting close as "this radius is wrong" and continue the scan;
  cap `MAX_CARRY_ATTEMPTS`.
- **Check the object is still in its canonical pose before scanning further.** After a drag it may be on
  its side, where no rim pinch exists at any radius:

```python
if (b_hi - b_lo) > max(0.055, 1.35 * h_bowl):     # 0.067 vs 0.044 upright
    print("toppled, no rim pinch available"); break
```

Without it, seed 60's second attempt spent **25 closes** across every direction and radius before the
episode died.

- **Abandon a wall after TWO consecutive air closes — one wrong wall radius can eat the budget.** A
  `close_gripper` is the unit of cost (`MAX_CLOSES = 10`), and a wall whose radius estimate is wrong
  fails at *every* remaining radius on that wall, because every radius is derived from the same bad
  `Rw`. Seed 53's failed first revision spent **5 consecutive air closes** on one wall (raw opening
  <0.05 each) and had too little budget left to reach a wall that grips. Count the airs *per wall* and
  break out of that wall alone — the outer `for u in walls` loop must keep running:

```python
airs = 0
for off in PINCH_OFFSETS:
    ...
    if width < AIR_GRASP_WIDTH:
        open_gripper(); retreat(quat, 0.12)
        airs += 1
        if airs >= 2:
            break            # this wall's radius estimate is wrong; try another wall
        continue
```

  This is a **budget guard, not a reward flipper**: it costs nothing on a wall that grips and its whole
  value is leaving closes available for the walls that can. **Evidence**: shipped revision 15/15 on dev
  seeds 51–65. Source:
  `outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate/fix_code.py`
  — `grasp_bowl` lines 333–403 (`airs = 0` at 361, the break at 384); 2026-09-16.

**Evidence**: shipped revision 13/15 on dev seeds (seeds 60 and 64 blocked, both by the drag-chase mode
above; seed 57 documented as *unstable* — the same command lifted on some runs and not others, reported
opening 0.071 vs 0.070). Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_on_the_cookie_box_and_place_it_on_the_plate/fix_code.py`
— `pinch_directions` lines 408–438, the offset loop in `run()`, toppled guard at the top of the attempt
loop; 2026-09-15.

#### Generalise the scan to the *vertical* axis — deepen in place when the close reads air

A radius that is wrong is not the only way to miss the wall: the **height** can be wrong too, and the
cheapest correction is to re-try at the same xy rather than pay for another approach cycle.

```python
for extra in (0.010, 0.020):          # 2 goto_pose + 2 gripper commands, vs a full approach
    if w >= AIR_W:
        break
    open_gripper()
    go(x, y, z0 - extra)              # the SAME xy, deeper
    close_gripper()
    w = gap()
```

**Why the height goes wrong in the first place is worth knowing, because it is a perception
artifact, not a geometry error.** When the arm parks near the bowl, SAM3 merges the carried/parked
gripper with the bowl and inflates the measured rim: on seed 62 a re-localised retry read
`gz = 0.214` against a true rim near 0.042 — a 0.19 m error — and the following close gave
`air grasp w = 0.015`. So a **geometry screen on the candidate's z-extent is what catches this**; a
raw `rim_z` is not trustworthy whenever the arm is close to the object. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_between_the_plate_and_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— the in-place deepen at lines 283–295, `AIR_W` at 244; 2026-09-16.

**The deepen has a *ceiling* as well as a floor, and on a thin slab the window is measured, not
guessed.** "Deeper is better" is the wrong instinct: past a point the pads drive the payload into the
surface or through a gap in it. On `libero_goal_task/put_the_wine_bottle_on_the_rack` (a 1.8 cm slab)
the bite is measured from the slab's **top edge**, and the two populations separate cleanly across 14
attempts:

| bite below the top edge | outcome |
|---|---|
| **≥ 5.0 mm** | held through the lift, **11/11** |
| **≤ 4.3 mm** | slipped, **3/3** |

```python
tip_goal = clip(ztop - 0.007, zbot + 0.004, ztop - 0.002)   # aim 7 mm, keep 4-2 mm of headroom
# dive until |tip - tip_goal| <= 0.0006, and walk an overshoot BACK — do not accept a shortfall
```

The 0.6 mm tolerance is what makes the window real: a depth controller that stops "near" the target can
land on the wrong side of a 0.7 mm-wide decision boundary, and the measured pairing shows exactly that
(`tip - 0.0036` and `tip - 0.0024` held at close 0.7599 / 0.7884, while `tip 0.0038` gave close 0.2574
and slipped). **Do not read the deepening loop as "retry until it works"** — read it as "reach the
measured depth, and treat a shortfall as a failure, not as a near-miss". Source:
`outputs/libero_fix_loop/libero_goal_task/put_the_wine_bottle_on_the_rack/fix_code.py` — `pinch()`,
block 0; evidence `sweep4_seed_55.log`, `sweep4_seed_56.log` vs `sweep3_seed_56.log`; 2026-09-17.

---

## Verify a Grasp by the Measured Gripper Gap, Not by the Plan

**Trigger**: any grasp — especially a smooth or rigid object — where success cannot be read off the
commanded trajectory because the planner has no reliable contact signal.

```python
def _gap():
    """Total finger gap in metres."""
    return float(np.asarray(get_observation()["robot_cartesian_pos"],
                           dtype=np.float64)[-1]) * 0.08

AIR_GAP = 0.0022      # an empty closed grip reads ~0.001
# gate: AIR_GAP < gap < ~0.02 is a candidate hold, but it must ALSO survive a lift
# and a re-close before it counts
```

The gap is a *three-way* discriminator, not a two-way one. Measured on this Franka/gripper:
air ≈ 0.0010, a real bowl hold 0.0033–0.0185, and a **blocked** grip 0.0211–0.0349. A blocked grip
passes a naive `gap > AIR_GAP` test while holding nothing, so check the upper bound too and re-measure
after a short lift.

**Why it works + evidence**: on `libero_goal_swap/open_the_top_drawer_and_put_the_bowl_inside` the
grasp closes on air when it is aimed from an unscreened mask (`gap = 0.0010`) and reads
`gap = 0.0066` with a lift reading `0.0059` once the aim is right. Gating every grasp *and* every
transport hop on this measurement is what let the program detect a lost object instead of releasing
an empty gripper into the drawer. Source:
`outputs/libero_fix_loop/libero_goal_swap/open_the_top_drawer_and_put_the_bowl_inside/fix_code.py` —
`_gap`, `grasp_bowl`, `carry_to`; 2026-09-14.

**A calibrated three-way gate for a wide bowl on a raised support.** Confirmed on a fourth task with
the band written out explicitly, so the numbers can be lifted directly:

```python
close_gripper()
g = gap()                       # gap() = robot_cartesian_pos[-1] * 0.08
if g <= AIR_GAP:                # 0.0035 - closed on nothing
    ... return None
if g >= MAX_GAP:                # 0.030 - pads wedged on something, not holding
    ... return None
...
goto_pose(np.array([tx, ty, lift_z]), quat)      # lift 0.10 m before trusting the hold
g2 = gap()
if g2 <= AIR_GAP:               # slipped on the lift
    ... return None
drop = float(meas[2]) - bowl["base"]             # release drop measured at the pinch
```

Two details make this portable. First, `AIR_GAP = 0.0035` sits a factor of 2 above air
(≈0.001–0.0013 in this convention) and a factor of 2 below a real hold — a band chosen from *measured*
margin, not from a round number. Second, `drop` is measured against the **object's own base**, so the
release height follows the object and the same program works on the table or 3.7 cm up on a stove slab.

**Evidence**: hold gap **0.0080–0.0083 on 15/15** seeds (0.3 mm spread), lift gap unchanged at
0.0042–0.0043, `drop = 0.026` on every seed. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate/fix_code.py`
— `grasp` lines 345–392, gate block 360–380; 2026-09-15.

**The lift re-read has a *direction* — a widening reading is a slip.** Re-reading after the lift is
not only about "is it still there": compare the lift reading against the **pinch** reading rather
than a fixed threshold, because the wrist reaches the commanded carry height whether or not the
object came along.

```python
AIR_GRASP_WIDTH = 0.05   # raw robot_cartesian_pos[-1]: at/below this the fingers met nothing
SLIP_DELTA = 0.03        # a WIDER reading after a lift means the object slipped out

close_gripper()
width = gripper_width()
if width < AIR_GRASP_WIDTH:
    print("  air grasp", flush=True); retreat(tcp, quat, 0.25); return "air", None

goto_pose(tcp + np.array([0.0, 0.0, 0.06]), quat)
goto_pose(tcp + np.array([0.0, 0.0, 0.20]), quat)
if gripper_width() > width + SLIP_DELTA:
    print("  slipped out during lift", flush=True); retreat(tcp, quat); return "slip", None
```

Note the units: these thresholds are in **raw** `robot_cartesian_pos[-1]` units, which is the same
quantity `_gap()` above returns × 0.08 — so `AIR_GRASP_WIDTH = 0.05` ≈ 0.004 m and
`SLIP_DELTA = 0.03` ≈ 0.0024 m in the `_gap` convention. The same `width + SLIP_DELTA` re-read is
applied again after the carry and after the descent to the place pose, so a slip anywhere along the
transfer is caught before release.

**Both constants above are for a grasp that HOLDS THE OBJECT BETWEEN TWO PADS. Neither transfers to
a bowl WIDER than the gripper.** Such a bowl can only be pinched with *one* pad inside its cavity, and
then the numbers move:

| | air | real hold |
|---|---|---|
| two-pad / friction grasp (values above) | ≤ 0.05 | 0.058–0.077 |
| one-pad radial wall pinch on a 10.5 cm bowl | 0.011–0.016 | 0.042–0.122 |
| one-pad radial wall pinch, that bowl on a *raised* support | ≤ 0.050 | close 0.091–0.114, lift 0.052–0.061 |

Read the first and last rows together: **the same grasp *type* does not have a universal population.**
Two one-pad pinches on the same 10.5 cm bowl differ by ~0.03 in both their close and their lift
readings, depending on where the bowl sits and how it settles. So there is no value of `AIR_W` that is
correct in general — only one calibrated to *this* scene's measured populations.

Two consequences, both measured on `libero_spatial_task/pick_up_the_black_bowl_between_the_plate_and_the_ramekin_and_place_it_on_the_plate`:

1. **Put the air boundary in the *measured gap between the populations*, not at the nominal opening.**
   `AIR_GRASP_WIDTH = 0.05` is the gripper's half-opening, which lands *inside* the hold population for
   this grasp: a settled one-pad pinch bottoms out near **0.043**, so the strongest available hold was
   classified as air on every retry (seed 62: `lost w=0.083 -> 0.050`, budget exhausted, reward 0.0).
   Setting `AIR_W = 0.030` made the first pinch hold, carry 0.40 m and release; passing seeds read
   0.070–0.074 post-lift and are untouched.
2. **Drop the `width + SLIP_DELTA` upper bound for this grasp type — the test must be one-sided.**
   A marginal wall pinch does not hold where it closed: the bowl slides down its own wall until it
   wedges near the base, so the aperture *closes in* rather than widening. Measured on clean
   single-pinch probes: `close 0.1034 -> lift 0.0834 -> lift+0.26 s 0.0430`, and `0.1133 -> 0.0892 ->
   0.0424` — stable at the wedge point with the object still between the pads. **A large post-lift
   closing delta is settling, not loss**, and the upper test threw away every usable grip on the
   long-carry seeds. The one test that is always valid: `if w2 < AIR_W: return None`.

   **…but "always" is too strong, and the exception is worth stating as a rule.** That test is sound
   only while `AIR_W` sits below the hold population's *own floor* by more than the reading noise. On
   `libero_spatial_task/pick_up_the_black_bowl_on_the_cookie_box_and_place_it_on_the_plate` the lift
   reading floored at **0.052 against an `AIR_W` of 0.050** — a two-count margin — so the same
   one-sided test was one noisy reading away from classifying a genuinely held bowl as an air close,
   and the consequence is severe: the code re-opens the gripper and *drops the payload in flight*.
   The acceptance was therefore written as **retention, not an absolute floor**:

   ```python
   close_gripper(); w = raw_w()          # raw robot_cartesian_pos[-1]
   if w < AIR_W:  return None            # rejects the air close at close time
   ... lift 0.06, then 0.16 ...
   w2 = raw_w()
   held = (w2 >= AIR_W) or (w2 >= 0.45 * w)   # <-- retention protects the lift check
   ```

   An air close in flight collapses toward 0 (a ratio of ~1.0 *of a value already below the
   threshold*); a real wedge pinch holds a ratio of 0.45–0.60. **Both terms are kept** — the absolute
   one is what rejects the air close at close time, the ratio is what keeps a tight-margin hold from
   being thrown away. Generalise the trigger, not the constant: *if your `AIR_W` and your hold floor
   are within a few counts, add the ratio term; if they are far apart, the absolute test alone is
   fine.* Source:
   `outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_on_the_cookie_box_and_place_it_on_the_plate/fix_code.py`
   — `grasp_bowl`, retention gate; 15/15 dev seeds, `close 0.091–0.114 → lift 0.052–0.061`, zero
   rejected holds; 2026-09-16.
   (Conversely, on a friction grasp the upper bound is what catches a real slip — scope it, do not
   delete it.)

**What a one-pad pinch on a bowl wider than the 0.08 m aperture *cannot* do is carry it level — and the
resulting tilt, not the placement, is what decides the marginal seeds.** Measured on
`libero_spatial_task/pick_up_the_black_bowl_on_the_wooden_cabinet_and_place_it_on_the_plate`: the
payload hangs with a cloud z-extent of **0.048–0.054 against a true height of 0.043**, i.e. 3–7° of
tilt that no amount of placement-loop tuning can remove, because it is fixed by the *grasp*.

The consequence is a hard ceiling on this task's reliability, and it shows up as a **free fall**: the
arm's kinematic floor on this scene is `tcp_z ≈ 0.078–0.083` over a plate top of `0.0057`, so the
payload is released ~12 mm above its support and *falls*. That fall converts the grasp's tilt into a
landing outcome, and the outcome is chaotic — the settled cloud's extent (see `transport.md`, *"Judge a
marginal landing by the settled cloud's z-extent"*) separates every observed pass from every observed
fail, while the landing offset separates nothing. Lowering the release is the one unexplored lever: the
arm was measured creeping ~1 mm per command at the floor (`0.085 → 0.082 → 0.081 → 0.080 → 0.079`) while
a 2 mm stall threshold broke the descent loop, so a lower release is reachable for ~10 extra
`goto_pose` calls.

**Gripping higher does not buy clearance — it moves the floor up by about as much.** The drop is
`tcp_z_floor − hang − support_top`, and *both* terms respond to where the pinch sits: a higher pinch
shrinks the hang, but the arm's floor at that xy rises. Measured independently on
`libero_spatial_task/pick_up_the_black_bowl_on_the_ramekin_and_place_it_on_the_plate`: at the plate's xy
the floor is `tcp_z ≈ 0.0595` over a plate top of **0.0058** with a hang of **0.0412–0.0418** — a ~1.2 cm
drop. Commanding 0.0488 achieved 0.0595, and five further downward commands were no-ops, one of which
moved the tool *up* (`0.0650 → 0.0716`). Pinching at **0.78 h made seeds 55/62/65 worse** (the bowl was
pushed off the plate), while 0.60 h was the best value tried — a **second, independent negative** for
raising the pinch, matching the `PINCH_FRAC` 0.62 → 0.80 result above on a different task. Treat the
grip height as a tuning parameter of the grasp, not as a way to escape the floor: the drop is a property
of the arm at that xy, and the only lever that removes it is a **lower release altitude**, which the
descent loop must be willing to creep for (see the ~1 mm/command creep measured above). Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_on_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— `rest_z`/`z_cap` and the descent guards — plus that task's `findings.md` root cause 11 and P4;
2026-09-16.

**Negative result — do not repeat it: raising the pinch band does not improve the hang.** Moving
`PINCH_FRAC` from 0.62 to 0.80 (pinching higher up the bowl's wall, where the radius is smaller) was
measured and did **not** reduce the tilt, and it regressed seeds 52 and 55; it was reverted. Treat the
tilt of a one-pad pinch on an over-wide bowl as a property of the grasp, not of the pinch height.
Source: that task's `findings.md` P6 and its `fix_code.py`; 2026-09-16.

**A rim pinch has three failure signatures, and they are all in the aperture sequence — not in the
final value.** Sample the aperture at several points along the lift (`ws = [...]`), because a single
value cannot distinguish "holding" from "was holding":

| signature | reading | meaning |
|---|---|---|
| **slide** | `min(ws[-2:]) < AIR_GRASP_WIDTH` (e.g. `[-0.0002, 0.008, 0.0115]`) | the bowl slid out entirely |
| **worked wider** | `max(ws) > width + SLIP_DELTA` | the bowl forced the pads apart |
| **steady creep** | `ws[0] - ws[-1] > CREEP_TOL` (e.g. `[0.0868, 0.081, 0.0759]`, creep 0.0109) | escaping slowly — it will not survive the carry |

The trap is the fix, not the diagnosis: **loosening `CREEP_TOL` to keep these marginal holds converts a
visible failure into an invisible one** — the bowl is dropped in flight over the plate, and that scores
0 exactly like the visible failure did. On a rim pinch a creeping hold is not a hold. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_next_to_the_cookie_box_and_place_it_on_the_plate/fix_code.py`
— `lift_and_confirm` (constants at 41–43); 2026-09-16.

**Why it works + evidence**: on
`libero_spatial_swap/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate` this is the
guard that makes a **radial wall pinch** safe to attempt without ground truth — the fingers can close
on air beside the wall, and the pinch can shove the bowl. All 15 development seeds accepted the first
pinch (`tries=1`) with a clean `bowl lifted` line and scored 1.0, i.e. no seed was ever mis-taken for
a hold. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate/fix_code.py`
— `attempt()`, `gripper_width`; 2026-09-15. This complements, and does not replace, "Verify a Grasp by
the Object Rising" below — a thin-shelled object can read a small width even when correctly pinched,
so the width gate proves *nothing was gripped by mistake*, not that the object is aboard.

### At *release* the same window must be two-sided — an open gripper reads ~0.080, not ~0

The window above guards a *hold*. Verify a **release** with it too, but add an explicit upper bound,
because the naive test is not merely weak here — it is inverted:

```python
open_gripper()
for _ in range(10):
    get_observation()
g = gap()
# open ~0.080 (released) | held ~object width | closed on air ~0.001
if AIR_GAP < g < 0.075:      # NOT `g > AIR_GAP`
    ...                      # something is still wedged between the pads: press and re-open
```

`gap() > AIR_GAP` ("the fingers are no longer closed on air") is **true after every successful
release**, because a released object leaves the fingers fully open. Calibration for this
Franka/gripper: fully open **0.080**, holding a 6.1 cm can **0.0577–0.0637**, closed on air
**0.0010–0.0013**. The failure is silent and score-neutral — the recovery branch it guards simply runs
on every episode, pressing the arm an unmotivated extra 3 cm below the container floor.

**Why it works + evidence**: on `libero_object_swap/pick_up_the_alphabet_soup_and_place_it_in_the_basket`
the one-sided form fired on **15/15** development seeds; the two-sided form fires on **1/15** (seed 60,
`gap = 0.0740`, still reward 1.0) and the sweep stays 15/15. Only the per-seed logs exposed it — the
reward was identical either way. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_alphabet_soup_and_place_it_in_the_basket/fix_code.py`
— `place`; 2026-09-14.

**Two further releases, both 0/15.** The ketchup task shipped `AIR_GAP < g < 0.075` and the milk task
`AIR_GAP < g < 0.075` (with `AIR_GAP = 0.030` there, since a 5.3 cm brick is held at a wider gap than a
can); on both, the wedged-release branch never fired on any development seed, while the one-sided form
would have fired on all 15. The calibration is stable across carried objects — a released gripper reads
~0.080 whatever it was carrying. Sources:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_ketchup_and_place_it_in_the_basket/fix_code.py`
(`place`) and `.../pick_up_the_milk_and_place_it_in_the_basket/fix_code.py` (`place`); 2026-09-14.

**And one case where it fires *spuriously* — benign, but not rare.** The tomato-sauce task measured a
post-release gap of **0.0692** (seed 57) and **0.0737** (seed 60): the gripper is open, but short of the
~0.080 a fully released object leaves, so the "still wedged" branch fired and pressed 3 cm deeper. Both
seeds still scored 1.000. So the branch is not free — the failure it guards against is silent, but so is
its own misfire, and the rate varies by task (1/15 on alphabet soup, 0/15 on milk and ketchup, **2/15**
here). Two consequences: keep the upper bound comfortably above the *lowest* genuine release gap you
observe, and log the gap on every release so a misfire is visible in the sweep rather than inferred from
the score. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_tomato_sauce_and_place_it_in_the_basket/fix_code.py`
(`place`); 2026-09-14.

### On a radial wall pinch, release with the object already *touching* the surface

**Trigger**: any grasp that is a **radial / side wall pinch** — the case "Walk a Radial Candidate List
When the Object Is Wider Than the Gripper" above exists to construct. The fingers do not lift cleanly
off such an object: as they open they *flick* it sideways off the wall they were pinching. If the
object is still airborne at that instant the flick carries it freely and the landing scatters.

The countermeasure is to end the descent **at** the surface rather than a few millimetres above it,
using the touchdown guard that is already there to stop the moment contact occurs:

```python
# descend until the object is ON the surface, then open.  The touchdown guard
# (gripper width opening up beyond grasp_width + SLIP_DELTA) stops the descent
# the moment contact occurs, so this cannot press the object into the surface.
for dz in [0.10, 0.04, 0.02, 0.010, 0.005, 0.002]:
    goto_pose(np.array([release_xy[0], release_xy[1],
                        surface_top + tcp_to_object_bottom + dz]), quat)
    if gripper_width() > grasp_width + SLIP_DELTA:
        break        # object has met the surface -- finish the release now
open_gripper()
```

The guard is what makes the last rung (`dz=0.002`) safe: without it, commanding the object 2 mm
*into* the surface would press it there, and the friction that holds it during the press would then
oppose the release. With it, the ladder stops at contact and the final rung is never actually reached
when the object is already down.

This trades a small, bounded approach against a large, unbounded scatter — worth it whenever the
acceptance gate is only a few sigma away. **Evidence**: on
`libero_spatial_swap/pick_up_the_black_bowl_next_to_the_cookie_box_and_place_it_on_the_plate` the
landing error went from mean **0.0133 → 0.0117 m** and max **0.016 → 0.015 m** against an **0.018 m**
acceptance gate — better or equal on all 15 development seeds, all still 15/15 at reward 1.000, i.e.
the improvement is robustness at the gate rather than a fix for a scoring seed. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_next_to_the_cookie_box_and_place_it_on_the_plate/fix_code.py`
— final descent loop in `attempt`, lines 563–572; 2026-09-15.

---

### Measure the carried object's *hang* in the air, not at the grasp

**Trigger**: an object **wider than the gripper opening** carried by a radial wall pinch — a *friction*
hold on a wall, not a form fit — and released by height above a support surface. Symptom: the object is
pressed **into** the support at the end of the descent, or a light support is displaced sideways.

The grasp-time height offset is measured while the object still rests on the table, i.e. **before the
pinch carries any of its weight**. It then slips deeper between the fingers during the lift:

```
seed 51:  0.0249 at the pinch  vs  0.0455 m measured in the air
seed 57:  0.0271               vs  0.0385
seed 58:  0.0246               vs  0.0588
all 15:   0.024-0.027          vs  0.035-0.068      <- a 1.1-3.4 cm under-estimate
```

**The *sign* of the stale error is scene-dependent, which is why the rule is "measure in the air"
rather than "correct the grasp estimate by +2 cm".** On
`libero_spatial_task/pick_up_the_black_bowl_on_the_cookie_box_and_place_it_on_the_plate` the pinch-time
estimate was stale in the *opposite* direction by an order of magnitude: the air-measured hang was
**0.0354–0.0437** while the number available at pinch time was **0.177–0.198** — over by ~15 cm,
because at pinch time the bowl's visible base is the *surface it is standing on*, not its own bottom.
There, a descent built from the pinch-time number would have released the payload 15 cm above the plate
and dropped it; here the same mistake under-reaches by 1–3 cm.

A descent built from the stale number puts the object's own lowest points at `z = 0.004-0.011` against a
plate top of `0.005` — the light smooth plate squirts out from under it.

```python
def hanging_drop(cur_xy, fallback, frames=None):
    gz_now = fingertip_z()                       # TCP height
    rgb, d, K, E = frames if frames is not None else observe()
    pts = object_points_near(rgb, d, K, E, cur_xy, radius=0.12,
                             z_floor=gz_now - 0.12)   # <-- excludes the table top
    if pts is None or len(pts) < 40:
        return fallback
    hang = gz_now - float(np.percentile(pts[:, 2], 2))
    if not (0.005 < hang < 0.10):                # object-height sanity band
        return fallback
    return max(fallback, min(hang, 0.070))       # never below the stale estimate
```

**The `z_floor` is what makes it work at all — and its absence fails *silently*.** Without a floor the
window sits under the wrist and returns a dark table mask, the sanity band then rejects everything, and
the helper quietly returns its `fallback` on every seed: measured as a **0.395 m "hang"** on all 15
development seeds, i.e. the fix was inert until the floor was added. This is the third independent
appearance of the same rule — a measurement window needs a *height* gate, not just an xy radius (see
`transport.md`, the height-gated window for a servoed payload; `localize.md`, the held-object
physical-sanity gate).

**Evidence**: seed 57 flipped reward 0 → 1 (`measured 0.0385 vs grasp estimate 0.0271`, released 1.1 cm
higher, bowl bottom at `z = 0.004` on a `0.005` plate). Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— `hanging_drop` lines 444–489, called after the lift (546) and at the release column (577); 2026-09-15.

---

## Ladder a Long Cartesian Descent — One Hop Under-Reaches Silently

**Trigger**: any `goto_pose(pos, quat, z_approach=...)` or `solve_ik` descent whose vertical travel is
more than a few centimetres, especially the final descent of a grasp. The commanded depth is *not*
reached: the measured TCP is short by 2–3 cm, the fingers close on air (`gap ≈ 0.001`), and **nothing
raises** — `move_to_joints` reports `completed: true`. Nothing about the episode looks like a failure
until the reward comes back 0.

```python
def hop_to(px, py, pz, quat, step=0.025):
    cur = tcp()
    d = np.array([px, py, pz]) - cur
    n = max(1, int(np.ceil(float(np.linalg.norm(d)) / step)))
    for i in range(1, n + 1):
        goto_pose(cur + d * (i / n), quat)
    return tcp()

def below(px, py, z_from, z_to, quat, step=0.025):
    z = z_from
    while z > z_to + 1e-6:
        z = max(z_to, z - step)
        goto_pose(np.array([px, py, z]), quat)
    return tcp()
```

Each hop is computed from the **measured** TCP, so a shortfall cannot compound into the next hop, and
the short hops keep a warm-started `solve_ik_with_convergence` inside its basin. Cap the hop at ~2.5 cm.

This is distinct from the kinematic floor below: here the arm *can* reach the target, it just does not
get there in one command. Use the floor pattern when progress stops no matter how you command.

#### Ladder in ABSOLUTE command space — `zcmd -= step`, never `measured - step`

The snippet above rebuilds each hop from a **snapshot** of the TCP taken once (`cur = tcp()`) and then
commands absolute points `cur + d * (i/n)`, which is correct. The trap is the *other* loop shape: a
descent that re-reads the measured z on every iteration and commands `zcmd = measured_z - step`.

`goto_pose` does not land on the commanded z. On `pick_up_the_salad_dressing…` the arm tracked every
command with a **constant 1.27–1.34 cm vertical lag** (cmd 0.278 → meas 0.2914, cmd 0.271 → meas
0.2841, cmd 0.264 → meas 0.2768) — so a relative ladder nets `step − lag ≈ 0.7 cm` of real travel per
0.020 m command, **3× less than intended**, and the iteration budget expires while the pads are still
centimetres above the object:

```python
zcmd = max(z_goal, zcmd - step)      # ABSOLUTE: subtract from the previous COMMAND
if now > prev - 0.003:               # break on LACK OF PROGRESS, not on a fixed gap
    break                            # ... this is the line that prints "floor at ..."
prev = now
```

**Diagnostic that separates the two bugs — and it is the whole reason to know both.** A descent that
hit the *kinematic floor* stops on genuine loss of progress and **prints** its floor line. A descent
that ran out of *loop budget* stalls **silently**: no IK failure, no floor line, just pads parked
1–4 cm high. On the salad-dressing seed 51 run the log read `stalled at 0.161, above the bottle top`
for **every** yaw candidate and never printed the floor — the floor was at 0.122–0.123. If you see a
stall and no floor line, raise the budget and check the ladder's arithmetic before you believe the
arm is blocked.

**Evidence**: 0/15 → 15/15 on development seeds 51–65. Every seed moved from `stalled at 0.161/0.165`
+ `RuntimeError: could not grasp the dressing` to `floor at cmd 0.088–0.089 meas 0.122–0.123`, closing
at 0.122–0.123. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_salad_dressing_and_place_it_in_the_basket/fix_code.py`
— `descend_to`; 2026-09-14.

**This supersedes the relative form promoted from `bbq_sauce`.** That task's `descend_to` shipped
`zcmd = max(z_goal, cur - step)` with `cur = float(tcp()[2])` — the relative shape — and it worked
there (0/15 → 15/15), but only because its floor sat high enough that 18 relative iterations happened
to reach it. The same code on the dressing scene stalls 4 cm short. The tracking lag is a property of
the controller, not of the scene, so treat the absolute ladder as the general form and the relative
one as an accident that worked once.

**Third reason the same shape fails, and a stronger one: on a `_task` scene the reported z need not be
in the world frame at all.** Both mechanisms above are *lag* — the arm tracks high by a constant, so a
relative ladder under-travels. On `libero_object_task/pick_up_the_bbq_sauce_and_place_it_in_the_basket`
a stall gate on `robot_cartesian_pos[2]` aborted the descent on **hop 1**: after a laddered descent to
a commanded `z = 0.05` the reading was `z = 0.2850`, while the episode video plainly shows the pads
inside the basket. The reading sat roughly constant whatever was commanded, so this was not lag but a
frame mismatch — the same family as the 0.107 m offset measured on the chocolate_pudding `_task` run
(see [manipulation.md](manipulation.md), "Measure the TCP, Not the Hand"), but larger, and *not* the
same constant. **Do not carry either constant across tasks**: measure the relation with a two-point
probe, and where the only need is for the descent to end, prefer no measured-z gate at all — ladder in
absolute command space to a deliberately unreachable target and let the arm's physical stall set the
release.

The one field of `robot_cartesian_pos` that *was* faithful on this task is the last component: the
gripper **width** matched `close_gripper`'s `gripper_width` exactly on every seed, so the entire hold
check can be built on it while the position part is ignored. Evidence: with the gate removed the
descent is deterministic and **15/15** development seeds pass; with the gate it aborted on hop 1.
Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_bbq_sauce_and_place_it_in_the_basket/fix_code.py`
— `descend_ladder` lines 164–177, `tcp` / `gap_raw` lines 50–55; 2026-09-16.

**Why it works + evidence**: on `libero_object_swap/pick_up_the_alphabet_soup_and_place_it_in_the_basket`
seed 51 a single 12 cm descent from z 0.172 to 0.052 landed at **z 0.080** — 2.8 cm short — and closed
with `gap = 0.0012 m`, scoring 0.000 with no error logged. Split into ≤2.5 cm hops it closed at
`gap = 0.0635 m` on the first attempt, and the same first-attempt hold reproduced on **all 15**
development seeds (`gap 0.0633–0.0637`, matching the can's measured 6.1 cm diameter). Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_alphabet_soup_and_place_it_in_the_basket/fix_code.py`
— `hop_to`, `below`; 2026-09-14.

---

## Gate a Closed Gripper on Aperture AND Finger Height

**Trigger**: driving a gripper into a bounded space (inside a bowl, a cup, a hole) where the motion
stops **on contact** rather than at the commanded pose. `goto_pose`/`solve_ik` undershoot here, and
the *first* descent from a standoff always half-travels, so a depth search over several targets is
needed.

```python
for dz in (-0.070, -0.055, -0.040):     # deepest first on this task
    ...                                  # 8/13 dev seeds vs 7/13 for the reverse order
```

**Why it works + evidence**: on `libero_goal_swap/open_the_top_drawer_and_put_the_bowl_inside` both
orders converge to the same physical grip — the first descent reaches `z 0.197–0.200` with
`gap 0.0000–0.0001` and the second grips at `z 0.019–0.022` with `gap 0.0053–0.0130` — so the
deepest-first gain is *not* a firmer press but a different arm path. Deepest-first scored 8/13
against 7/13 on the same seeds. **Read no more into this than the seed count**: on this task a 1–2 cm
trajectory change anywhere flips roughly 5 of 13 seeds in both directions, so treat single-seed
comparisons as noise and report the count. Source: same `fix_code.py` — `grasp_bowl`; 2026-09-14.

---

## Pinch a Tall Object HIGH So Its Body Hangs Below the Pads

**Trigger**: grasping a tall, narrow, capped bottle (or any object whose height is several times its
width) for a *carry*. The symptom of getting the height wrong is visible before any reward is read:
after the lift the object hangs tilted, and the measured grip gap is **much narrower after the lift
than at the pinch** — the object has slid or pivoted in the jaws. A mid-height pinch puts the centre of
mass just under the pads, which is only metastable; a high pinch leaves the mass hanging below like a
self-restoring pendulum.

```python
GRASP_FRAC = 0.78        # of the object's OWN z-range, not of a fixed height
LIFT_STEP  = 0.04        # absolute-z hops; NEVER one jump to the carry height

# choose the pinch height and the pinch xy from the object's own cloud:
zlo = float(np.percentile(pts[:, 2], 2)); zhi = float(np.percentile(pts[:, 2], 98))
z_grasp = zlo + GRASP_FRAC * (zhi - zlo)
band = pts[np.abs(pts[:, 2] - z_grasp) < 0.022]
if len(band) < 20:
    band = pts                                   # degrade, do not crash
bxy = 0.5 * (np.percentile(band, 2, axis=0)[:2] + np.percentile(band, 98, axis=0)[:2])

# lift as a ladder, re-reading the gap each hop:
z_lift = z_grasp
while z_lift < CARRY_Z:
    z_lift = min(CARRY_Z, z_lift + LIFT_STEP)
    goto_pose(np.array([bxy[0], bxy[1], z_lift]), quat)
held_gap = gap_raw()      # must be within ~0.02 raw of the pinch reading
```

**Validate the height against the object's own taper before trusting it.** A depth-slab profile sweep
prints the extents directly and shows where the shoulder is — do not pick `GRASP_FRAC` by eye:

```python
for frac in (0.30, 0.45, 0.55, 0.65, 0.75, 0.82, 0.90):
    zz = zlo + frac * (zhi - zlo)
    sl = pts[np.abs(pts[:, 2] - zz) < 0.012]
    if len(sl) >= 8:
        e = np.percentile(sl, 98, axis=0) - np.percentile(sl, 2, axis=0)
        print("    profile frac=%.2f z=%.3f n=%3d ext=(%.3f,%.3f)" % (frac, zz, len(sl), e[0], e[1]))
```

On the ketchup bottle this read `ext_y` **0.060 at frac 0.30 → 0.052 at 0.55 → 0.038 at 0.75 → 0.033 at
0.82** — a taper, so `GRASP_FRAC = 0.78` lands on the shoulder just under the cap and the jaws close on
the narrowest part.

**Use the lift re-read as the cheap hold check.** The pinch→lift change in the measured gap is a direct
read-out of sliding, and it needs no extra perception: before the fix it narrowed by **0.15–0.17 raw**
(0.49 → 0.32–0.34) on the failing seeds; after, it is `pinch 0.463–0.479 → lift 0.460` on **15/15**
seeds, a delta of **≤ 0.016 raw** — nothing moves in the grip. So the gate is not just "still above the
air floor" but "the gap did not *change*": `if held_gap <= AIR_GAP_RAW or held_gap > pinch_gap + 0.03`.

**Why it works + evidence**: on `libero_object_task/pick_up_the_bbq_sauce_and_place_it_in_the_basket`
(the runtime language is "pick the ketchup") the bottle was pinched at mid-height and on seeds 55, 63,
64 it pivoted about the pinch and hung tilted while the arm carried it, so the gripper descended into
the basket **empty** and the bottle was left standing on the table behind the basket — visible in the
video at 0.30–0.58 of the episode at 60–70° from vertical, with the last frames showing the fingers
inside the mouth and no bottle between them. Raising the pinch flipped **55, 63, 64** from 0.0 to 1.0
(12/15 → 15/15) with all twelve already-passing seeds holding. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_bbq_sauce_and_place_it_in_the_basket/fix_code.py`
— `GRASP_FRAC` line 14, `LIFT_STEP` line 17, the pinch band and profile sweep at lines 194–238; 2026-09-16.

---

## A Correct Pinch on a Tapered Neck Reads *Below* the Air Floor — Gate on the Lift Re-Read

**Trigger**: the pinch height is a fraction of the object's own height, and at that fraction the object's
cross-section is narrow — a bottle shoulder or neck, a tapered carton, a cone. The grasp is real and
load-bearing, but `close_gripper` returns an aperture of 0.02–0.03 m, which the usual absolute
"< 0.03 means it closed on air" heuristic rejects. The program then discards a grasp that would have held.

Trace symptom to grep for: `grasp failed: gap 0.0264` (or any value in the 0.02–0.03 band) with reward 0,
on a program whose *close* otherwise looks clean — no air close, no wedge, no IK failure.

```python
AIR_GAP = 0.012               # closed on air really reads below this
GRASP_MAX_GAP = 0.072         # wedged wider than this is not our object
...
close_gripper()
gap_close = aperture(get_observation())
if gap_close <= AIR_GAP or gap_close >= GRASP_MAX_GAP:
    open_gripper(); continue                # air, or wedged on something else
hang = tcp_pinch - object_zlo               # capture the hang HERE, before the lift
ladder_z(x, y, tcp_pinch, top_z, quat, "lift", step=0.040)
gap_lift = aperture(get_observation())
if gap_lift <= AIR_GAP or gap_lift > gap_close + 0.03:
    open_gripper(); continue                # it slid out on the way up
```

The lower bound and the upper bound are doing different jobs, and that is why both are here: `AIR_GAP`
rejects a close on nothing, `GRASP_MAX_GAP` rejects a jaw that wedged on the table or a neighbouring
object, and the **lift re-read** is the actual hold test — the aperture changing on the way up is a direct
read-out of sliding, and it costs no perception. Note the asymmetry in the second gate: `> gap_close +
0.03` compares against *this attempt's own* close, not against a constant, so a narrow pinch is not
penalised for being narrow.

**Why the absolute floor is the wrong instrument.** The object's own taper sets the floor's value. The
shipped profile sweep on the goal bottle of
`libero_object_task/pick_up_the_tomato_sauce_and_place_it_in_the_basket` (runtime language "Pick the
**bbq sauce**…") measured `ext 0.046 at frac 0.30 → 0.040 at 0.55 → 0.030 at 0.75 → 0.026 at 0.82` — so
at the documented `GRASP_FRAC = 0.78` a *correct* pinch necessarily reads ≈ 0.026 m, and an 0.030 floor
is guaranteed to reject it on that object every time. The threshold was wrong, not the pinch height.

**Evidence**: with the 0.0264 m close rejected, attempt 1 on dev seed 51 raised `grasp failed: gap 0.0264`
and the episode scored **0.000**. After `AIR_GAP` was lowered to 0.012 and the lift re-read added, seed
51 scored **1.0** and the full sweep went **15/15**, with `gap_close 0.0264 → gap_lift 0.0265` — a delta of
**+0.0001, identical on all 15 development seeds**: nothing moves in the jaws. A `(yaw, frac)` ladder
`[(0, 0.78), (0, 0.62), (90, 0.78)]` sits behind the first entry as insurance; the final sweep shows
**exactly one grasp attempt per seed, always `yaw=0 frac=0.78`**, so the fallbacks provably never fire and
no passing seed can regress through them.

**Scope of the evidence, stated plainly**: the 0.0264 failure was the same author's *first draft* of this
program, and the shipped `initial_code.py` already carries the corrected constant — so this is a repair
within one task's own development, not a measured gain over a provided baseline. It is recorded because
the *diagnosis* generalizes (the taper sets the reading; the hold test is the change, not the absolute
value), not because the before/after is a controlled comparison. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_tomato_sauce_and_place_it_in_the_basket/fix_code.py`
— `AIR_GAP` line 30, `GRASP_MAX_GAP` line 31, `aperture` 78–80, the close gate 334–337, the lift gate
345–351, `GRASP_LADDER` line 313; 2026-09-16.

---

## Pinch a Boxy Carton at a Fraction of Its OWN Measured Height — and Ladder the Lift

**Trigger**: a tall, light rectangular carton (here 13.4 × 5.0 × 2.7 cm) to be carried across the
table by a two-pad friction grasp. Neither requirement is about the carton's identity: the closing axis
must go across the **narrow** horizontal axis, and the pinch height must be a fraction of the object's
**own measured z-range** rather than a constant.

```python
GRASP_FRACS = (0.55, 0.40, 0.70)     # of the carton's OWN z-range
GRASP_YAWS  = (0.0, 90.0)
AIR_GAP, GRASP_MAX_GAP = 0.030, 0.072

z_grasp = brick["bot"] + frac * brick["h"]
open_gripper()
goto_pose(np.array([brick["cx"], brick["cy"], z_start]), q)
below(brick["cx"], brick["cy"], z_start, z_grasp, q)     # <=2.5 cm laddered hops
meas = float(tcp()[2])
if meas > brick["top"] - 0.020:      # the arm stopped at its reach-dependent floor;
    continue                          # accept only if the pads got DOWN onto the carton
close_gripper()
g = gap()
if g <= AIR_GAP or g >= GRASP_MAX_GAP:
    continue                          # air, or wedged on something that is not the carton
z = meas                              # ladder the LIFT: one jump throws a held object
while z < z_start:
    z = min(z_start, z + 0.04)
    goto_pose(np.array([brick["cx"], brick["cy"], z]), q)
if gap() > AIR_GAP: return True
```

Three of these lines carry more than they look:

- `z_grasp = brick["bot"] + frac * brick["h"]` is what makes the identical program work wherever the
  carton happens to stand — the height is relative to the **object**, and `brick` is re-localized on
  every attempt.
- The acceptance test is **relative to the object's top**, not to a commanded or absolute z:
  `meas > brick["top"] - 0.020` rejects the attempt where the arm stopped at its own kinematic floor
  short of the carton, which is otherwise indistinguishable from a successful descent.
- The **lift is laddered** (≤4 cm hops) exactly like the descent. The same rule that makes a long
  descent under-reach silently makes a long *lift* throw the payload out of the jaws, and a held
  object is the worse case to lose.

**Contrast with the bottle entry above — the fraction is not portable, the principle is.** For a
*tapered* bottle the pinch goes **high** (`GRASP_FRAC = 0.78`) onto the narrowest shoulder. A boxy
carton has no taper, so there is no narrow band to aim at and 55% of its own height is used. What
carries over is not the number but the method: sweep the object's *measured* z-profile and pick the
fraction where the cross-section is what the jaws need.

**Evidence**: 15/15 development seeds grasped on the **first** candidate (yaw 0, frac 0.55), with
`meas_z` 0.096–0.102 against carton tops of 0.138–0.140 — the pads 3.6–4.4 cm below the top — and
`gap` 0.0519–0.0535 after the close, 0.0520–0.0530 after the lift: a pinch-to-lift delta of
**≤ 0.0015 m**, i.e. nothing moved in the jaws. No seed logged a stall, an air close or a retry, and
the measured gap matched the carton's 5.0 cm y-width plus pad thickness, so the closing axis genuinely
straddled it rather than closing beside it. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_ketchup_and_place_it_in_the_basket/fix_code.py`
— `GRASP_FRACS` line 50, `grasp` lines 297–334 (laddered descent 306–311, relative-height acceptance
312–315, gap gate 317–321, laddered lift 323–331); 2026-09-16.

---

## Reach Past a Kinematic Wall by Tipping the Wrist — Laddering Further Just Saturates

**Trigger**: repeated closes return an **air** aperture while the pads' estimated xy stops short of
the object centre by more than a few mm, *and commanding further past the object does not move the
achieved position at all*. This is the grasp-side face of the reach wall that
[manipulation.md](manipulation.md) documents as a laddered `probe_reach_x`; the move below is what to
do once the wall has been found.

```python
TILT_LADDER = (0.0, 15.0, 25.0, 32.0, 20.0, 28.0)     # degrees

def tilt_toward(e_xy, theta_deg, yaw_deg=0.0):
    """Top-down pose tipped by theta_deg so the pads shift along +e_xy.

    The tool axis is rotated about the horizontal axis perpendicular to e_xy; the sign of
    that axis is chosen by predicting which candidate actually moves the pads toward e_xy.
    """
    R0 = Rotation.from_euler("z", yaw_deg, degrees=True).as_matrix() @ np.array(
        [[1, 0, 0], [0, -1, 0], [0, 0, -1]])
    e = np.array([float(e_xy[0]), float(e_xy[1]), 0.0])
    if np.linalg.norm(e) < 1e-9 or theta_deg <= 0.0:
        q = Rotation.from_matrix(R0).as_quat()
        return np.array([q[3], q[0], q[1], q[2]])
    ehat = e / np.linalg.norm(e)
    best = None
    for axis in (np.cross(ehat, [0.0, 0.0, 1.0]), np.cross([0.0, 0.0, 1.0], ehat)):
        R = Rotation.from_rotvec(np.asarray(axis, float) * np.radians(theta_deg)).as_matrix() @ R0
        off = R @ np.array([0.0, 0.0, 1.0])
        score = off[0] * ehat[0] + off[1] * ehat[1]
        if best is None or score > best[0]:
            best = (score, R)
    q = Rotation.from_matrix(best[1]).as_quat()
    return np.array([q[3], q[0], q[1], q[2]])
```

Rotating the pose about the horizontal axis re-aims the pads *along the tool axis* without moving the
arm — the pads swing out from under the wrist, which is reach the arm does not have.

**The wall this defeats is a software clamp, and that is why the tilt works and laddering does not.**
`solve_ik` clips the commanded hand position — `np.clip(pos, [-0.1,-0.5,0.005], [0.75,0.5,0.9])` at
`cap/integrations/franka/libero_reduced.py:383`, so x ≤ 0.75 and z ≥ 0.005 for *every* task in *every*
suite. A larger commanded x is discarded, not fought for, which is exactly why the
`aim += measured error` loop above converges to the same 0.750 forever. The tilt escapes the clamp
because the clamp constrains the **hand**, while the pads sit off the hand axis under a tilted
orientation: the pads can therefore pass 0.75 while the commanded hand position stays clipped. See
[manipulation.md](manipulation.md), "The Reach and Height Walls Are `solve_ik` Clamps, Not Physics".
Naming it correctly matters — the failure reads as a mechanical limit, and the natural response to a
mechanical limit (command further, ladder harder) is precisely the response that cannot work.

**Why it works + evidence**: on `libero_object_task/pick_up_the_chocolate_pudding_and_place_it_in_the_basket`
(the runtime language is "pick the salad dressing", object remapped) the bottle sits at x = 0.763 and
**every** top-down command saturates at the same achieved x. X overshoot does not help, and a
closed-loop `aim += measured error` iteration converges to the same point:

| commanded eef x | achieved pads x | close result |
|---|---|---|
| 0.763 / 0.772 / 0.781 / 0.790 / 0.799 | 0.748 / 0.750 / 0.750 / 0.750 / 0.750 | air, gap 1.2 mm |

The pads stop ~13 mm short of a 26 mm-wide bottle, so every top-down close reads aperture 0.0148 — the
whole difficulty of the task. A 12–28° tip moves the pads 0.747 → 0.752–0.760 and the same pinch then
holds (aperture 0.33–0.48, gap 26–38 mm) **at every tilt tried**, so the exact angle is not critical
and the ladder is a safety net rather than a search. On all 15 dev seeds candidate 0 (tilt 0) airs and
candidate 1 (tilt 15) holds at 36.5–38.3 mm. Note the achieved 0.750 wall is the *same* x = 0.750 that
`libero_spatial_swap` measured for this arm — an independent replication of the wall's position.
Requires the pad offset from [manipulation.md](manipulation.md) ("Measure the TCP, Not the Hand"):
`z_cmd = z_pad - Rz * PAD_FROM_EEF`, so the **pads** clear the object top rather than the reported
frame. Source: `outputs/working_codes/libero_object_task_pick_up_the_chocolate_pudding_and_place_it_in_the_basket_fix.py`
— `tilt_toward`, lines 60–82; 2026-09-16.

---

## Reach a Table-Level Pinch by a Lateral Approach That Keeps the Closing Axis

**Trigger**: an object short enough that the arm's **pad-point floor** is above its mid-height, so no
top-down command can bite it at *any* seating depth. Measure the floor before believing a ladder will
find a rung. On the `libero_goal_task/open_the_top_drawer_and_put_the_bowl_inside` slab (`tcp() = hand() − 0.100`
under `TOP_DOWN`; the arm saturates at `hand_z = 0.117`) the pad point floors out at **`tcp_z = 0.017`**
against a slab top of `0.0076`, and the ladder read `gap = 0.0014 / 0.0012 / 0.0015 / 0.0012` — all
empty — at four depths. The achieved orientation was *not* the cause (tilt measured 0.1° off top-down).
This is the same obstruction `grasp.pinch-flat-slab-at-ik-z-clamp` straddles at the deepest allowed pose;
when the object is too short even for that, the **pose** has to change, not the ladder.

```python
Q_LAT = np.array([0.0, 0.8660254, 0.0, -0.5])        # tool z = (-0.866, 0, -0.5)
axis  = np.array([0.8660254, 0.0, 0.5])              # pad point -> hand, 60 deg off vertical

z_pinch = top - 0.5 * span_z                         # the object's own mid-height
tgt     = np.array([c[0], c[1], z_pinch])
seat(tgt + 0.085 * axis, Q_LAT, iters=3, tol=0.010, tag="lat-far")   # find a branch from outside
seat(tgt, Q_LAT, tag="lat-pinch")

# judge the RETURNED pose by its functional properties, not by the quaternion you asked for
tz      = tool_z(raw()[3:7])
closing = quat_to_R(raw()[3:7])[:, 1]                # R[:,1] is the finger axis
if abs(float(tz[2])) < 0.30 or abs(float(closing[1])) < 0.85:
    return False                                     # this branch cannot pinch what you want
close_gripper()
# ... climb out ALONG the tool axis, then re-orient to TOP_DOWN in free space
```

**The rotation is about the closing axis, and that is the whole trick.** A 60° lateral keeps the fingers
closing along ±y, so the two **contact faces are the ones a successful top-down pinch would have used** —
the grasp is unchanged, only the *reach* is. The hand body ends up ~5 cm above and 8.7 cm +x of the pad
point, so the only gripper part near the table is the tilted finger, and the pads are placed on the
object's mid-height **by the command** rather than by where the tips stall. Rotate about the axis you
want to keep closing along; a rotation that also moves the closing axis buys reach by destroying the
grasp.

**Gate on the closing axis, not on the commanded quaternion.** `solve_ik` does not honour the requested
orientation — it walks a four-step fallback ladder (see [manipulation.md](manipulation.md), "The Reach
and Height 'Walls' Are `solve_ik` Clamps, Not Physics"), so a pose test written on the *commanded*
quaternion refuses branches that would work. On seed 55 the IK returned tool z `(-0.6, 0.09, -0.8)`,
still closing along ±y: functionally a correct lateral pinch that the previous
`tz[0] <= -0.60 and |tz[1]| <= 0.35` test rejected at the margin. Seed 55 was 0.0 before and 1.0 after;
test `|tool_z[2]|` and `|R[:,1][1]|` instead.

**Evidence**: load-bearing on 4 of the 15 development seeds, each with a full pinch where the top-down
ladder was empty at every rung — 55 `0.0425`, 61 `0.0423`, 62 `0.0424`, 65 `0.0421`. Seeds 55 and 62
scored 0.0 before the lateral existed; 61 and 65 reached 1.0 only with it. All four end with the box
verified inside the drawer cavity. Source:
`outputs/libero_fix_loop/libero_goal_task/open_the_top_drawer_and_put_the_bowl_inside/fix_code.py` —
`lateral_grasp`, lines 491–552; frozen-file sweep 2026-09-17. Ingested as
`knowledge/skill-code-instances/grasp/grasp.reach-a-table-level-pinch-by-a-lateral-approach-that-keeps-the-closing-axis.yaml`.

### A corner bite passes a loose ceiling but is not a hold — calibrate to the object's own populations

**Trigger**: any `held()` / `bite_ok()` test on a flat slab, whose acceptance threshold was chosen as a
single ceiling rather than as the object's measured band.

The same task measured three separate gap populations for a 4.0 cm slab: full pinch **0.0418–0.0424**,
empty **0.0010–0.0015**, and a corner/edge bite **0.013–0.034**. Only the first holds. A corner bite at
`gap = 0.0342` passed a `held()` whose ceiling was 0.070 and was gone by the first lift rung
(`lift z=0.065 gap=0.0010`). A 7 cm ceiling falsely admits a 6 cm corner reading, and no single cut can
separate the corner population from the full-pinch one — they are distinguished by **where** the fingers
sit, not by a threshold. Accept only the object's own band and re-check after every lift rung:

```python
SLAB_LO, SLAB_HI = 0.0385, 0.050        # measured full-pinch band for this slab
PAD_TOP_TRIES   = (0.015, 0.023, 0.007, 0.031)   # seating depths to try, in order
```

This is the band form of
`grasp.calibrate-the-hold-test-to-the-measured-populations-and-keep-it-one-sided`.

**Unresolved hazard — a full pinch can still be lost a few cm into the lift.** On seed 54 the slab was
held at `gap = 0.0418` through two rungs (`lift z=0.065`, `z=0.115`) and read `0.0010` at `z=0.175`,
its y drifting `0.143 → 0.115` between re-detections: it is **dragged, then slips**. A staged lift with a
re-close at every rung (`+0.05 / +0.10 / +0.16 / +0.24`) was already in place and was not enough. The
untested idea is to stage the lift in ~2 cm steps and watch for the **first sign of opening** (a rise
from 0.0418 toward 0.06) instead of waiting for the empty close. Recorded as a hypothesis, not a rule;
seed 54 is left deliberately un-tuned. Source and full table: the task's `findings.md`, P3 and P10.

## Recognise a *Gripless* Shell: a Table-Flush Rammed Surface Has No Reachable Band, and the Close Ejects It

**Trigger**: a thin, flat payload lying **flush on the table** (saucer, plate, shallow lid) whose outer
15–20 mm rises into a shallow flare (~20°) and then a rounded bevel (~45°), and whose **underside is the
table surface itself**. Nothing to probe: the near wall is the ramp, and there is no under-rim gap for a
20 mm pad.

**Why no pinch exists here — the mechanism, not an empirical failure.** A finger pad's face is a plane
containing the tool axis. Against a sloped ramp the pad therefore touches along a **line**, not an area,
and the closing force has a large component *along* the ramp. The jaws do not clamp the object, they
**wedge it and eject it**. A face-on clamp of the ramp is geometrically impossible anyway: the lower pad
would have to occupy the plate's own material or pass under the table.

**The tell is that the grip dies on the *first* commanded motion, including a purely horizontal one.** On
`libero_goal_task/put_the_bowl_on_top_of_the_cabinet` a depth-jitter pass did straddle the rim
(aperture **0.0084–0.0094 m**, indistinguishable from the wedges that hold on other tasks), and a
**15 mm horizontal drag** — which needs no vertical friction at all, the table carries the plate's weight —
collapsed it to **0.0010 m on 4/4 seeds tested** (53, 54, 57, 60). An 8 mm climb and a 4 mm downward seat
killed it too (seed 51).

```python
# the one test that separates a grip from a wedge — run it BEFORE believing an aperture
goto_pose([px + 0.015, py, pz], quat)        # 15 mm, in the plane, no lift
g2 = gap_m()
if g2 < AIR_FLOOR + 0.002:                   # it was never held
    held = False
```

> **This snippet is not ingestable as a store instance** — in the revision it came from it sits *inline*
> inside the run block (indented), not in a top-level helper, so a line range for it fails to parse. That
> is exactly the factoring cost promotion 0003 recorded. Write the probe as a top-level
> `def drag_test(px, py, pz, quat):` if you want it reusable.

**Two independent methods agree that nothing is reachable.** `plan_grasp` (GraspNet) returned
`No grasp candidates found` on **6 of 15** baseline runs for this plate. When a learned planner and a
geometric argument both come back empty, stop spending attempts.

**Everything in this task's fix was tried and every one of them failed** — recorded so it is not retried:
re-closes at +6/+25/+55 mm, a 4 mm downward seat, an inward-angled climb (+8 mm/2.5 mm in, +25/5, +55/9)
keeping contact on the shallow part of the flare, a lateral drag, and GraspNet. Each kills the wedge in
one move, on every seed.

**What to do instead of burning the horizon**: recognise the geometry, attempt the cheapest straddle once,
and **declare the task infeasible** rather than spending 14 closes and a retry budget. Related:
`abandon-a-pinch-wall-after-two-consecutive-air-closes`, and `verify-by-object-rise` — which is what
catches the *other* half of this failure, see below.

**The false positive that made this task look solvable for a whole sweep.** `initial_code.py` printed
`grasped = True` from a **0.0729 m** aperture on seeds 53/54/65 and ran a complete transport — while the
end-of-episode keyframe shows the plate **untouched in its original spot**. An aperture alone can never
certify a grasp; `verify-by-object-rise` (require the object's own cloud to rise > 12 mm) is the
certification that catches it, and it is why the shipped program refuses to transport air. The same
lesson as "a corner bite passes a loose ceiling but is not a hold", from the other direction.

**Executed source**: `libero_goal_task/put_the_bowl_on_top_of_the_cabinet` `fix_code.py` — drag probe
lines 384–401 (indented), acceptance at line 369, ramp profile table `profile_table` lines 184–198.
**Diagnostic evidence only**: the task is **0/15 on both `initial_code.py` and `fix_code.py`** (verified
single-revision, shipped md5 `4a212de084676e578a7ac275dcf5f9f8`), so this section records a genuine
*infeasibility* and a masking detection, not a fix that raises reward.

## Pinch the Rim Band When the Object Is Wider Than the Jaws

**Trigger**: `plan_grasp` raises `AssertionError('No grasp candidates found')` — or returns nothing —
because **`2·rmax > jaw opening`**, so a diametral pinch is geometrically impossible at *any* height.
Measure the object before theorising about the grasp: on `libero_goal_task/put_the_bowl_on_the_stove`
the instruction's object is a cone-rimmed plate with `2·rmax ≈ 0.140 m` against a **0.080 m** jaw
opening, and the initial program scored **0/15** — not a tuning failure, a geometric impossibility.

**The remaining closing geometry is the rim.** A plate or bowl rim is a **wedge**: the pads straddle
the ~8 mm band where the outer edge meets the inner ramp, and because the profile *widens upward* the
wedge also locks vertically — the pads cannot close further as the object is pulled down. That band is
~8 mm wide at the clamp floor but ~18 mm wide 7 mm lower, so the **depth is the whole game**:

```python
wide = 2.0 * R > 0.078                      # R = rmax of the object's mask
q    = mkq(180.0, 0.0)                      # jaws close along y, aiming at the object
yt   = cy + 0.945 * R                       # the rim's own y band, just inside the outer edge
for z in (0.20, 0.11, 0.05, CLAMP_Z + 0.007):
    go([cx, yt, z], q)                      # keep a legal pose as the fallback
deep = float(min(max(obj["zmax"] - 0.0094, -0.0035), 0.012))   # pads ~9 mm below the object's top
```

**A shallow engagement is not a weak grip, it is no grip.** A plain `goto_pose` pinch at the clamp
reaches only the top ~2.5 mm of the rim, closes at gap ~**0.0075**, and the plate slides straight out.
The working wedge closes at **0.0176–0.0187**. On a rim pinch the closed gap is therefore a
*diagnostic of engagement depth* rather than a retention score — see the bistability caveat below.

**The rim wedge is only reachable past the software clamp.** That is a separate mechanism, documented
in [manipulation.md](manipulation.md), "The clamp is a software floor, not a wall".

**Evidence**: `libero_goal_task/put_the_bowl_on_the_stove`, **0/15 → 11/15** development seeds
(pass 51,52,53,54,55,57,59,60,62,63,64). Source: `fix_code.py` — the `if wide:` run block, lines
183–251. Ingested as
`knowledge/skill-code-instances/grasp/grasp.pinch-the-rim-band-past-the-ik-clamp-when-the-object-is-wider-than-the-jaws.yaml`.

**Caveat — deep-wedge retention is bistable, and the closed gap does not predict it.** Same task, same
pose: seed 62 held at gap 0.0183 while 61 slipped at 0.0182; 51 held at 0.0176 while 56 slipped at
0.0187. Thirteen replays across five code variants never made 61 hold. Do **not** build a success
predicate on the gap alone — the honest reading of a wedge grasp is a measured probability, not a
threshold.

### …and a rim pinch needs the lift laddered

An unsecured wedge is thrown off the rim by a single fast lift. Ladder the lift in 4–9 mm rungs and
**re-measure the object's `zmax` after every rung** — the rung that fails is the one where `zmax` stops
rising. Here the ladder is `(0.004, 0.008, 0.013, 0.019, 0.027, 0.040, 0.060, 0.090)` with the check
`zmax > zmax_at_grasp + 0.02`. This is the laddered-lift rule
(`grasp.pinch-a-tall-carton-at-55-percent-of-its-own-height-and-ladder-the-lift`) applied to a
*wedge-secured* grasp, where the risk is the wedge opening rather than the object leaving the jaws.

## Stop a Descent at the Measured Kinematic Floor

**Trigger**: a top-down grasp where `solve_ik` reports success but the measured TCP stops tracking the
command before reaching the target — i.e. the requested grasp height is below what the arm can
physically reach at that `xy`. The arm has a reach-dependent Z floor; commanding through it produces a
strained, laterally-off pose rather than an error.

```python
def grasp(bx, by, gz, top_z, quat, step=0.015):
    goto_home_joint_position()
    open_gripper()
    zcmd = gz + 0.10
    move_tcp([bx, by, zcmd], quat, tol=0.030, retries=1)   # approach: retry is safe here
    meas = achieved_tcp()[2]
    while zcmd > gz:
        zcmd = max(gz, zcmd - step)                        # 15 mm steps
        move_tcp([bx, by, zcmd], quat, tol=0.030, retries=0)
        now = achieved_tcp()[2]
        if now > meas - 0.004:      # no further progress -> kinematic floor
            print(f"  descent floor at cmd {zcmd:.3f} meas {now:.3f}", flush=True)
            break
        meas = now
    if meas > top_z - 0.005:        # fingers still above the object
        return None
    close_gripper()                 # close at the floor, not at gz
```

**Why it works + evidence**: on `libero_goal_swap/put_the_wine_bottle_on_top_of_the_cabinet` the
nominal `gz = 0.062` was 5.7 cm below a kinematic floor at TCP z ≈ 0.119. v1 misread the resulting
error as an IK glitch and re-solved from home, which produced a strained pose that knocked the bottle
over (seed 52), scoring 8/15. Closing at the floor instead grasps the bottle's **neck** — every v2
seed logged `descent floor at cmd 0.087 meas 0.119` then `closed at tcp_z 0.120 aperture 0.181–0.185`
on the *first* attempt. 15/15; flipped seeds 52, 53, 54, 58, 61, 62, 65. Requires the TCP inversion in
[manipulation.md](manipulation.md) and the no-home-retry rule there. Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_wine_bottle_on_top_of_the_cabinet/fix_code.py` —
`grasp`, lines 236–269; 2026-09-14.

### Refinement: break on LACK OF PROGRESS, never on a fixed command-vs-measured gap

The loop above breaks on `now > meas - 0.004` — the right shape. The failure mode to avoid is a loop
that breaks on a **fixed** gap between commanded and measured position:

```python
# WRONG: at the kinematic floor the measured z stops falling, so the gap is pinned at
# exactly one step, the test never fires, and the loop re-issues the same command
while cmd_z - meas_z > tol:
    cmd_z = max(gz, cmd_z - step)
    move_tcp([x, y, cmd_z], quat, retries=0)

# RIGHT: break on lack of progress, plus an iteration cap as a backstop
if now > meas - 0.004:
    break
```

At the floor the gap sits at a constant one-step value forever, so a fixed-gap exit condition is
never satisfied and the loop runs until the episode dies with
`ValueError: executing action in terminated episode` from inside `move_to_joints` — the whole episode
is lost, not just the descent. This applies to **placement** descents as much as grasp descents.

**Evidence**: on `libero_goal_swap/put_the_wine_bottle_on_the_rack` this exact bug cost the episode
on the pre-fix program; after the change every development seed logs
`place floor at cmd 0.374 meas 0.385` and exits the loop immediately. Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_wine_bottle_on_the_rack/fix_code.py` —
`lower_onto`, lines 261–285; 2026-09-14.

### Refinement: a *fixed-length* hop ladder lands short, because the arm tracks HIGH

The refinements above fix the *exit* condition. This one is about the *budget*: a ladder with a
**fixed number of hops** inherits the z-tracking error as a fixed shortfall. The arm tracks ~1.0–1.2 cm
**high** of every commanded z (the same lag documented in [manipulation.md](manipulation.md)), so a
6-hop × 2 cm descent from `pinch_z + 0.11` bottoms out at `pinch_z + 0.02` — above the object's rim.
The pads then close on air on **every** candidate and the log shows the achieved height above the
command (`cmd z 0.223 → achieved 0.240`).

```python
z = float(tcp()[2]) + 0.02
last = None
for _ in range(14):                 # longer budget: the tracking error eats the first few hops
    z -= 0.02
    if z < zr - 0.05:               # zr = pinch height, e.g. z_hi - 0.012
        break
    go([tcp_xy[0], tcp_xy[1], z], quat)
    zc = float(tcp()[2])
    if zc < zr + 0.004:             # really arrived -> stop
        break
    if last is not None and zc > last - 0.004:
        print("      descent blocked at z=%.3f" % zc)   # wall / drawer floor
        break
    last = zc
```

The stall break is what makes the longer budget safe — without it the extra hops are commanded into
the drawer floor and burn the episode horizon. So: **read the achieved z back, and let the loop run
until it has actually arrived or stopped moving.** Distinguish this from a genuine floor: here the arm
*can* reach the height, it simply had not arrived when the fixed ladder ran out.

**Evidence**: flipped seeds 62, 63, 64 from 0.0 to 1.0 on
`libero_spatial_swap/pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_cabinet_and_place_it_on_the_plate`
— `reached z=0.240 (target 0.191)` with `gap=0.0020` before, `reached z=0.192` with `gap=0.0049` then
`lift gap=0.0078` after; 9/15 → 12/15. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_cabinet_and_place_it_on_the_plate/fix_code.py`
— descent loop in `profile`, lines 169–188; 2026-09-15.

### Refinement: the same loop applies at the *pinch* — press to the clamp before closing

The descent above breaks on lack of progress *during the search*. The same one-millimetre lag also
bites at a **grasp** whose depth is a hard kinematic limit rather than a measured quantity — a thin
slab on a table, a box lid, a flat packet, where the pads must straddle the object's top face.

```python
z_min = IK_MIN_Z + Z_CMD_REP_OFFSET        # deepest pose the IK clamp allows
descend_to(bx, by, z_min, quat)            # stepped descent
prev = float(tcp()[2])
for _ in range(8):                         # <-- press until the arm really reaches the clamp
    press_cmd(cmd_of([bx, by, z_min]), quat)
    cur = float(tcp()[2])
    if prev - cur < 0.0005:
        break
    prev = cur
z_deep = tcp()[2]                          # the MEASURED depth, not the commanded one
close_gripper()
```

`z_deep` must be measured, never the commanded `z_min`: it feeds the release-height term
`hang = (z_deep - FINGERTIP_OFFSET) - object_zlo`, so a commanded depth silently puts the object in
the wrong place later. Pair with the measured-gap verifier above, and treat a failure as an air
grasp to retry rather than as a bad target.

**Why it works + evidence**: on `libero_goal_swap/put_the_cream_cheese_in_the_bowl` the pinch covers
only the top ~7 mm of a 17.7 mm-thick slab. Seed 64 closed to `gap = 0.0025` then `0.0017` m (air)
on both attempts — the pads had skated off the top face — and the episode ended with the scene
untouched. Pressing to the clamp first gave `gap after close = 0.0417` / `gap after lift = 0.0423`
and reward 1.0 on the same seed, taking the sweep from 13/15 to 14/15. Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_cream_cheese_in_the_bowl/fix_code.py` —
`grasp_box`, lines 298–332; 2026-09-14.

**Confirmed on a sibling slab in a different suite**: on
`libero_object_swap/pick_up_the_butter_and_place_it_in_the_basket` the same recipe — descended and then
pressed to `HAND_FLOOR = IK_MIN_Z + Z_CMD_REP_OFFSET = 0.115` until the arm stopped tracking — pinched a
7.5 × 3.9 × 1.6 cm slab with `gap after close` and `gap after lift` of **0.0389–0.0390 m on all 15
development seeds**, on grasp attempt 0 every time. On that task no GraspNet call, no yaw sweep and no
retry was ever exercised: with the pads straddling the slab's full height, the first candidate worked.
That is the point of this pattern — a flat, short object has no mid-height straddle to find, so the
search that costs other tasks several attempts collapses to one. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_butter_and_place_it_in_the_basket/fix_code.py`
— `main`; 2026-09-14.

### Refinement: the floor is *position dependent*, and `solve_ik` drifts sideways instead of failing

The refinements above assume the floor is one number you will discover by stepping. It is not — it varies
with `xy`, by centimetres. On `libero_object_swap/pick_up_the_bbq_sauce_and_place_it_in_the_basket` a
commanded TCP z of 0.04 reached **0.115** at `(0.45, 0.058)` but **0.074** at `(0.49, -0.23)`: 4 cm lower
a few centimetres away on the same table. Any program that assumes a fixed grasp depth, or derives a
later placement from the *commanded* depth, is wrong at one of the two positions.

The second half of the trap is that `solve_ik(pos, quat)` does **not raise** below the floor. It
substitutes a fallback orientation, and because the fingertip offset is then applied along a different
`R[:, 2]`, the TCP **drifts laterally instead of going down**:

| xy | commanded | measured TCP | outcome |
|---|---|---|---|
| (0.45, 0.058) | 0.04 | (0.539, 0.066, 0.105) | 9 cm sideways, no descent |
| (0.599, 0.263) | 0.04 | (0.627, 0.270, 0.107) | sideways |
| (0.65, 0.265) | 0.04 | (0.682, 0.277, 0.109) | sideways |

So a descent that "succeeded" can have moved the gripper 9 cm off the object's axis while its `z` still
looks plausible. Two consequences worth encoding:

- **Return the measured TCP from the descent helper** — `return tcp()`, never `z_goal` — and let the
  caller consume that.
- **Gate the grasp on a height *relative to the object*, not on the command**: accept iff
  `measured_z <= zhi + 0.005`, i.e. "the fingers got below the top of the bottle". That test is true
  whether the floor is 0.115 or 0.074, which is exactly what a fixed-depth assumption cannot express.

**Why it works + evidence**: the pre-fix program on that task aimed at `zlo + 0.38 h = 0.059` and gated on
`got[2] > zlo + 0.55 h`, so **all four yaw candidates were rejected** and the run raised
`RuntimeError: could not grasp the bbq sauce` — 0/15. Stepping in 20 mm and accepting on the relative test
gave 15/15, with the measured hang (`grip_z_measured - zlo`) feeding the release height so the placement
did not inherit the commanded-depth error either. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_bbq_sauce_and_place_it_in_the_basket/fix_code.py`
— `descend_to`, `tcp`, `grasp_bottle`; 2026-09-14.

#### On a pinch, the sub-floor drift *flicks the payload* — and the contact signature is the pads SPREADING

For a **radial wall pinch** the failure is worse than a lateral miss: the fingers are already on the
object when the solver swaps branch. The tool stops descending, the fingers sweep sideways, and the
payload is flicked off the wall — measured on seed 63 as the aperture jumping
**0.0578 → 0.1088 with ZERO z change** and the bowl landing 36 mm off. The seeds this hit were the two
*best* placements of the sweep once the sub-floor command was removed.

**The joint-line bypass drifts too, only slower — so bypass the last *millimetres*, not the descent.**
Substituting `solve_ik([cx, cy, IK_MIN_Z])` and walking along the line between two solved poses does
dodge the fallback-orientation swap above, but it is not drift-free: measured on
`libero_goal_task/put_the_wine_bottle_on_the_rack` the joint line walks **~2 mm laterally per 13 mm of
dive**. On a 1.8 cm slab that is enough to shove the payload — seed 52's slab travelled ~10 cm sideways
and the following close read air. The working split is therefore: **ride the accurate `goto_pose` path
down to the clamp, and bypass the clamp with the joint line only for the last few millimetres** — the
drift scales with the distance travelled along the line, so a short residual is a small error. Source:
`outputs/libero_fix_loop/libero_goal_task/put_the_wine_bottle_on_the_rack/fix_code.py` — block 0
`pinch()`; `sweep4_seed_53.log` (tip 0.0024, close 0.7325) vs `v2b_seed_52.log`; 2026-09-17.

Never chase the surface with a wall pinch — the pads ride up the bowl's widening wall and push it
sideways even when they do descend. **Release from a controlled clearance above the measured floor**
instead:

```python
z_air = plate_top + max(hang, 0.055) + 0.020      # tcp z ~= 0.091 here, 15-19 mm above the floor
hop_to(col_x, col_y, z_air, q, step=0.07, eps=0.006, budget=14)
open_gripper()
```

with the floor at that column being TCP z ≈ 0.072–0.076.

**Write the over-descent guard with the right sign.** A pinch's contact signature is the fingers being
pushed **apart**, so the aperture *increases*:

```python
if gg - g_ref > 0.010:      # spread = riding up the widening wall
    print("    over-descent warning: grip %.4f -> %.4f" % (g_ref, gg), flush=True)
```

A guard written as `if g_ref - gg > thresh:` (aperture closing) **can never fire on this grasp type** —
the pre-fix guard was written that way and was dead code. This is why the sign belongs next to the
grasp type, not in a generic helper. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_cabinet_and_place_it_on_the_plate/fix_code.py`
— `run` lines 387–401, `grip_norm` 65–68; 2026-09-16.

**Confirmed on a third flat slab, where the floor landed within 2 mm of the first.** On
`libero_object_swap/pick_up_the_cream_cheese_and_place_it_in_the_basket` (a 7.8 × 4.0 × 1.8 cm slab)
the measured floor at that `xy` was **0.117** against the butter slab's 0.115 — so on two different
tasks in the same suite, at different locations, the press-to-the-clamp recipe pinched on **grasp
attempt 0** every time with a gap matching the object's short side (0.0420–0.0422 m on 15/15 seeds).
`solve_ik` never raised once. The floor reading is *repeatable enough to predict but not to hardcode*:
use `HAND_FLOOR = IK_MIN_Z + Z_CMD_REP_OFFSET` as the command and let the no-progress break find the
real stop. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_cream_cheese_and_place_it_in_the_basket/fix_code.py`
— `descend`, `main`; 2026-09-14.

**Third confirmation, on a *neck* pinch where the floor sits just below the object's top.** On
`libero_object_swap/pick_up_the_ketchup_and_place_it_in_the_basket` the floor is at TCP z **0.121**
(reproducible to the millimetre on 15/15 seeds, logged as `floor at cmd 0.102 meas 0.121`) and the
bottle's top is at 0.148 — so the reachable band is only ~2.7 cm deep and the pinch lands on the
**cap/neck**, not the body, reading `gap 0.033–0.035 m`, identical on all 15 seeds. Two useful
additions to the pattern:

- When the reachable band is this thin, the deep descent is *doing identity work too*: the accepted
  grasp height (`z ≤ zhi + 0.005`) is what tells you the fingers are on the object at all.
- **The first yaw candidate sufficed every time** — a neck pinch is narrow, so no yaw sweep is needed;
  the sweep is for objects whose cross-section is wide in one direction (see the short-axis yaw
  pattern). Spending attempts sweeping yaw on a bottle neck is wasted budget.

Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_ketchup_and_place_it_in_the_basket/fix_code.py`
— `grasp_bottle`, `descend_to`; 2026-09-14.

**Fourth confirmation, on a carton body where the shortfall was 2.8 cm.** On
`libero_object_swap/pick_up_the_milk_and_place_it_in_the_basket` the pinch was commanded to
`bot + 0.55 · h = 0.077` on a brick whose top is at 0.137–0.138, and the arm stopped at a measured pad
z of **0.105–0.107** on every one of 15 seeds — `move_to_joints` reporting success, nothing raising.
At this `xy` (`(0.66, −0.10)`) the floor is therefore **~0.106**, a third distinct value in the same
suite (bbq sauce 0.115 / 0.074, cream cheese 0.117, ketchup 0.121). The relative gate
`meas > top − 0.020` → reject was what made this run: measured 0.105–0.107 against top 0.137–0.138 is
0.031 m below the top, **1 cm of margin on the gate**, and the grasp was accepted on the **first**
candidate (yaw 0, frac 0.55) on 15/15 seeds with gap 0.0530–0.0533 (0.3 mm spread). A gate written
against the *command* (`|meas − 0.077| < tol`) would have rejected the correct grasp on **15/15**.

The ladder matters here too: the frac list `(0.55, 0.40, 0.70)` was never exercised past its first
entry, because the *relative* gate — not the fraction — is what decides. Keep the ladder as insurance
against a floor that rises above the object's top; do not expect it to fire on a healthy scene. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_milk_and_place_it_in_the_basket/fix_code.py`
— `grasp`, `find_cartons`; 2026-09-14.

**Fifth confirmation, and the cleanest separation yet between the floor's *value* and its *pattern*.** On
`libero_object_swap/pick_up_the_orange_juice_and_place_it_in_the_basket` the pinch was commanded to
`bot + 0.55 · h = 0.079` and the arm stopped at a measured pad z of **0.099** (spread **0 mm** across 15
seeds) at `(0.463, 0.059)` — the fifth distinct value this suite has produced (bbq sauce 0.115 / 0.074,
cream cheese 0.117, ketchup 0.121, milk ~0.106). What is new is the *margin analysis* on the relative
gate: the carton's top is 0.139, so the gate `meas > top + 0.005` → reject leaves the accepted value
**4.0 cm** clear of the threshold. That is the point of the pattern — the floor moves by centimetres
between tasks, but the *distance from the object's top to the gate* stays large, because it is set by the
object's height rather than by the arm. A gate on the commanded 0.079 would again have rejected the
correct grasp on 15/15.

**A consequence for the foot of the gripper-gap window.** `AIR_GAP` (the lower bound of the accept
window) must be no larger than the *narrowest* grasp any fallback candidate could legitimately produce,
because the yaw sweep changes which face the fingers close across. On this task the primary pinch closes
across the carton's **y**-extent (0.050 m → gap 0.053) but the `yaw = 90` fallback would close across its
**x**-extent of 0.027 m, so the milk sibling's `AIR_GAP = 0.030` would have *rejected a valid fallback
grasp*. Size the lower bound from the smallest face the sweep may present, not from the primary face.
Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_orange_juice_and_place_it_in_the_basket/fix_code.py`
— `grasp` (relative gate, gap window), `orange_frac`; 2026-09-14.

**Sixth confirmation, on a `_task` suite — and the first where the *closure policy*, not the floor, was
the bug.** On `libero_object_task/pick_up_the_alphabet_soup_and_place_it_in_the_basket` the goal object is
a flat 8.1 × 4.7 × **1.8 cm** slab, thinner than the finger pads. The pre-fix ladder closed on **every**
descent rung; on 12 of 15 seeds an intermediate rung was as deep as the loop got, so the fingertips came
to rest **on the slab's top face**, the close caught air, and the reading was a fully-closed gripper —
`width 0.015–0.017` — with the achieved eef z plateaued at **0.1338–0.1345**. The three seeds that passed
had happened to reach deeper on that same first rung (`width 0.526–0.528`): a servo/branch coin flip, not
a strategy. Two rules generalize:

- **Never close on a rung.** Close once, at the deepest z `solve_ik` accepted. The ladder's job is to
  *find* the floor, not to offer a series of grasp attempts — a rung close turns every near-miss into a
  plausible-looking air grasp, and **the aperture is the only signal that separates them here**: on an
  object 1.8 cm tall, "fingers at the sides" (z 0.116) and "fingers on top" (z 0.134) differ by less than
  the object's own height, so no absolute or object-relative height gate is sharp enough.
- **The commanded z is the lever, so command past the floor.** This arm settles ~0.11 m above the
  command, so *reachable* z — not the stall test — is what sets fingertip height. Walking monotonically
  in 0.02 m steps to `FLOOR = 0.005` put the fingertips at the slab's sides at **measured eef z
  0.1163–0.1168 on every seed**, and the first pinch of every seed read `width 0.51–0.55`, ≈ the slab's
  4.2 cm short side.

15/15 development seeds after the change (baseline 3/15); flipped 51, 52, 53, 54, 56, 58, 60, 61, 62, 63,
64, 65. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_alphabet_soup_and_place_it_in_the_basket/fix_code.py`
— `pinch` lines 151–171 (the `while z > FLOOR` ladder is 159–166, the single `close_gripper()` at 167);
2026-09-16. The same program derives its pinch azimuth from the object's OBB ([grasp.md](grasp.md), "Derive
the Closing Yaw From the Object's Own Cloud") and releases at the basket's rim-band midpoint
([localize.md](localize.md), "Take a Container's Mouth Centre From Its Top Rim").

---

## Gate a Closed Gripper on Aperture AND Finger Height

**Trigger**: verifying a grasp from the normalized aperture alone. The aperture cannot distinguish
"closed on the object" from "closed just above it", so a descent that stalled too high is scored as a
success.

```python
close_gripper()
ap = float(ee_pose()[7])
if ap <= 0.05:                      # air
    return None
lift_err = move_tcp([bx, by, meas + 0.06], quat, tol=0.030, retries=0)
ap2 = float(ee_pose()[7])
if ap2 <= 0.05:                     # slipped
    return None
```

Combine with the height gate inside the descent loop (`if meas > top_z - 0.005: return None`, above)
so a stall above the object is rejected before the fingers even close.

**Calibration for this Franka/gripper** — normalized aperture ≈ **0.99 open**, ≈ **0.015 closed on
air**, 0.18–0.32 closed on a bottle neck.

**Why it works + evidence**: seed 51 at Stage 0 logged `gripper_width = 0.0149` (air) after a
commanded grasp and scored reward 0. Every v2 seed reports `aperture 0.18x` and
`lift check aperture 0.18x` at the moment of acceptance. Source:
`.../put_the_wine_bottle_on_top_of_the_cabinet/fix_code.py` — `grasp`, lines 236–269; 2026-09-14.

### The aperture is trustworthy for hold-vs-air — which is a *different* question from how deep you are

The trigger above and the rule below are both true, and the boundary between them is worth stating
because a program that confuses them either over-gates or under-gates:

- **When the failure is a reach/aim failure, the aperture decides alone and is unambiguous.** On
  `libero_object_task/pick_up_the_chocolate_pudding_and_place_it_in_the_basket` the populations are
  cleanly separated — air closes read **0.0146–0.0149** (gap 1.2 mm), real holds **0.33–0.48** (gap
  26–38 mm), open **0.999** — and no height corroboration was needed. Gate on a two-sided window
  (`HOLD_MIN = 0.20`, `HOLD_MAX = 0.95`; above `HOLD_MAX` the pads never touched anything), then
  re-check retention after the lift with `w2 < HOLD_MIN and w2 < 0.45 * w → slipped`. All 15 dev seeds
  logged candidate 0 air **0.0148** → candidate 1 hold **0.457–0.479**, lift retention 0.447–0.492.
- **The aperture says nothing about *where* the hold is.** That is what the height gate in the
  previous section is for, and it is not redundant: two attempts with *identical* estimated pad
  positions (0.752) produced one hold and one air close, and a hold at pads (0.760, 0.095) versus an
  air close at (0.755, 0.109) differ by 5 mm — inside the estimator's own error. So the *pad estimate*
  cannot replace the aperture, and the aperture cannot replace the height gate.

**Search framing — when success is uncertain, spend the attempt budget as a search, not as an analytic
prediction.** Because the gate is one clean bit, the honest program is a small pose ladder plus a
one-bit test per rung, rather than an attempt to compute the right pose. Six candidates ≈ 360 sim
steps, comfortably inside the ~999-step horizon even though each `open_gripper`/`close_gripper` pair
costs 30 steps. The ladder here is `TILT_LADDER` (see "Reach Past a Kinematic Wall…" above), with the
error direction for the next rung taken from the *previous* attempt's measured pad miss — so the
search is steered, not blind. Source:
`outputs/working_codes/libero_object_task_pick_up_the_chocolate_pudding_and_place_it_in_the_basket_fix.py`
— `attempt_pinch`, lines 224–258; 2026-09-16.

#### …but the aperture is not the whole test when the payload's *mask* disappears on the grasp

**Trigger**: after a top-down pinch of an object thinner than the pads, the payload mask that localized
it before the grasp is not weak — it is **absent**. A mask-only hold check then reads "air" on a perfectly
good grasp and skips the entire transport, which is a *silent* failure because nothing crashes and the
reward simply arrives at 0.

The pads occlude the very object they are holding, and the smaller the object the more completely they
do it. On `libero_goal_task/put_the_wine_bottle_on_the_rack` — an 8.3 × 4.6 × 1.8 cm slab — the held
payload produced **no mask at all on 8 of 12 successful-grasp development runs**, *including on runs that
scored 1.000*. So the mask is not a slightly degraded signal to be thresholded down; for this object class
it is simply unavailable while the hold is real.

Three signals, checked strongest first, and the third is the one that saves the run:

```python
now = payload_now(noun, relaxed=True)          # (a) relaxed mask near the hand: min_n=100, min_score=0.03
if now is not None:
    return float(now["zlo"] - zbot), now
tab = find_payload(rgb, d, K, E, noun, on_table=True)
if tab is not None:                            # (b) found back on the table -> the grip slipped
    return float(tab["zlo"] - zbot), tab
if float(eef()[7]) >= 0.12:                    # (c) no mask of it anywhere on the table, jaws loaded
    return 9.0, None                           #     -> the hold is INFERRED, not observed
return -9.0, None
```

Branch (c) is the inference: an object that is *not* on the table and *is* between loaded jaws is being
carried, whether or not a segmenter can see it. Note the asymmetry that makes it safe — the check is
one-sided per branch. Branch (b) can only report a slip (it requires a *positive* detection on the
table), and branch (c) is only reached when (b) failed, so a missing mask can never be mistaken for a
slip.

**Evidence**: `hold inferred` printed in `sweep4_seed_{51,53,55,58,59,60,62,64}.log` — **four of those
(51, 53, 55, 59) still scored 1.000**, i.e. the branch fires on successful runs and is not a
consolation prize for failures. The regression it repairs is measured: a strict mask-only check made
seeds 52–53 skip the transport entirely (v2a, 0/15 on those seeds). The payload's own close populations
on this object put a partial corner capture at **0.4773** against **0.52–0.84** for full pinches, so a
single ceiling cannot separate them either — see the corner-bite section above for the same hazard
measured on a different slab.

**Executed source**: `libero_goal_task/put_the_wine_bottle_on_the_rack` `fix_code.py` — `hold_rise()`,
lines 293–313; 2026-09-17. Instance:
`knowledge/skill-code-instances/grasp/infer-a-hold-from-the-jaws-when-the-pinched-payload-has-no-mask.yaml`.

---

## Verify a Grasp by the Object Rising, Not by Gripper Width

**Trigger**: any grasp you are not sure about. `gripper_width` alone is ambiguous — a thin-shelled
object reads a very small width even when correctly pinched.

```python
def bowl_state(obs):          # generic: "object_state"
    rgb, di, K, E = view(obs)
    b = localize(rgb, di, K, E, OBJECT_PROMPTS)
    if b is None:
        return None
    pts = b["pts"]
    return {"pts": pts, "xy": pts[:, :2].mean(axis=0),
            "rim_z": float(np.percentile(pts[:, 2], 97)),
            "zmax": float(pts[:, 2].max()), "info": b}

# after close_gripper, LIFT before re-observing (a pre-lift look merges the gripper with the
# object and can show a falsely raised zmax)
goto_pose(np.array([tcp[0], tcp[1], tcp[2] + 0.16]), q)
st2 = bowl_state(get_observation())
if st2 is not None and st2["zmax"] > base_zmax + 0.04:
    ...  # carried
```

**Why it works + evidence**: on seed 51 the initial program read `gripper_width=0.0134` and a merged
pre-lift `zmax` of 0.095 that looked "lifted"; the post-lift `zmax` of 0.040 correctly exposed the
air grasp (the object never left the table). This check then drove the direction sweep on every
retried seed. Source: `.../put_the_bowl_on_top_of_the_cabinet/fix_code.py` — `bowl_state` (a
module-level symbol) plus the confirmation block in `main()`; 2026-09-14.

**Note**: do NOT wrap a retry loop around a *post-hoc* geometric self-check at the end of the
episode. Re-segmenting the object from the final frame returns `zmin` below the support on 12 of 15
seeds whose reward was nevertheless 1.000 (the final mask merges the object with its reflection).
Emit that readout for debugging only; never gate control on it.

**IK guard** — always check `if joints is not None` before `move_to_joints`.

**TCP offset for placement**: `goto_pose(pos, quat)` moves the **WRIST** to `pos`; fingertips extend below the wrist. Calibrate per robot/gripper config and adjust placement Z accordingly.

**Top-level call** — if you define a `run()` function, call it at the end:
```python
def run():
    ...
run()
```

**Gripper width thresholds** — add validated per-object thresholds here as you discover them:

| Object | Good grasp (gw >) | Air grasp (gw <) | Notes |
|---|---|---|---|
| patterned metal bowl (wide/shallow, r≈0.03 at grasp height) | 0.071–0.097 | ≤0.015 | Rim-snapped radial pinch; see "Rim-Snapped Grasp" above. Threshold alone is not a verifier — re-observe the object after lifting. |
| wine bottle (neck grasp, TCP z ≈ 0.120) | 0.18–0.32 | ≤0.05 | Gripper normalized scale: ≈0.99 open, ≈0.015 closed on air. Aperture alone is not a verifier — also require the fingers to be *below the object's top* (see "Gate a Closed Gripper" above). |
| metal bowl, wedge grip inside the cavity (`_gap` × 0.08) | 0.0033–0.0185 m | ≤0.0010 m | **Blocked** grips read 0.0211–0.0349 m and hold nothing — check an upper bound too, and re-measure after a lift. See "Verify a Grasp by the Measured Gripper Gap" above. |
| stove control, top-down pinch of the raised band (`_gap` × 0.08) | 0.0243 m after the pinch, 0.0171 m after the sweep | ≤0.0040 m | The gap must be read *after* the pinch and *after* the sweep: a full-contact pinch reads 0.0243 m, matching the band's measured 2.4 cm cross-dimension. ≤0.0040 m means closed on air, so retreat and retry at another height rather than sweeping. See "Rotate an Articulated Control In Place" in [manipulation.md](manipulation.md). |
| butter box, flat slab pinched at the IK z clamp (`_gap` × 0.08) | 0.0389–0.0390 m after close **and** after lift | ≤0.0060 m shipped gate; air ≈ 0.001 m | 7.5 × 3.9 × 1.6 cm slab pressed to `HAND_FLOOR = 0.115` so the pads straddle its whole height. Gap is essentially the slab's short side and is stable to 0.1 mm across 15/15 development seeds — a good example of a *tight* window: gate as `AIR_GAP < gap < GRASP_MAX_GAP` (0.006–0.070) rather than a bare lower bound, so a blocked grip cannot pass. See "press to the clamp before closing" above. |
| chocolate pudding box, short-axis pinch at the clamp (`_gap` × 0.08) | 0.0459–0.0461 m | ≤0.0060 m (`AIR_GAP`); shipped band 0.012–0.078 | 8.5 × 5.5 × 3 cm. The gap matches the box's **short** side because the closing axis is derived from the top face (see "close across the SHORT axis" above) — so here the gap doubles as a check that the yaw derivation was right. Empty closed grip reads 0.001–0.005 m. |
| milk carton, body pinch at 55% of height, fixed `yaw = 0` (`_gap` × 0.08) | 0.0530–0.0533 m after close, 0.0529–0.0531 m after lift | `AIR_GAP` 0.030; shipped band 0.030–0.072 | 14.3 × 5.9 × 4.4 cm brick. The gap matches the brick's **y**-width (0.052 m image-measured), which is the axis a `yaw = 0` top-down pinch closes along — see "the measured gap is also a direct read-out of WHICH axis" above. Spread 0.3 mm over 15/15 seeds, and the *lift* gap is within 0.2 mm of the pinch gap, so this closed grip is genuinely on the object and not wedged. Note `GRASP_MAX_GAP = 0.072` here, wider than the brick: an upper bound only rejects a grip that closed on something *larger* than the intended object. |
| orange-juice carton, body pinch at 55% of height, fixed `yaw = 0` (`_gap` × 0.08) | 0.0529–0.0531 m after close | `AIR_GAP` **0.010**; shipped band 0.010–0.072 | 2.7 × 5.0 × 13.4 cm carton. Same y-width and nearly the same gap as the milk brick above (0.052 vs 0.053) — a useful reminder that a gap in this band does **not** identify the object, only that the fingers are on a body of about that width. The lower bound here is deliberately far below the milk sibling's 0.030 so that a `yaw = 90` fallback closing across the carton's 2.7 cm x-extent is still accepted: size the foot of the window from the *narrowest face the sweep may present*, not the primary one. |
| akita black bowl (d≈11 cm), radial wall pinch (raw `robot_cartesian_pos[-1]`) | ≥0.05 raw (≈0.004 m) — accepted on 15/15 seeds at `tries=1` | <0.05 raw | Bowl mouth is wider than the gripper, so the grasp is a **wall pinch**; the same value is re-read after the lift/carry/descent and a reading **wider by >0.03 raw** means the object slipped. See "Verify a Grasp by the Measured Gripper Gap" above. |

---

## Derive the Closing Yaw From the Object's Own Cloud

**Trigger**: a pinch whose validity depends on **which pair of faces** the fingers land on — a lever,
blade, bar, handle, a knob's raised band — where the object's in-plane orientation varies across
seeds. A hard-coded `make_topdown_quat(0)` only works when the object happens to be axis-aligned, so
its success is coincidence rather than derivation.

```python
def closing_yaw(band_xy):
    """Yaw whose finger-closing axis is across the band's narrow dimension."""
    c = band_xy - band_xy.mean(axis=0)
    w, v = np.linalg.eigh(c.T @ c)
    axis = v[:, int(np.argmax(w))]              # long axis of the band
    normal = np.array([-axis[1], axis[0]])
    # this topdown() parameterization closes along (sin yaw, -cos yaw)
    return float(np.degrees(np.arctan2(normal[0], -normal[1])))
```

Take the eigenvector of the **larger** eigenvalue in XY as the object's long axis, use its
perpendicular `n` as the closing-axis normal, then solve `(sin yaw, −cos yaw) = n` for the
parameterization you are using — never substitute an arbitrary perpendicular. Derive it from the
**pinchable band's own cloud**, not the whole object's OBB: a wide base dominates the covariance and
rotates the answer.

**Why it works + evidence**: on `libero_goal_swap/turn_on_the_stove` this returns ≈ −1° on all 15
development seeds (the band's long axis lies along world x, its broad faces facing ±y) and the
subsequent pinch reads a full-contact gap of 0.0243 m, matching the band's measured 2.4 cm
cross-dimension. A fixed `topdown(0)` would have produced the same angle here — but by luck, and
only on a seed whose control happened to be axis-aligned. Source:
`outputs/libero_fix_loop/libero_goal_swap/turn_on_the_stove/fix_code.py` — `closing_yaw`, lines
88:94; 2026-09-14.

**Variant — a rectangle narrower than the gripper in ONE direction only: close across the SHORT axis.**
The same derivation, but the choice of perpendicular is now forced by the gripper rather than by the
object's faces. If the closing axis follows the long side, the fingers must straddle that side — and on
an 8.5 × 5.5 cm box against an ~8 cm opening they cannot. So take the *short* axis, i.e. the
perpendicular to the larger-eigenvalue eigenvector of the **top face's own** cloud:

```python
def closing_yaw_across_short_axis(top_xy):
    """Yaw whose finger-closing axis (sin y, -cos y) follows the top face's SHORT axis."""
    c = top_xy - top_xy.mean(axis=0)
    w, v = np.linalg.eigh(c.T @ c)
    axis = v[:, int(np.argmax(w))]                 # long axis of the top face
    normal = np.array([-axis[1], axis[0]])         # short axis direction
    return float(np.degrees(np.arctan2(normal[0], -normal[1])))
```

Feed it the **top-face** points (see "Take an Object's Centre From Its Visible Top Face" in
[localize.md](localize.md)), not the whole cloud — a front face adds in-plane spread and rotates the
answer. Verify the result against the measured gap: if the fingers really straddle the short side, the
gap after closing should be close to that side's length.

**Why it works + evidence**: on
`libero_object_swap/pick_up_the_chocolate_pudding_and_place_it_in_the_basket` this returns **−1.4 to
−1.6°** on all 15 development seeds (the box's short axis lies along world y) and the measured pinch gap
is 0.0459–0.0461 m, matching the box's ~4.6–5.5 cm short side. Source: same `fix_code.py` —
`closing_yaw_across_short_axis`; 2026-09-14.

**The measured gap is also a direct read-out of WHICH axis the parameterization closed along — the
cleanest confirmation yet.** At a fixed `yaw = 0` the closing axis is `(sin 0, −cos 0) = (0, −1)`, i.e.
world **−y**, so the pinched object's gap must equal its **y**-extent, not its x-extent. On
`libero_object_swap/pick_up_the_milk_and_place_it_in_the_basket` the brick is 14.3 × 5.9 × 4.4 cm and
the measured gap was **0.0530–0.0533 m on 15/15 seeds**, matching the image-measured **y-width 0.052 m**
and *not* the x-extent 0.035 m. This pins the parameterization claimed in the `closing_yaw` comment
(derived on a stove band, then a pudding box) to a **box** body, and it means a shipped fixed-yaw grasp
can be sanity-checked after the fact: **compare `gap()` against both image-measured extents and see
which one it matches.** A mismatch against the axis you assumed is the tell that the yaw derivation (or
the parameterization) is wrong — cheaper than a failed lift. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_milk_and_place_it_in_the_basket/fix_code.py`
— `grasp` (gap read-back), `find_cartons` (image-measured widths); 2026-09-14.

---

## Object Geometry Utilities

```python
# Z range (grasp height tuning)
z_min, z_max = obj_pts[:, 2].min(), obj_pts[:, 2].max()
height = z_max - z_min

# OBB (orientation-aware bounding box)
obb = get_oriented_bounding_box_from_3d_points(obj_pts)
# Keys: "center" (3,), "extent" (3,), "R" (3x3 rotation matrix)
obb_center = obb["center"]
```
