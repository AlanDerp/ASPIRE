---
name: transport
description: Motion patterns for moving objects between locations — multi-step waypoints, safe transit sequences, interpolated Cartesian moves, collision avoidance during transport. Grows through experiment.
---

# Transport — Motion Patterns

> This skill covers **how to move** once an object is grasped: waypointing, safe transit,
> intermediate stops, and collision avoidance. Discovered through experiment — add entries as
> you validate them.

---

## Waypoint Sequences

Add entries here when you find a multi-step motion pattern that prevents collisions, slip, or
IK failures during transport. Include: trigger condition, waypoint sequence, why it works.

| Pattern | Trigger | Sequence | Notes |
|---|---|---|---|

---

## Pre-Probe IK Conditioning

Before grasping, pre-visit the placement target at multiple approach heights. This seeds the
IK solver so it stays on the correct branch when placing after the grasp.

```python
# BEFORE grasping, probe the target at decreasing heights:
for probe_z in [target_z + 0.08, target_z + 0.06, target_z + 0.04, target_z + 0.02]:
    goto_pose(np.array([target_x, target_y, probe_z]), TOP_DOWN_QUAT)
goto_home_joint_position()
# NOW grasp — IK is conditioned for placement
```

**Why it works**: IK solvers maintain local branch continuity from their last configuration.
Visiting the placement target before grasping seeds the solver on the branch that can reach
that XY at low Z — so after grasp + home reset, the arm finds the same branch.

**When to use**: Any task where the placement target is at low Z and has a fixed known XY.

---

## Interpolated Cartesian Motion

Add entries here when fine-grained step-by-step moves outperform direct `goto_pose` (e.g. for
fragile placements, long horizontal transport, or constrained workspaces).

---

## Safe Transit (Lateral Escape Before Lift)

Add entries here when the arm must move laterally before lifting to avoid sweeping through
obstacles (opened drawers, adjacent objects, cabinet edges).

---

## Placement Approach

Add entries here for approach sequences above the target (hover height, descent speed,
drop vs. lower) that prevent bounce, tip, or miss.

### Choose the Placement Surface by Local Flatness, Not by Height or Mask Area

**Trigger**: "put X on top of Y" where the scene also contains a *taller* but non-supporting structure
(a slatted ramp, a sloped shelf, a decorative ledge). A height-max picker or a "largest mask" picker
selects the wrong surface and the object is placed on a slope.

```python
flat = np.zeros((nx, ny), dtype=bool)
for i in range(1, nx - 1):
    for j in range(1, ny - 1):
        z = top[i, j]
        if not np.isfinite(z) or cnt[i, j] < 6:
            continue
        if not (z_lo <= z <= z_hi):
            continue
        if not np.isfinite(top[i - 1:i + 2, j - 1:j + 2]).all():
            continue
        gx = (top[i + 1, j] - top[i - 1, j]) / (2.0 * res)
        gy = (top[i, j + 1] - top[i, j - 1]) / (2.0 * res)
        if abs(gx) <= max_slope and abs(gy) <= max_slope:
            flat[i, j] = True
# ... flood-fill `flat`, keep components >= min_cells, take the highest
# surviving component inside the reach box (xr, yr)
```

Rasterise the top-`z` of a world point cloud with `np.maximum.at`, require a finite 3×3 neighbourhood,
threshold the finite-difference gradients, flood-fill, keep components of at least `min_cells` (18)
cells, then take the highest component whose centroid lies inside the reach box.

**Why it works + evidence**: on `libero_goal_swap/put_the_wine_bottle_on_top_of_the_cabinet` the
cabinet's flat top is `z ≈ 0.213–0.225` over `x ∈ [0.268, 0.520], y ∈ [−0.374, −0.183]`, while a
**slatted ramp** in front (`x ∈ [0.561, 0.828]`) has a *sloped* top rising from `z = 0.238` to
`0.288`. A height-max or mask-area picker lands the bottle on the ramp; the gradient test rejects it
on every seed. All 15 seeds resolved the same target (`z = 0.2158`). Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_wine_bottle_on_top_of_the_cabinet/fix_code.py` —
`find_flat_top`, lines 157–219; 2026-09-14.

### On a Thin Flat Target, Rank by Proximity — Clearance Is Only a Gate

**Trigger**: "put X on Y" where Y is a plate / tray / mat lying flat (mask z-extent of only ~1 cm),
the goal is a plain object-`On` relation with a **tight XY tolerance** (< 3 cm), and the scene
contains clutter. A clearance-ranked search will happily pick the clearest cell, which is not the
goal cell.

```python
need = h_object + 0.04
for dx in np.arange(-tol, tol + 1e-6, 0.01):
    for dy in np.arange(-tol, tol + 1e-6, 0.01):
        gx, gy = pcx + dx, pcy + dy
        m   = np.hypot(cloud[:, 0] - gx, cloud[:, 1] - gy) < r_object   # circular footprint
        col = cloud[m]
        above = col[col[:, 2] > target_top + 0.02]
        clear = 1.0 if len(above) == 0 else float(above[:, 2].min() - target_top)
        score = (clear >= need, -math.hypot(dx, dy))    # proximity is the TIE-BREAKER
# target_top = np.percentile(target_pts[:, 2], 90)   # the TARGET's own mask, not the table height
# tol = min(0.04, max(0.02, r_target - r_object))    # keep candidates inside the target
```

Two things carry the pattern: **clearance is a boolean gate, not a ranking** — once a cell is clear
enough, the only thing that matters is how close it is to the goal region; and the target's surface
height comes from the **target's own mask** (`target_top`), never from the table height. Finds the
candidate set by walking a fine grid around the target centre, then dedupes to ≥2 cm apart.

**Why it works + evidence**: on `libero_goal_swap/put_the_bowl_on_the_plate` all 15 development seeds
select the **plate centre** as the first candidate (the measured clearance of 0.252 m is the robot
arm, not furniture) and all 15 verify 0.013–0.024 m from it. The same code path with a
max-clearance-only ranking, on the sibling task `put_the_bowl_on_the_stove`, picked a cell **5 cm off
the burner and scored 0**. Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_bowl_on_the_plate/fix_code.py` — `choose_places`,
lines 174–202; 2026-09-14.

### On a Sloped Support, Aim at the Downhill Lip and Clamp to a *Measured* Reach

**Trigger**: "put X on Y" where Y's support surface is **not flat but slopes**, and the arm's
reachable set covers only part of it. The near/uphill end of a sloped support can be out of reach
while the far/downhill end is in reach — and a generic criterion (highest band, largest mask, nearest
centroid, `min |xy|`) can select exactly the unreachable part.

```python
def choose_place_xy(pts, x_lo=0.58, x_hi=0.70, inset=0.012):
    z_hi = float(np.percentile(pts[:, 2], 98.0))
    band = pts[pts[:, 2] > z_hi - 0.09]                # the support's top band
    if len(band) < 20:
        band = pts
    y_front = float(np.percentile(band[:, 1], 97.0))    # the downhill lip
    lip = band[band[:, 1] > y_front - 0.03]
    if len(lip) < 5:
        lip = band
    x = float(np.clip(np.median(lip[:, 0]), x_lo, x_hi))   # reachable band
    return x, y_front - inset                           # centre just INSIDE the lip
```

The band isolates the support's top; its extreme value along the slope axis is the downhill lip;
`inset` keeps the object's centre just inside the lip instead of overhanging it. **`x_lo`/`x_hi` must
come from a measured reach probe** — never from `solve_ik`'s willingness to return a solution, since
it returns one for poses the arm cannot hold.

**Why it works + evidence**: on `libero_goal_swap/put_the_wine_bottle_on_the_rack` the rack top runs
from `z = 0.299` at `y = −0.30` down to `z = 0.236` at `y = −0.18` — a slope in `y` only — and a
top-down pose cannot be carried past `y ≈ −0.19`, so the uphill two-thirds of the top is unreachable
and the v1 `min|xy|` pick `(0.561, −0.202)` sat exactly there. Retargeting to the front lip
`(0.700, −0.191)` moved the arm's floor at the place point from **6 cm above the surface to 1 cm
above it**, and all 15 development seeds then released inside that 1 cm. Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_wine_bottle_on_the_rack/fix_code.py` —
`choose_place_xy`, lines 204–228; 2026-09-14.

### Set the Release Height From the Support's Own Surface AND the Grasp Offset

**Trigger**: releasing a held object onto a support whose height you measured with perception. The
release height needs **two measured terms**, and it must never be commanded below what the arm can
reach.

```python
z_surf = find_surface_at(px, py)                 # measured AT the place point, not averaged
if z_surf is None:
    z_surf = float(np.percentile(support_pts[:, 2], 90))
z_lo = z_surf + above + 0.005                    # above = TCP_z - object_base, measured AT GRASP
lower_onto(px, py, z_lo)                         # stops at the arm's floor, whatever that is
open_gripper()
```

`above` is measured at the moment of the grasp (`got - det["base"]`) and **never assumed** — it is
the only way to know where the object's base sits relative to the TCP. The descent then releases at
whichever is higher: the ideal height or the floor.

**Refinement — capture the term at the pinch, *before* any lift, or the lift is silently folded into it.**
The mirror-image form of this term is the object's *hang* — how far its underside sits below the
fingertip — and it is captured with the same discipline: read the hand z while the fingers are still at
the pinch.

```python
        close_gripper()
        g = grip_gap()
        hand_grasp = float(tcp()[2])        # <-- capture BEFORE any lift_to(...)
        ...
    hand_at_grasp = hand_grasp
    hang = (hand_at_grasp - FINGERTIP_OFFSET) - float(box["bot"])
```

If the capture is taken *after* the lift instead, the entire carry height is added to the hang and the
release pose can land **above** the carry height — where the descent silently does nothing and the
object is released wherever the lateral move left the arm. Nothing in the trace reports an error, and a
lucky seed can still score 1.0. Print `hand`, `fingertip`, `object bottom` and `hang` on one line and
read them: a correct hang for an object pinched at the table is ≈ 0.

**Why it works + evidence**: on `libero_object_swap/pick_up_the_butter_and_place_it_in_the_basket` the
Stage-0 smoke run read the hand **after** the lift and got `hang = 0.221` — a 22 cm error — which
computed a release pose at hand z 0.498, *above* the 0.34 carry height, so `descend` did nothing and the
box was released in mid-air; seed 51 still scored 1.0 by luck. With the capture moved before the lift,
all 15 development seeds report `hang = −0.003 … −0.000` and release at hand z 0.215–0.219. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_butter_and_place_it_in_the_basket/fix_code.py`
— `main`; 2026-09-14.

**Why it works + evidence**: on `libero_goal_swap/put_the_wine_bottle_on_the_rack` all 15 development
seeds log `rack surface at place point z=0.242–0.243; releasing at 0.373–0.375` then
`place floor at cmd 0.374 meas 0.385`, and the post-release detection finds the bottle with base
`0.236–0.243` against that surface — within 1–6 mm on every seed.

**The success predicate wants the object resting *on* the support, not standing on it.** Seed 61
scored 1.0 with the bottle **lying** on the rack (`base 0.236 top 0.284`, height 0.048) rather than
upright. Do not add a post-hoc "is it upright?" check to a goal whose predicate does not contain one —
it would reject valid states. Source: same `fix_code.py` — `run`, lines 287–345; 2026-09-14.

**When the offset does not reproduce, this recipe is the wrong shape — do not tune the constant.**
The two measured terms above are only valid while the hang is stable across the carry. A wall pinch
on a wide object makes it unstable (sign flip, and it keeps changing *during* the descent), so no
value of `offset` works: switch to the closed loop on the payload's own base —
"Close the *placement* loop on the payload's own measured base" below. The tell is a payload that
arrives perfectly centred on its own cloud and lands centimetres off.

### Derive Transit Height From the TARGET SURFACE, Never From the Grasp Height

**Trigger**: placing an object **on top of** a tall support (cabinet, rack, shelf, stove). If the
lateral move is done at a fixed offset above the *grasp* point, the hanging object sweeps through the
support's front/side and is knocked off. Symptom: the grasp verifies fine, the final approach
completes without error, but the object ends up on the table leaning against the support instead of
on top of it — and the failure looks chaotically sensitive to grasp yaw.

```python
# offset = how far the object's underside sits below the fingertip target (measured at grasp)
offset = float(st_pts[:, 2].min()) - tcp[2]      # e.g. -0.036
transit_z = z_top + 0.09 - offset                # object underside 9 cm above the surface
place_z   = z_top + 0.012 - offset               # set down with a 12 mm gap

cur = wrist(obs2)[:3]                            # raise straight up first, then translate
if cur[2] < transit_z:
    goto_pose(np.array([cur[0], cur[1], transit_z + 0.1]), quat)
else:
    goto_pose(np.array([cur[0], cur[1], cur[2] + 0.06]), quat)
goto_pose(np.array([tx, ty, transit_z]), quat)   # lateral move ABOVE the support
goto_pose(np.array([tx, ty, place_z]), quat)     # vertical descent onto the surface
open_gripper()
for _ in range(3):
    get_observation()                            # let physics settle before retreating
goto_pose(np.array([tx, ty, transit_z]), quat)   # retreat straight up
```

**Why it works + evidence**: on `libero_goal_swap/put_the_bowl_on_top_of_the_cabinet` the initial
program used a fixed `grasp_tcp_z + 0.16`, putting the carried bowl's underside at ~0.149 m while the
cabinet top is at 0.215 m — so the bowl swept ~0.06 m *below* the cabinet top and clipped the sloped
shelves. Two otherwise byte-identical controllers differing only in grasp yaw (~4.5°) scored 15/15 vs
7/15, reproducibly. Deriving both heights from the measured surface removed the collision and the yaw
sensitivity entirely: the final program succeeds from grasp directions spanning 50 to −62°. Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_bowl_on_top_of_the_cabinet/fix_code.py` lines
126–214; 2026-09-14. Requires the target surface height first — see "Flat-Surface Localization by
Densest Upper Z-Plateau" in [localize.md](localize.md).

### Compensate the Release Pose for an Off-Centre Grasp

**Trigger**: the object was grasped off-centre — a wall pinch, a rim pinch, any grasp where the tool
centre point is *not* the object's centre. The object then hangs a fixed offset from the TCP, and
releasing with the TCP over the target puts the **object** off by that offset. On a tight goal test
(±4 cm) this is the whole difference between reward 0 and reward 1.

```python
# offset from the observation taken BEFORE the pinch - see localize.md: a mask of the
# object while it is held is contaminated by the gripper and under-reads the offset
off = np.clip(np.array([bx - tcp[0], by - tcp[1]]), -0.08, 0.08)
tcp_to_bottom = float(gz - object_z_lo)      # where the object's underside sits vs the TCP
# SIGN IS SCENE-SPECIFIC — measure it, never inherit it (see "the SIGN is not a constant" below):
#   object hangs on the PINCH side    -> place + off   <- radial wall pinch
#   object hangs OPPOSITE the pinch   -> place - off   <- goal-swap bowl-on-stove
release_xy = np.array([place[0] - off[0], place[1] - off[1]])   # <- bowl-on-stove's sign

cur = tcp_xy()
for f in (0.0, 0.33, 0.66, 1.0):             # waypoints at one carry height, quat unchanged
    goto_pose(np.array([cur[0] + f * (release_xy[0] - cur[0]),
                        cur[1] + f * (release_xy[1] - cur[1]), CARRY_Z]), quat)
goto_pose(np.array([release_xy[0], release_xy[1], place_z]), quat)
open_gripper()
```

The offset is *only* valid for the grasp it was measured from — re-measure it on every attempt,
before that attempt's pinch.

**A tilted grasp makes the offset *rotation-dependent*, so it cannot be a constant at all.** On
`libero_object_task/pick_up_the_chocolate_pudding_and_place_it_in_the_basket` the pinch is deliberately
tipped 15–32° to clear a reach wall (see "Reach Past a Kinematic Wall by Tipping the Wrist" in
[grasp.md](grasp.md)), and a tilted tool puts the pads off the reported frame **in xy as well as in z**:
the pad-to-command offset is `R @ [0, 0, PAD_FROM_EEF]`, whose horizontal part `PAD_FROM_EEF * Rz_xy`
grows with the tilt. Recomputing the release xy from the **held** orientation on every release — rather
than reusing an offset measured at a top-down pinch — is what keeps the object inside a 0.15 m mouth.
The rule generalizes: whenever the grasp orientation is not constant across attempts, the compensation
must be recomputed per attempt from that attempt's own quaternion, not carried as a number.

**Re-localizing the container *after* the lift is sometimes right — and the rule above says not to.**
The two are not in conflict; the difference is what the mask can see. On the `_swap` alphabet-soup task
the carried can dragged the *basket's* mask centroid 8.7 cm, so the pre-grasp xy was kept. On this task
the basket is re-observed and re-localized **after** the lift and reads cleanly: the held bottle does not
enter the basket's mask from the scene camera, and pickup (x ≈ 0.763) and basket (x ≈ 0.60) are far
apart in frame. So re-localize after the lift **only** when the carried object provably cannot enter the
container's mask — and decide that from a mask you have actually looked at, not from the rule's name.
Both readings scored 15/15 development seeds; this one also scored **50/50 held-out**. Source:
`outputs/working_codes/libero_object_task_pick_up_the_chocolate_pudding_and_place_it_in_the_basket_fix.py`
— `place_in_basket`, lines 278–298; 2026-09-16.

**Use the pinch-time geometry for the offset's DIRECTION, and split it from its magnitude.** The two
halves of `off` have different best sources, and mixing them up costs ~2× the object's radius:

| term | best source | why |
|---|---|---|
| **direction** (which side of the tool the payload hangs on) | the **pinch-time** geometry | the in-air SAM3 mask is *clipped by the fingers*, so its centroid azimuth is good only to ±30° |
| **magnitude** (how far off-axis) | re-measured **in the air** after the lift | the payload slips deeper between the pads during the lift, so a pinch-time estimate is stale |

For a wall pinch the payload hangs on the wall that was pinched, i.e. the unit vector from tool to
payload is the direction from the pinch point to the bowl centre: `u = normalize(bowl_centre - tool_xy)`,
`off = R_out * u`. Reversing that vector puts the release column ~2·R across the target — measured
**|err| 0.105 m with the sign flipped vs 0.021 m with it right**, and both flipped seeds went to
reward 1.0. (If the pinched wall is the one *away* from the goal, the payload conveniently hangs
goal-side; see `grasp.md` "pinch the wall away from the goal".)

**A residual constant bias is a margin, not a fix — do not dress it up as one.** After the loop closes,
what is left is a small seed-independent landing residual. Commanding the column pre-shifted by
`-bias` (`LAND_BIAS = (+0.009, +0.013)` m, σ ≈ 0.002 over 12 clean dev seeds) halves the mean in-program
error (0.0217 → 0.0120 m) but changes **no** pass/fail outcome: the A/B sweep with `LAND_BIAS = 0` is
also 15/15. Keep it only if it is measured, label it as a margin, and never let it stand in for the
closed loop — a constant cannot fix a *varying* offset (see "Close the *placement* loop on the payload's
own measured base" below). Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_cabinet_and_place_it_on_the_plate/fix_code.py`
— `run` lines 355–374, `air_bowl` 167–198, `hop_to` 224–262; 2026-09-16.

**…but on an OPEN placement loop the same constant is the fix, not a margin.** Whether a residual bias
is fatal or cosmetic is decided by one thing: whether anything downstream *measures* the payload after
the command. Where the loop closes on the payload's own base (the task above), a constant only shrinks
the residual and changes no outcome; where the placement is commanded open-loop, the constant is the
*only* term acting on the offset and the same magnitude decides pass/fail. On
`pick_up_the_black_bowl_on_the_ramekin_and_place_it_on_the_plate` all 15 dev seeds landed at a mean
**(+0.012, −0.019) m** offset with the same sign on every one (x `+0.001…+0.024`, y `−0.007…−0.038`),
against a ~1 cm tolerance (plate rim 0.065 m vs bowl rim 0.054 m — see [localize.md](localize.md), *"Fit
a circular object's rim"*), so a 2 cm biased landing perched the bowl on the rim instead of nesting it:

```python
AIM_BIAS = np.array([-0.012, 0.019])       # = -(measured mean landing offset)
place_xy = goal_xy + AIM_BIAS             # the servo target AND the descent's lateral term
# the grasp's wall ordering still uses the UN-biased goal_xy
```

Landed distance went from a 2.3 cm mean to a 5 mm median and the dev result from **3/15 to 15/15**
(14/15 on a byte-identical repeat sweep; **29/30 combined**). So the rule is not "a constant fixes
nothing" — it is **check the sign first**: same sign on every seed plus an open loop means the offset is
a *bias* and the constant is the fix; a varying sign means it is noise and only a closed loop removes
it. Never apply a constant you have not measured, and say which of the two cases you are in. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_on_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— `AIM_BIAS` lines 400–407, consumed by the servo at 406–442; 2026-09-16.

**…and take the re-measurement in FREE SPACE, after the lift.** The rule above says *when* to
measure. This says **where**, and it matters when the object is grasped inside an enclosure — a
drawer, a bin, a cabinet — because the wall occludes the far side of the grasp axis and the near rim
contributes points. The pinch-time offset is then biased, and its **sign can flip** once the object is
clear:

```
seed 53:  offset at pinch = [-0.039, 0.000]      offset after lift = [+0.039, 0.006]     # 7.8 cm swing
```

Take a fresh observation after the lift and prefer it, falling back to the pinch-time value only if
that measurement fails:

```python
if held > AIR_GAP:                       # gripper gap proves the object is held
    pinch_off = bowl["c"] - np.array([tcp_xy[0], tcp_xy[1]])
    cd = bowl_near(t[:2])                # FRESH observation, free space, no gate
    lift_off = None if cd is None else cd["c"] - t[:2]
    offset = lift_off if lift_off is not None else pinch_off
```

Note the free-space call deliberately uses the **ungated** path — the physical-depth gate described in
[localize.md](localize.md) applies only while the object is known to be clamped, and using it here
regresses (measured: seed 52's offset moved from `[0.039,0.006]` to `[-0.008,0.024]`, wedging the
descent at x = 0.728). **Evidence**: using the lift value flipped seeds 53, 54, 57, 59, 60
(6/15 → 9/15); seed 53 reads `offset_used=[0.039,0.006] rel_xy=(0.696,0.012) verify dist=0.026 ok=True`,
against a pinch-time value that sent the transit 7.8 cm to the −x of the plate. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_cabinet_and_place_it_on_the_plate/fix_code.py`
— `profile` lines 197–209, consumed at `carry_and_place` line 258; 2026-09-15.

**Why it works + evidence**: on `libero_goal_swap/put_the_bowl_on_the_stove` the bowl is held by a
radial wall pinch, so its centre hangs ≈ one radius (~5 cm) from the TCP; a bowl 5.1 cm from the
burner scores 0 and 2.5 cm scores 1.0. Taking the offset from the *carried* mask measured
`(-0.016,+0.018)` where the truth was `(-0.049,+0.000)`, which drove the descent column ~4 cm
sideways into a stack of leaning planks (bowl released in mid-air, seeds 59/61 → reward 0). The
pre-pinch offset lands 0.2–1.5 cm from the intended place and those seeds score 1.0. Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_bowl_on_the_stove/fix_code.py` — `attempt()`,
lines 316–343; 2026-09-14.

**The SIGN is not a constant — measure it before trusting it.** `off` is a displacement of the
*object* from the *TCP*, so its sign follows which side of the object the pinch sat on. The
bowl-on-stove case above hangs the bowl **opposite** the pinch (`place - off`); the radial wall
pinch on
`libero_spatial_swap/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate` hangs it
on the **same** side (`place + off`). Reusing `place - off` there released the bowl 5 cm past the
plate's +x edge (plate edge 0.783; release commanded 0.772, object landed 0.777) and it slid off —
and the failure *presents* as "the bowl rolled off the plate", not as an offset bug, so it is easy
to misdiagnose as release height or plate-centre error. Measuring it took one deliberate release
onto a clear patch of table: pinch TCP x=0.707 on a bowl centred at 0.659, released at TCP x=0.659,
the bowl came to rest at x=0.700 — a carried offset of **+0.041 m ≈ +Rw, same sign as the pinch**.
Flipping to `place + off` took seed 51 from 0.0 to 1.0, and seeds 51–65 then all landed 0.002–0.007 m
from the commanded point. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate/fix_code.py`
— `attempt()`, lines 385–404; 2026-09-15.

**…but do not express that as "which sign for which grasp type" — that framing *is* the bug.** The
sign is scene-specific only because `off` was built with two different conventions in two different
code paths. Fix the convention once and the branch disappears:

```
off  ==  payload_centre − tcp        (a MEASURED vector; its sign is part of the measurement)
release_xy  ==  place − off          (ALWAYS; no per-grasp-type sign anywhere)
```

Because `payload_centre = tcp + off`, commanding `tcp = place − off` puts the payload where you want
it *whichever side of the object the pinch sat on*. The scene-specific `+`/`−` above is then an
artifact of storing the offset in the hand frame in one branch and the world frame in another.

Measured cost of getting this wrong on
`libero_spatial_task/pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate`: the
fallback branch negated the stored offset and *then* subtracted, computing `place + off` where the
measured branch computed `place − off`. Release column 0.774 against a plate centre of 0.712 — the
payload landed **2·|off| = 12.4 cm** past the target, perched on the plate's rim, reward 0.000. With
one convention everywhere the column is 0.651 and the payload lands at r = 0.009–0.014 m on 15/15
seeds. The tell is the **2× factor**: a wrong sign on a measured offset misses by *twice* the offset,
whereas a wrong sign in the offset *estimate* misses by the offset. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— `carry_and_place` lines 630–652 (`release_xy`), `grasp_bowl` line 616 (`pinch_off`); 2026-09-16.

**Counter-example — do NOT close the loop on a *stall* residual with the same trick.** The pattern above
compensates a **grasp** offset: a real, static displacement between the TCP and the object that survives
the whole carry. A **descent stall** leaves a residual that looks identical in the log but is a property
of the descent *path*, not of the target pose, and pre-shifting the command for it moves the landing
without shrinking the error.

Measured on `libero_object_swap/pick_up_the_tomato_sauce_and_place_it_in_the_basket`, where the release
residual ran 0.013–0.104 m and was systematically biased toward +x: re-descending from `CARRY_Z` gave
+0.083 m of x-drift, while re-descending from `CARRY_Z + 0.04` gave only +0.038 m. Applying the
correction (lift, hop to a pre-shifted xy at the higher carry height, re-descend) left the residual
essentially unchanged — 0.104 → 0.091 (seed 53), 0.096 (seed 56), 0.100 (seed 64) — **and flipped seed
53 from reward 1.000 to 0.000**, because the shallower re-descent also stalls shallower (z 0.196 vs
0.162) and releases the object *above* the rim, which is exactly the failure the over-command exists to
prevent. Rejected; the single over-commanded descent is kept. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_tomato_sauce_and_place_it_in_the_basket/fix_code.py`
(header comment records both rejected experiments) and its `findings.md` pattern 3; 2026-09-14.

**How to tell the two apart before spending replays on it**: a grasp offset is *invariant to the approach
path* (it is the object hanging off the TCP), so re-measuring it from a different carry height gives the
same number. A stall residual *changes when you change the approach height* — as it did here, 0.083 →
0.038 m. If the number moves with the path, it is not an offset and must not be compensated.

#### When the offset is NOT constant across grasps, stop compensating it — servo on the held object's own cloud

The compensation above assumes the hang is a *repeatable* number for that grasp. Measure it a second
time and you may find it is not. On
`libero_spatial_swap/pick_up_the_black_bowl_next_to_the_cookie_box_and_place_it_on_the_plate` the
carried bowl measured **+0.040 m** off the TCP on one grasp and **+0.085 m** on the next — on the same
bowl, same task, same radial wall pinch. The cause is upstream of the grasp: a *commanded* pose is not
an *attained* pose. `goto_pose` reports success while the tool axis stalls several centimetres short
laterally, so an offset computed from the pre-grasp pinch pose is derived from a pose the arm never
reached. Every one of the 15 seeds printed the identical assumed offset `(-0.049,+0.000)` and every one
landed 0.076–0.102 m off.

When the offset is neither constant nor derivable from a commanded pose, drop the open-loop correction
and **close the loop on the object itself**: hop the tool until the *held object's measured centre* sits
over the goal.

```python
def servo_object_over(goal_xy, z, quat, max_iter=5, tol=0.006, hop=0.030,
                      held_prompts=HELD_PROMPTS):
    est = None
    for k in range(max_iter):
        rgb, d, K, E = observe()
        cur = tcp_xy()
        # window centred on the PREVIOUS ESTIMATE, not the tool axis, so the object is
        # not clipped by the window edge and its median stays unbiased
        m = measure_held(rgb, d, K, E, cur if est is None else est,
                         radius=0.13 if est is None else 0.10, prompts=held_prompts)
        if m is None:
            return est
        est = m[0]
        err = np.asarray(goal_xy, dtype=float)[:2] - est
        n = float(np.linalg.norm(err))
        if n < tol:
            return est
        step = err * min(1.0, hop / max(n, 1e-6))     # cap the hop at `hop`
        nxt = np.array([cur[0] + step[0], cur[1] + step[1], z])
        if not reachable(nxt, quat):                  # never command an unreachable hop
            return est
        goto_pose(nxt, quat)
```

Three details are load-bearing:

- **The search window must follow the *estimate*, not the TCP.** Centring the window on the tool axis
  lets the object drift to the window edge and be clipped, which biases the median toward the TCP and
  manufactures the very offset you are trying to remove.
- **After the servo, re-read `release_xy = tcp_xy()`.** The descent must start from where the tool
  actually *is*, not from the originally commanded release point — otherwise the servo's work is undone
  by the next absolute command.
- **The window's depth floor must scale with the hang — a fixed offset is not safe.** The `z_floor` that
  keeps table clutter out of the held cloud is the one constant in this function, and the obvious value
  is wrong by an order of magnitude: the bowl hangs only **0.044 m**, so `tcp_z - 0.20` puts the floor
  *below the table* and admits anything tall standing nearby. On
  `libero_spatial_task/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate` seed 53 the
  decoy akita stood `z = 0.002–0.062` within 0.10 m of the plate *and* SAM3 returned **one mask spanning
  both bowls** while the payload passed over its twin — the merged centre sat **0.079 m** off and the
  servo carried a correctly aimed bowl off the plate. Scale the floor to the hang, and add the one gate
  height alone cannot give you — the **footprint**:

```python
z_floor = now[2] - 0.12                   # NOT now[2] - 0.20: ~2.7x the measured hang
sel = pts[(np.linalg.norm(pts[:, :2] - near_xy, axis=1) < radius) & (pts[:, 2] > z_floor)]
lo, hi = np.percentile(sel, 2, axis=0), np.percentile(sel, 98, axis=0)
if not (0.040 <= hi[0] - lo[0] <= 0.150 and 0.040 <= hi[1] - lo[1] <= 0.150):
    continue                              # one mask spanning payload + decoy
if float(np.linalg.norm(centre - now[:2])) > 0.10:
    continue                              # a huge "error" is a bad mask, not a correction to chase
```

  Two bowls ~0.10 m apart give a >0.15 m extent; a single bowl never does — which is exactly the case
  the height gate cannot separate, because both bowls are legitimately up at carry height inside one
  mask. **Evidence**: seed 53 flipped 0.000 → 1.000 on the *first* fix attempt (`err` (+0.003,−0.002),
  verified on plate at `r = 0.006`) with all 14 previously passing seeds still at 1.0. Source:
  `outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate/fix_code.py`
  — `held_cloud` lines 225–260; 2026-09-16.

This is independent of both unknowns at once (whether the commanded pose was attained, and how much the
object hangs from this particular grasp), which is why it replaces the offset entirely rather than
correcting it. **Evidence**: all 15 development seeds flipped 0.000 → 1.000, each converging in 2 steps
to ≤0.002 m residual and landing 0.010–0.015 m from the goal centre. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_next_to_the_cookie_box_and_place_it_on_the_plate/fix_code.py`
— `servo_bowl_over` lines 418–454, `held_offset` 336–356, `release_xy = tcp_xy()` at 554; 2026-09-15.

Contrast with the section above: keep the pre-pinch offset when you have *measured* the sign and it
reproduces; reach for the servo when the same measurement gives you two different numbers.

**The measurement window must be gated in *height* whenever the scene holds a same-class decoy.** This
is the failure mode that makes the servo look like it does not work, and it is silent:

```
window taken in XY only, around the tool axis / previous estimate
  carry the payload toward the goal -> the window starts catching the DECOY's near edge
  -> the median sits BETWEEN the two objects  (servo[1..4] bowl=(0.690,0.220), the decoy's centre)
  -> the servo dutifully drags the held object away from the goal
  -> released 0.134 m off target, reward 0.000 (seed 51, first fix iteration)
```

Gate on height relative to the *current tool z* (`z_floor = z_tcp − 0.20`) rather than on a table
estimate:

```python
def held_obj_xy(rgb, d, K, E, near_xy, z_tcp, radius=0.13):
    near_xy = np.asarray(near_xy, dtype=float)[:2]
    z_floor = float(z_tcp) - 0.20            # <- the load-bearing line
    for p in HELD_PROMPTS:                   # ("bowl", "metal bowl", "small bowl", "bowls")
        for m in sorted(segment_sam3_text_prompt(rgb, p) or [], key=lambda x: -x["score"])[:4]:
            pts = mask_to_world_points(m["mask"].astype(np.uint8), d, K, E)
            if pts is None or len(pts) < 60:
                continue
            sel = pts[(np.linalg.norm(pts[:, :2] - near_xy, axis=1) < radius) & (pts[:, 2] > z_floor)]
            if len(sel) < 60:
                continue
            c = np.median(sel, axis=0)
            return np.array([float(c[0]), float(c[1])])
    return None
```

**A carried object is the only same-class cloud up at carry height**, so the height gate excludes
everything resting on the table *without needing any table estimate* — the same lesson as "anchor the
relation to the named support's own measurement" in `localize.md`, applied to a moving reference frame.
Once gated, the servo converges in 2 iterations (`servo[1] err=0.0015`) and the final landing distance
is 0.010–0.021 m on 14/15 seeds. **Evidence**: seeds 51 and 61 flipped 0.000 → 1.000 (landing 0.021 m
and 0.010 m), full re-sweep 15/15 with no regression; the decoy lock-on above is the counterexample.
Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_on_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— `held_bowl_xy` lines 450–478, `servo_bowl_over` 481–521, call site 596–598; 2026-09-15.

#### Gate that measurement by *continuity*, not by plausibility — a merged mask passes every static gate

**Trigger**: any loop that tracks a **held** object from the wrist view while the gripper occludes it.
The masks intermittently merge with a same-class neighbour, catch the fingers, or drop out — and a
merged mask sits at a *plausible* height, in a *plausible* size band, with a *plausible* underside, so
no static gate catches it. What is wrong with it is that it **jumped**.

```python
new = m["c"][:2]
if est is not None and float(np.linalg.norm(new - est)) > 0.030:
    print("  place[%d]: measurement jumped %.3f -> reject"
          % (k, float(np.linalg.norm(new - est))), flush=True)
    continue                      # hold position, do NOT chase, do NOT release
est = new
```

Compare each measurement against the **previous accepted** estimate — not against the goal, and not
against a size/shape band. This is the complement of `localize.physical-sanity-gate-on-a-segmentation-of-a-held-object`
(which is per-measurement and static: absolute bands plus expected depth): that gate is still right to
have, but a *merged* mask defeats it, and this one is what catches it. Two companion rules in the same
loop: count consecutive dropouts rather than releasing on the first missing mask (`miss >= 3`), and
reject an *upward* base jump (`> 0.015`) — an object cannot rise while it is being set down.

**Evidence**: without the guard the loop chased `est=(0.752,0.166)` — a **54 mm** jump — and released at
`tcp_z=0.062` (seed 59, reward 0.0). With it, the same seed rejects the bad mask four times
(`place[16..19]: base jumped up 0.0185 -> reject`), holds position, and releases centred on the plate
(`xy_off=0.0089`, `ext_z=0.045`) for reward 1.0; seed 61 was repaired by the same guard. Honest caveat:
the shipped program scored **11/15** against its own `initial_code.py`'s **12/15** on dev, with seed 58
flipping to pass on a byte-identical rerun — so the value of this rule is the mechanism and the two
seeds it demonstrably repaired, *not* a sweep-level gain. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_on_the_wooden_cabinet_and_place_it_on_the_plate/fix_code.py`
— `main`, the placement loop; 2026-09-16.

#### Close the *placement* loop on the payload's own measured base — a precomputed release height cannot survive the descent

**Trigger**: the payload is centred perfectly at carry height and *still* lands several centimetres
off. This is the same unknown as the servo above, re-entering at the other end of the carry, and it
appears precisely when the grasp is a wall pinch on a wide/shallow object.

The hang is not one number. A rim pinch on a bowl 10.5 cm wide — wider than the ~8 cm gripper
opening — leaves the payload swinging by about one pendulum length, so the measured offset changes
sign between the pinch and the landing:

```
seed 51: offset at the pinch  (-0.008, -0.052)
         offset at the landing (+0.030, +0.046)      <- sign flipped
```

Any constant compensation therefore lands ~10 cm off, and the error *grows during the descent*
(seed 52 arrived centred to 0.0008 m on its own cloud and then measured 6.7 cm away). So do not
solve for a release height; descend until the object's own base reaches the support:

```python
def place_on_target(goal_xy, support_top, quat, max_iter=24, z_cap=None):
    rest_z = float(support_top) + 0.002
    z_floor = float(support_top) + 0.004     # ABSOLUTE floor: at release height a tool-relative
    z_cap = float(support_top) + 0.032 if z_cap is None else z_cap   # gate admits the support,
    est, stall, z_prev = None, 0, None                               # and the support is LARGER
    for k in range(max_iter):
        rgb, d, K, E = view()
        cur = tcp_pos()
        cl = held_cluster(rgb, d, K, E, cur[:2] if est is None else est, z_floor,
                          0.13 if est is None else 0.11)   # window follows the previous estimate
        if cl is None:
            break
        cxy, base_z, _n = cl                        # base_z = 5th percentile of the object's cloud
        est = cxy
        err = np.asarray(goal_xy, float)[:2] - cxy
        n = float(np.linalg.norm(err))
        if base_z <= rest_z + 0.008:   break         # object base is at the support -> release
        if float(cur[2]) <= z_cap + 0.001: break     # tool floor for this column -> release
        if z_prev is not None and float(cur[2]) > z_prev - 0.002:
            stall += 1
            if stall >= 3: break                     # no longer descending -> release
        else:
            stall = 0
        z_prev = float(cur[2])
        step = err * min(1.0, 0.014 / max(n, 1e-6))  # lateral correction capped at 14 mm
        if n < 0.002:
            step = np.zeros(2)
        dz = float(np.clip(base_z - rest_z, 0.004, HOP))
        goto_pose(np.array([cur[0] + step[0], cur[1] + step[1],
                            max(float(cur[2]) - dz, z_cap)]), quat)
    return est
```

Three details are load-bearing: the floor is **absolute** (`support_top + 0.004`, not
`tcp_z − k`) — see the width note in the servo section, the plate is the *larger* cloud at release
height; the window **follows the previous estimate** rather than the tool axis; and the descent
step is sized by the *measured clearance* (`base_z − rest_z`), never by the commanded z.

**Evidence**: seed 52 landing 6.7 cm → 1.3 cm and seed 53 4.5 cm → 1.2 cm on the same two seeds,
with the previously passing seeds unchanged (13/15 shipped). Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate/fix_code.py`
— `place_on_target` lines 314–364, `held_cluster` 230–261; 2026-09-16.

#### …but the loop above still *discovers* the release height — command it, taper into it, and servo the tool onto it

**Trigger**: the closed descent above, or any descent that stops on a **measured** payload-or-support
height and then opens the jaws *there*. Reaching the base is necessary but not sufficient: the stop
test carries a few mm of mask noise, so the height the payload is let go at is the one quantity in the
program that is decided by the measurement rather than by a command — and it is also the quantity the
predicate is most sensitive to.

```python
drop = 0.002                        # release a couple of mm clear: set down, not pressed in
rel_z_rel = rel_z + drop            # rel_z = rest surface + measured hang of the payload
...
        # inside the descent loop: never command below the release height
        dzmax = 0.030 if base_z > rest_z + 0.030 else 0.010        # TAPER the last 3 cm
        dz = float(np.clip(base_z - rest_z - 0.004, 0.0, dzmax))
        goto_pose(np.array([cur[0] + step[0], cur[1] + step[1],
                            max(gz - dz, rel_z_rel)]), q)
...
# then, outside the loop, COMMAND the release height and close on the measured grip site:
for _ in range(3):                  # the joint servo lands a few mm short of its own command
    cur = tcp(); settle(q, 1); gz = gripz()
    if gz >= rel_z_rel - 0.001: break
    goto_pose(np.array([cur[0], cur[1], rel_z_rel + (rel_z_rel - gz)]), q)   # integral term
open_gripper()
```

Three parts, and each one is load-bearing:

1. **Clamp.** `max(gz - dz, rel_z_rel)` keeps the loop *at or above* the release height. Pressing the
   payload into the support and lifting it back out is not a placement.
2. **Taper.** `dzmax = 0.010` once the payload base is within 3 cm of the support bounds the approach
   *velocity* at contact. A free drop from 8 mm bounced the bowl 24.7 mm off centre and regressed
   seed 51 from 1.0 to 0.0 with everything else identical.
3. **Servo.** The release height is commanded **absolutely** in grip-site space and then closed on the
   *measured* grip site with an integral term (target `rel_z_rel + (rel_z_rel - gz)`), because
   `solve_ik`/`goto_pose` land short of their own target — see `manipulation.md` *"Measure the TCP,
   Not the Hand"*. Release `drop` metres clear so the payload **falls** the last couple of mm instead
   of being pressed in; the jaws are then no longer in loaded contact with the support when they open
   and cannot drag the payload sideways as they retract.

**Evidence**: with the un-closed loop, `gripz()` at the release read **1–6 mm below its own command on
all 15 development seeds** (`rel_z − gripz` = +0.006, +0.005, −0.004, +0.002, −0.002, +0.004, +0.005,
+0.002, +0.005, +0.006, +0.002, +0.003, +0.005, +0.001, +0.003) — i.e. every release pressed the bowl
into a 12 cm plate by a random amount. With the closure, seed 63 released at `gripz=0.060 (cmd 0.061)`
instead of 5 mm low and went **0.0 → 1.0**. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate/fix_code.py`
— `carry_and_place`, the descent loop and the release closure; 2026-09-16.

**Do not judge this by a per-seed sweep result.** The 3 mm of release height the closure removes *is*
the margin that flips marginal seeds, so the same change can move a seed either way on a single draw —
on this task identical shipped code flipped seeds 58 and 59 between 0.0 and 1.0 on repeats. Justify the
taper and the closure by mechanism plus the achieved-vs-commanded height print, and only then by score.

#### The measured hang can be NEGATIVE — carry the sign, do not assume the payload hangs below the pads

Every release height above is built as `support + hang`, which quietly assumes `hang > 0`: that the
payload's base sits *below* the fingertips. A payload **thinner than the finger pads**, pinched with
the pads pressed to the deepest pose the IK accepts, breaks that assumption — the pads close *below*
the slab's base, so `hang = fingertip_z_at_grasp − object_bot` comes out **negative**. A release height
built from a positive hang then lands short, and the slab is still on the pads when the jaws open.

```python
# measured on all 15 seeds: hand 0.117, fingertip 0.117 - 0.132 = -0.015, slab base 0.002-0.005
hang     = (hand_at_grasp - FINGERTIP_OFFSET) - float(box["bot"])   # -0.017 .. -0.019 (NEGATIVE)
z_under  = rim - RELEASE_UNDER_RIM                                  # 0.101
hand_rel = z_under + hang + FINGERTIP_OFFSET                        # commanded 0.215 -> measured 0.219
```

The sign is not the point; **carrying** it is. Read the formula as a definition rather than a
measurement — the payload's underside is at `hand − FINGERTIP_OFFSET − hang`, which holds whether the
pads reach past the base (negative hang) or stop above it (positive hang). Written that way, the same
three lines serve a 14 cm carton and a 15 mm slab with no branch, and the "pressed to the floor" pinch
(see [grasp.md](grasp.md)) no longer needs a special release case.

**Evidence**: on `libero_object_task/pick_up_the_milk_and_place_it_in_the_basket` (runtime language
"Pick the *butter*…"; the payload is a **15 mm slab**) the measured hang was **−0.017…−0.019 m** on all
15 development seeds, and the release commanded hand z 0.215–0.222 against a rim of 0.141–0.142 landed
the slab inside the mouth every time. `gap after lift` equalled `gap after close`
(0.0388–0.0392 m — the slab's 37 mm short side) on every seed, so nothing shifted in the jaws across
the carry. Source: same `fix_code.py` — `main`, the hang line at 314 and the release-height lines at
322–324 (press-to-floor pinch ladder 284–312); 2026-09-16.

### Carry a Marginal Friction Grip in Short Hops, With a Re-Close and a Gap Check Per Hop

**Trigger**: a smooth, dense, cylindrical object held only by friction (a wedge pinch, a rim pinch)
being carried over a long distance in one move. The single long move is where the grip is lost.

```python
for w in (mid, above_place, place):
    if _gap() <= AIR_GAP:
        return False                 # already gone - never release an empty gripper
    move_tcp(w, DOWN_QUAT, iters=3)
    close_gripper()                  # re-wedge at EVERY hop
    if _gap() <= AIR_GAP:
        return False
```

The re-close is the whole trick: each hop re-seats the fingers on the object, so the grip is renewed
rather than accumulating slip. The gap check *before* release is what keeps a lost object out of the
target container.

**Why it works + evidence**: on `libero_goal_swap/open_the_top_drawer_and_put_the_bowl_inside` one
long move measured `gap 0.0014` (lost) where the identical transfer split into three hops measured
`0.0036 … 0.0185` (held). Requires the measured-gap verifier in [grasp.md](grasp.md). Source:
`outputs/libero_fix_loop/libero_goal_swap/open_the_top_drawer_and_put_the_bowl_inside/fix_code.py` —
`carry_to`; 2026-09-14.

**Confirmed on a friction pinch, and the failure is silent — a *passing lift check* does not predict
carry survival.** On `libero_object_swap/pick_up_the_salad_dressing_and_place_it_in_the_basket` seed 51
the cap pinch verified twice (`gap after close 0.0281`, `gap after lift check 0.0257`), was still
healthy at the start of the lateral move (`carrying gap 0.0257`), and then the release logged
**`gap_before_release = 0.0010`** — the gripper opened over the basket on an empty hand and the episode
scored 0 with **nothing raised and no error printed**. The grip died somewhere inside a single ~21 cm
move. So treat the *pinch* check and the *carry* check as separate gates: the lift check proves the
fingers cleared the table, not that the object is still there at the far end. Split the lateral move into
`stages` interpolated sub-hops with `close_gripper()` and a `holding()` test at each, and — the
load-bearing half — re-test `holding()` **immediately before `open_gripper()`** and `return False`
rather than opening, letting the caller re-localise and retry the whole cycle:

```python
if not holding():
    print("  grip gone at the release point; NOT opening over the basket", flush=True)
    goto_pose(np.array([bx, by, CARRY_Z]), quat)
    return False                    # caller retries; never release an empty hand
```

Without the release-time gate the program still *appears* to finish (it prints `done`, raises nothing)
while scoring 0 — which is exactly how this failure hides. With the pattern: **0 grip losses on 15/15**
development seeds (`gap` 0.0367 after close, after lift and at the release point on every seed) and the
retry cycle never fired. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_salad_dressing_and_place_it_in_the_basket/fix_code.py`
— `holding`, `carry_to`, the gate in `place`; 2026-09-14.

### Release Below the Rim of a Tall Container Whose Floor Cannot Be Measured

**Trigger**: placing a small object into a container whose interior floor is **not visible to depth** —
a tall basket or bin, where the near wall occludes the inside completely. Any "aim at the measured
container floor" rule is unavailable, and "release just above the rim" leaves the object's centre above
the container's top plane, which an object-`In` predicate may reject.

```python
RELEASE_UNDER_RIM = 0.040          # object underside this far below the measured rim
z_under  = rim - RELEASE_UNDER_RIM
hand_rel = z_under + hang + FINGERTIP_OFFSET
move_xy(cx, cy, quat, z=CARRY_Z)   # lateral at carry height, then one vertical descent
descend(cx, cy, quat, hand_rel, tag="place")
open_gripper()
```

Measure the rim, not the floor: on a rectangular container the rim is the **98th percentile of the
container mask's z**, and the release xy is the midpoint of the mask's 1st/99th percentile footprint —
for a rectangle that midpoint *is* the interior centre. The fingers then end up a few centimetres inside
the mouth, which is what centres the object, and the object falls the remaining ~6 cm onto the floor.
Requires `hang` from the pinch (see the release-height section above) and a container wide enough that
the open gripper clears its walls (here 11.5 × 13 cm interior against an ~8 cm gripper).

**The exact depth is not a knife edge**, which is what makes this usable without a measured floor: on
this task a release ~2.3 cm below the rim also scored 1.0, so anything in the 2–4 cm band works. Use it
when the floor is *unmeasurable*; when the floor is measurable but unreachable, the over-command pattern
below is the better tool.

**Ablation — on a tall bottle this rule is an *equivalent alternative* to the over-command, not a
requirement.** On `libero_object_swap/pick_up_the_salad_dressing_and_place_it_in_the_basket` the release
height was derived as `z_rel = rim − RELEASE_UNDER_RIM + hang`, with `hang = pinch_tcp_z − object_base_z`
read at the pinch (0.119 m — the pads sat at the bottle's very top, so it hangs its full 14.8 cm below
them). Replacing that with the blind deep over-command used by the sibling tasks
(`descend_to(bx, by, 0.06, …)`, a flat target far below the basket floor) **also scored 1.000 on seeds
51–55**, stalling at a measured pads z of 0.143–0.144 against a rim of 0.141–0.142. Under *either* form
the physical stall — not the commanded depth — sets where the object is released. The object-derived
rule is belt-and-braces: it gives a slightly tighter release xy (2–3.5 cm closer to the basket centre)
and an explicit readable release condition. Its stated motivation — a 14.8 cm bottle whose base would sit
~1.8 cm below a 0.012 m basket floor when the pads stall 3 cm under the rim — was **never independently
reproduced**, because on the one run where the deep command was tried the grip had already been lost
before the release. Record it as an equivalent alternative for a container with a *measured* rim rather
than as a correction to the over-command pattern.

**Why it works + evidence**: on `libero_object_swap/pick_up_the_butter_and_place_it_in_the_basket` a
16 × 16 top-z grid over the basket footprint returned **no points at all** in the 11 interior columns
(the near wall occludes it) — only the rim (z ≈ 0.142) and the inner wall tops are visible. Releasing at
`rim − 0.040` succeeded 15/15 development seeds on the first attempt with no retry (release hand z
0.215–0.219 against a rim of 0.1414–0.1416). Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_butter_and_place_it_in_the_basket/fix_code.py`
— `find_basket`, `main`; 2026-09-14.

### Release *Above* the Mouth When the Payload Is as Tall as the Container Is Deep

**Trigger**: a pick-and-place where `payload_height >= container_interior_depth`, or where the mouth's
free width is under ~1.5 × the gripper body. Symptom: the container is **displaced** during the descent
— the payload's lower edge, and then the gripper body, catch the near wall — and the payload ends up
standing on the table at the rim line rather than inside.

**Same container, same task name, opposite rule from the entry above — and the payload is what
changed.** On `libero_object_swap/pick_up_the_butter_and_place_it_in_the_basket` the payload is a low
butter box and releasing ~4 cm *below* the rim scored 15/15. On
`libero_object_task/pick_up_the_butter_and_place_it_in_the_basket` — the `_task` remap, whose
authoritative language is `"Pick the orange juice and place it in the basket"` — the payload is a
**0.143 m carton in a basket only ~0.135 m deep**, and a below-rim release is fatal on every seed. So
the release height is not a property of the container; it is a function of
`payload_height / interior_depth`.

```python
HIGH_CLEARANCE    = 0.100        # whole lateral transit height, above the rim
RELEASE_ABOVE_RIM = 0.020        # payload BASE released 2 cm above the rim, then dropped in
high_z    = rim_z + hang + HIGH_CLEARANCE
release_z = rim_z + hang + RELEASE_ABOVE_RIM
```

`hang` is measured in the **commanded** frame (`pinch_z_cmd − target_zlo`, both terms taken before the
lift — see [grasp.md](grasp.md)); lift vertically at the pick xy, fly the transit, then descend purely
vertically and open.

**Why it works**: the carton is *taller than the basket is deep*, so seating its base on the basket
floor necessarily puts the gripper at rim height — the height at which the arm must be to seat it is
the height at which the gripper body is inside the mouth. Against ~0.11 m of usable interior and an
~0.08 m gripper there is no descent path that ends with the payload in the basket. Releasing the base
2 cm above the rim and letting the carton fall the remaining distance removes the requirement
entirely.

**Evidence**: baseline `hand_z = (rim_z − 0.070) + hang` (payload base 7.0 cm below the rim) →
**2/15**, and the trial video shows the mechanism: the carton's lower edge catches the near rim, the
still-descending arm **shoves the basket ~0.03 m in +x**, and the carton is left on the table at the
near rim line. Shipped `hand_z = rim_z + 0.020 + hang` → **14/14 in each of two independent draws**
(28/28 on seeds 52–65, no seed flaky). Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_butter_and_place_it_in_the_basket/fix_code.py`
— `RELEASE_ABOVE_RIM` line 42, `high_z`/`release_z` lines 403–404, the release block lines 441–446;
2026-09-16.

**Scope of the claim — this is a comparison against a *reachable* deep release, not against the
over-command.** The over-command pattern below deliberately commands a target the arm cannot reach and
lets the physical stall set the height; on this scene the stall was never measured, and the shipped
program never issues an unreachable z. So the honest statement is: *given a commanded release depth,
above-rim beats 7 cm below-rim on a payload this tall.* Whether an over-command would also have worked
here is **untested** — do not read this entry as evidence against it.

**Partially resolved by a sibling `_task` task, and in the over-command's favour.**
`libero_object_task/pick_up_the_ketchup_and_place_it_in_the_basket` (runtime language "Pick the milk…")
carries a **13.4 cm carton — the same object class — into the same basket** and releases by
over-commanding a flat z 0.06. The arm stalls 2.7 cm below the rim and the task scores **15/15**
development seeds. So an over-command into this container in a `_task` scene is *not* inherently fatal,
and payload height alone does not distinguish the two runs. What does distinguish them is what the arm
**does** with the command: ketchup's target is unreachable, so the *stall* sets the release height,
whereas butter's baseline commanded `rim − 0.070` — a depth the arm **reached** — driving the gripper
body on past the stall point and into the wall. Read the two entries together as: a release height is
safe when a stall sets it or when an explicit above-rim rule sets it, and unsafe when it is a
*reachable* deep target. Butter's own program was never run against an over-command, so this adjusts
the explanation, not the measured result.

**That last sentence is now itself too strong, and a third payload shows where it fails.**
`libero_object_task/pick_up_the_tomato_sauce_and_place_it_in_the_basket` (runtime language "Pick the
**bbq sauce**…") carries an **0.110 m bottle into a ~0.13 m interior** and releases at
`rel_z = rim − RELEASE_UNDER_RIM + hang` with `RELEASE_UNDER_RIM = 0.040` and `hang = 0.089–0.090`
(measured at the pinch, before any lift). The payload base lands at **0.101–0.102 against a rim of
0.141–0.142 — exactly 4.0 cm below the rim** — and the arm **reached** the commanded z on 10 of the 15
development seeds and stalled on the other 5 (57, 58, 59, 60, 62). **Both cases scored 1.0; the task is
15/15.** So a reachable below-rim release is not fatal here, on a *deeper* command than several of the
cases the paragraph above treats as dangerous.

What separates the three runs is the payload-to-interior ratio, and it is the ratio — not the
reachability — that the paragraph above is really pointing at:

| task | payload | interior | base below rim | outcome |
|---|---|---|---|---|
| `_swap` butter | 15 mm slab | ~0.135 m | 4.0 cm | **15/15** |
| `_task` butter | 0.143 m carton | ~0.135 m | 7.0 cm | **2/15** → above-rim 14/14 |
| `_task` ketchup | 0.134 m carton | ~0.135 m | 2.7 cm (stall) | **15/15** |
| `_task` tomato_sauce | 0.110 m bottle | ~0.13 m | 4.0 cm (reached on 10/15) | **15/15** |

Read the four rows together and reachability stops being the discriminator: tomato_sauce's release is
reachable and safe, ketchup's is stalled and safe, butter's is reachable and fatal. The row that is
fatal is the one where the payload is *taller than the interior is deep*, and there the base cannot go
7 cm below the rim without the descent path putting the carton's lower edge through the near rim. Note
also why the *tool* height stays clear while the payload does not: the bottle is pinched high
(`GRASP_FRAC = 0.78`), so `hang` is 0.089 and the tool sits at z 0.190 — well above the 0.141 rim —
even with the payload base 4 cm inside. **The quantity to derive is the payload base, not the tool z.**

This does **not** close the question the paragraph above opened — tomato_sauce was never run against an
over-command either, so no run in this table isolates reachability from payload ratio, and none of them
tests a tall payload released by stall *below* the rim. What it does establish is that "reachable deep
release" alone does not predict the butter failure. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_tomato_sauce_and_place_it_in_the_basket/fix_code.py`
— `RELEASE_UNDER_RIM` line 39, `hang` line 342, `rel_z` line 379, the descent 380–381; 2026-09-16.

### Fly the Whole Lateral Transit Above the Rim, Before Any Sideways Move

**Trigger**: any carry whose path crosses the destination container, where the payload hangs below the
hand by more than a few millimetres. A fixed free-air carry height is not safe, because the payload's
underside sits at `carry_z − hang` and `hang` is known only after the pinch.

Order is the whole content of the pattern: **lift vertically at the *pick* xy to the transit height
first, then move laterally.** A Cartesian move that corners is not the same path as a joint-space
interpolation, and a single "go to (x, y, high_z)" from the pick pose lets the arm swing the payload
sideways through the rim plane on the way up.

**Evidence**: on `libero_object_task/pick_up_the_butter_and_place_it_in_the_basket` the pick-pose lift
height `LIFT_Z = 0.215` puts the payload base at 0.128 m against a rim at 0.135 m — **7 mm below** — so
even though the *hand* looked high, the first sideways move already crossed the rim plane and fouled
the basket. Flying the transit at `rim_z + hang + 0.100 = 0.322` placed all 14 attempted seeds
cleanly. Source: same `fix_code.py` — `high_z` at lines 403–404 and the vertical lift to it at line
420, which precedes every lateral step; 2026-09-16.

### Close the Placement Loop on the Payload's Own Measured xy, Not the Hand's

**Trigger**: any placement into a target whose free width is under ~2–3 × the hand-to-payload lateral
offset. An open-loop model aim (`mouth − nominal_offset`) leaves the *payload's* centre off by the
per-grasp offset, which is not the nominal one.

At the transit height — payload base ~10 cm above the rim and fully visible in the agentview — measure
the carried object's xy, close the loop, and re-command:

```python
for _ in range(MAX_ALIGN):                      # 3
    obj = find_carried(rgb, d, K, E)            # identity-gated; xy only, never its base
    if obj is None:
        break                                   # no payload found -> keep the model aim
    err = mouth - obj
    if np.hypot(*err) < ALIGN_TOL:              # 0.006
        break
    step = np.clip(err, -ALIGN_STEP, ALIGN_STEP)  # 0.05
    go([cur[0] + step[0], cur[1] + step[1], high_z], quat)
```

The identity gate is the language's **colour word plus a hand-radius window**, and the carried mask's
*base* is never used (see "Never Re-Localize an Object While It Is in the Gripper" in
[localize.md](localize.md) — on this very task the carried carton's mask reported a base 7.4 cm too
high while its xy was right to 6 mm). When the gate finds nothing the loop is a no-op and the model aim
is used, which is the correct failure mode: it degrades to the previous behaviour rather than to a
guess.

**Evidence**: measured hand-to-payload lateral offsets of +0.030 m (seed 51, two independent
measurements agreeing to 1 mm) and +0.004…+0.006 m (seeds 54–58) against a ~0.11 m basket interior and
a 0.05 m payload — the margin is a few centimetres, so aiming the hand at the mouth centre puts the
payload off centre. The loop converged `|err| 0.011 → 0.005` on seed 54 and `0.009 → 0.005` on seed 55,
both reward 1.0; the no-op path also scored 1.0 on seeds 52/53/56–65. Source: same `fix_code.py` — the
alignment loop lines 417–438, `find_carried` lines 231–274; 2026-09-16.

### Over-Command the Descent Into a Container — the Stall Does the Centring

**Trigger**: placing an object into a container whose mouth is only slightly wider than the object
(a bowl, a cup, a drawer bay), where the release xy has to be accurate to about a centimetre.
Symptom: the object is released beside the container or ends up standing **upright on its rim**
even though the TCP looked centred. A stepped descent stops as soon as its z target is satisfied and
never converges x/y, so a ~4 cm lateral residual is still there when the gripper opens.

```python
# aim the carried object's UNDERSIDE at the container FLOOR - a height the arm
# cannot reach - then keep re-commanding it until the arm stops moving.
z_release = rim_z - DROP_DEPTH + FINGERTIP_OFFSET + hang   # hang = object's drop below the pads
lower_to(cx, cy, z_release, DOWN_QUAT)      # stepped, one command per step, no xy retry
prev = float(tcp()[2])
for _ in range(12):
    press_cmd(cmd_of([cx, cy, z_release]), DOWN_QUAT)
    cur = float(tcp()[2])
    if prev - cur < 0.0008:                 # no more progress -> stalled
        break
    prev = cur
open_gripper()
```

The deep aim is **load-bearing even though the arm never gets there**: the sustained downward command
is what keeps the Cartesian controller working long enough to converge the xy onto the container
centre. The *physical stall*, not the commanded pose, fixes the release height. Commanding only the
reachable height gives up on the xy; clamping the command so the fingertips stay above the rim is
much worse (see the next entry).

**Why it works + evidence**: on `libero_goal_swap/put_the_cream_cheese_in_the_bowl` the working seeds
stall of their own accord at reported z ≈ 0.1918 against a bowl rim at 0.039 — the pads stop 3.7 cm
*above* the rim and never enter the mouth, while the xy converges. The deep aim + settle loop flipped
seeds 52, 54, 55, 57, 58, 60, 61, 62, 63 from 0.0 to 1.0 (4/15 → 13/15) and held the four that
already passed; a flat slab released only a couple of centimetres above a conical mouth instead falls,
catches the inner slope and wedges vertical (top ≈ 0.070 m against a rim at 0.039 m). Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_cream_cheese_in_the_bowl/fix_code.py` — `main`,
lines 335–439 (the `rep_target` + settle loop at 388–416); 2026-09-14.

**Confirmed in a different suite, where the stall lands just *below* the rim.** The stall height is a
property of the arm and the container's position, not of the pattern, so it can fall on either side of
the rim: on `libero_object_swap/pick_up_the_chocolate_pudding_and_place_it_in_the_basket` the arm stalls
at TCP z **0.1364–0.1373** while the basket rim is at **0.1415–0.1416** — the pads release ~4 mm *below*
the rim, the gripper never enters the mouth, and the box falls ~12 cm onto the liner. 15/15 development
seeds. As above, the commanded target (`rim_z − 0.030 − hang ≈ 0.1259`) is never reached, so the stall —
not the command — sets the release height. Two rules carry over unchanged: **do not try to descend into
the mouth**, and **do not clamp the commanded target to stay above the rim**, since the deep command is
what keeps the Cartesian controller converging xy. When the container is tall enough that this stall
sits well inside the mouth, the "Release Below the Rim" pattern above gives the same behaviour without
relying on where the stall happens to land. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_chocolate_pudding_and_place_it_in_the_basket/fix_code.py`
— `run`; 2026-09-14.

**Confirmed again on an `In`-site container, where the commanded target is far below the floor.** On
`libero_object_swap/pick_up_the_alphabet_soup_and_place_it_in_the_basket` the release descent is
commanded to a flat **z 0.06** while the basket's interior floor is at **0.012** and its rim at
**0.140** — a target the arm cannot approach, deliberately. Every seed stalls at a measured TCP of
**0.140–0.153**, i.e. right at the rim, and drops the can ~0.12 m into the basket. Two details worth
copying: the descent is a **ladder** of ≤2.5 cm hops rather than one long move (a single 12 cm hop
under-reaches by 2.8 cm with no error — see [grasp.md](grasp.md)), and the xy released on is the one
measured **before** the grasp, not re-segmented while carrying (the carried can dragged the basket's
mask centroid 8.7 cm — see "Never Re-Localize an Object While It Is in the Gripper" in
[localize.md](localize.md)). 15/15 development seeds. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_alphabet_soup_and_place_it_in_the_basket/fix_code.py`
— `place`, `below`, `run`; 2026-09-14.

**The stall height also depends on the *carried geometry* — do not carry a sibling's number across.**
This is the sharpest version of the caveat, and it comes from the **same container**. On
`libero_object_swap/pick_up_the_milk_and_place_it_in_the_basket` — the same `In`-site basket, the same
commanded flat z 0.06, the same descent helper — the arm stalls at a measured pad z of
**0.120–0.124** against a rim of **0.141–0.142**, i.e. ~2 cm **below** the rim, where the alphabet-soup
sibling packaged into that very basket stalled **at** the rim (0.140–0.153). The two tasks differ in
what is being carried: an 8 cm can pinched near its middle versus a **14.3 cm** brick pinched at 55% of
its height, so the carried body hangs further below the pads. Both runs scored 15/15 development seeds.

The rule this yields is not a constant but a restatement of the aim: **the release pad height is
whatever the arm gives you; what you control is where the object's *underside* ends up.** Aim the
object's base far below the rim (here the brick's base sits ~0.09 m below a 0.141 rim and it falls
~3.5 cm onto the floor), and read the measured TCP back after the descent so the log records where the
pads actually landed rather than where they were sent. A literal `release_z = rim − 0.02` copied from
this task would release the soup can *inside* the basket wall. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_milk_and_place_it_in_the_basket/fix_code.py`
— `place`, `find_basket`, `run`; 2026-09-14.

**Third data point on the same container, and the strongest case for the carried-geometry reading.** On
`libero_object_swap/pick_up_the_orange_juice_and_place_it_in_the_basket` — again the same basket, same
commanded flat z 0.06 — the stall lands at pad z **0.113–0.114** against the 0.141–0.142 rim. Ordering
the three tasks by the *height of the carried object* orders the stall heights exactly:

| Task (same container) | Carried object, and where it was pinched | Stall pad z | Rim |
|---|---|---|---|
| alphabet soup | 7.8 cm can, pinched mid-body | 0.140–0.153 (at the rim) | 0.140 |
| milk | 14.3 cm brick, pinched at 55 % of height | 0.120–0.124 (~2 cm below) | 0.141–0.142 |
| orange juice | 13.4 cm carton, pinched at 55 % of height | **0.113–0.114** (~2.8 cm below) | 0.141–0.142 |
| ketchup (`_task`, carries the **milk carton**) | 13.4 cm carton, pinched at 55 % of height | **0.112–0.115** (~2.7 cm below) | 0.1415 |

The orange-juice task also shows why the *object's base*, not the pad, is the quantity that matters: the
carton is 13.4 cm tall in a basket ~13 cm deep, so its base reaches the basket floor while the pads are
still 2.8 cm below the rim — the object's own base terminates the descent, and any release height
computed to put the *pads* somewhere sensible would be measuring the wrong end of the object. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_orange_juice_and_place_it_in_the_basket/fix_code.py`
— `place`, `find_basket`; 2026-09-14.

**The last row is the same carried object in a different suite, and it lands on the same stall — the
strongest support for the carried-geometry reading.** On
`libero_object_task/pick_up_the_ketchup_and_place_it_in_the_basket` the runtime language names the
*milk* (the `_task` remap; see [localize.md](localize.md)), and the payload is again a **13.4 cm
carton pinched at 55 % of its height**, released with the same flat `RELEASE_Z = 0.06` into the same
basket. The arm stalled at `tcp z = 0.112–0.115` on every one of the 15 development seeds — matching
the `_swap` orange-juice row's 0.113–0.114 to within 2 mm, from a different suite, a different task
name, and a different program. Two independent programs carrying the same object into the same
container stop at the same height, which is what makes this a property of the **arm and the carried
geometry** rather than of either program. One implementation note from this run: the
released-gripper check must be **two-sided** (`AIR_GAP < g < 0.075`), because an *open* gripper reads
~0.080 and a one-sided `g > AIR_GAP` is therefore true after every successful release. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_ketchup_and_place_it_in_the_basket/fix_code.py`
— `place` lines 336–361, `find_basket` lines 271–295; 15/15 development seeds; 2026-09-16.

**A fourth data point in a `_task` suite, where the same flat z 0.06 lands the payload from a *flat*
object.** On `libero_object_task/pick_up_the_alphabet_soup_and_place_it_in_the_basket` the release ladder
walks from `CARRY_Z = 0.30` down to the same deliberately-unreachable `DROP_Z = 0.06`, then re-commands it
in a settle loop until the arm stops making progress (`prev − cur < 0.0008`). The arm stalls at measured
eef z **0.212** against a rim of **0.141–0.142**, i.e. ~7 cm *above* the rim, and the 1.8 cm slab — pinched
low, unlike the mid-body can above — falls in with `task_completed` on **15/15** development seeds. The
spread across all four tasks in this family (stall 0.212 here, 0.140–0.153 on the can, 0.120–0.124 on the
milk brick, 0.113–0.114 on the orange-juice carton) is the clearest statement of the rule: `DROP_Z` is a
*constant you invent*, the stall is a property of the arm and the carried geometry, and the only thing the
program controls is that the object's base is commanded far enough below the rim. Two details also carry
over from the alphabet-soup `_swap` sibling above — the descent is a **ladder**, not one long move, and the
release xy comes from the container's own rim band rather than its whole-cloud median
([localize.md](localize.md)). Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_alphabet_soup_and_place_it_in_the_basket/fix_code.py`
— `main`, release ladder at lines 234–245; 2026-09-16.

**A fifth data point that confirms the *flat-object* stall height reproduces across tasks, not just
across suites.** On `libero_object_task/pick_up_the_orange_juice_and_place_it_in_the_basket` — a
different task, a different program, a different payload (a **2.8 cm** dark box against the alphabet
soup `_task` sibling's 1.8 cm slab), but the same flat `DROP_Z = 0.06` and the same ladder-and-settle
release — the arm stalls at measured eef z **0.210–0.212** against a rim of 0.141–0.142. That matches
the alphabet-soup `_task` row's 0.212 to within 2 mm, and it lands on the *same* side of the rule as
everything else in this family: the stall is ~7 cm **above** the rim, far from the commanded 0.06, so
`DROP_Z` was never reached on any seed. Read the family as two clusters rather than one spread — a
**flat payload pinched low** stalls ~7 cm above the rim (0.210–0.212, two tasks), and a **tall payload
pinched at 55 % of its height** stalls 2–2.8 cm *below* the rim (0.112–0.124, three tasks). **The
salad-dressing entry below does not fit either cluster, and it is recorded there as an open tension
rather than folded in here** — treat the grouping as a correlation to test, not a predictor, until a
single task is measured with two commanded depths. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_orange_juice_and_place_it_in_the_basket/fix_code.py`
— `main`, the release ladder (`DROP_Z` line 36); 15/15 development seeds; 2026-09-16.

**A sixth data point that does NOT fit the two clusters — record the tension, do not smooth it.** On
`libero_object_task/pick_up_the_salad_dressing_and_place_it_in_the_basket` the payload is a **7.8 cm
can** (the same size and class as the alphabet-soup `_swap` row above, `h = 0.077–0.079`), it is carried
into the same basket, and the release commands the **same flat unreachable depth** — `descend_to([x, y,
0.060])`, with the source comment *"Command far below the rim on purpose: the arm stalls inside the mouth
and the can is released there. Do not clamp the target to stay above the rim."* The pads stalled at
measured z **0.1051–0.1052** against the 0.141–0.142 rim: ~3.6 cm **below** the rim, where the
alphabet-soup `_swap` can stalled **at** it (0.140–0.153).

So the carried-geometry reading is **not sufficient on its own**. Two tasks with the same nominal
carried object and the same flat, unreachable command produced stalls 3.5 cm apart, which means at least
one of the things this table treats as "the carried geometry" is not the operative variable — candidates
that this run does not separate: the pinch height on the can (mid-body vs nearer the top), the exact
quantity each program reads back (`tcp_world()` vs the reported eef pose vs a pad z), and the stall
detector itself (`STALL_EPS = 0.0015` with 2 consecutive stalled hops here, vs `prev − cur < 0.0008`
in the alphabet-soup ladder). Note the epsilon direction rules one explanation out: a *looser* progress
threshold declares the floor *earlier* and therefore *higher*, so it cannot explain a stall 3.5 cm
lower. **Use the table as a per-sequence lookup, not as a predictor**: what transfers across all six
tasks is that the measured floor — not the commanded value — decides the release, and the two-cluster
grouping above is a correlation across tasks that differ in more than payload until someone varies the
command *within* one task and measures the stall twice. What this run does establish independently is
the **tightness** of a repeated floor: 0.1051–0.1052 across 15 seeds is a 0.1 mm spread, so a measured
floor is a far better release datum than any commanded constant. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_salad_dressing_and_place_it_in_the_basket/fix_code.py`
— `main` lines 386–392 (the release command and its comment), `descend_to` lines 94–134 (hop budget 16,
`MAX_HOP` 0.025, `STALL_EPS` 0.0015, `STALL_HOPS` 2); 15/15 development seeds; 2026-09-16.

### Guard the *Container*, Not the Commanded Target

**Trigger**: the same release-into-a-container motion — the finger pads are driven below a
container's rim, and the worry is that the retreat will drag the container with them.

**Lesson**: the naive guard is to clamp the **commanded** target so the fingertips cannot go below
the rim. That was measured and it is much worse: the shallower command removes the sustained
downward push that does the xy centring, so the arm simply reaches the target and the object is set
down too high, wedging on the rim everywhere. If the motion needs a guard, guard the **measured** z
inside the settle loop instead — stop pressing once `tcp()[2] <= rim_z + FINGERTIP_OFFSET + margin` —
so the deep command is still issued on the way down and the loop merely exits before the pads enter
the mouth.

**Evidence (negative result)**: on `libero_goal_swap/put_the_cream_cheese_in_the_bowl` the
clamped variant scored **2/15** (seeds 56, 62) on exactly the seeds the unclamped program scores
14/15 on. The lesson is documented here from the program's own comments — the clamped variant lived
in a throwaway probe, not in the shipped `fix_code.py`, so there is **no executed-source anchor**
for it and it is deliberately not recorded as a code instance. Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_cream_cheese_in_the_bowl/fix_code.py`, lines
379–388; 2026-09-14.

### Verify the Placement Against the Target Pose Measured BEFORE the Carry

**Trigger**: any post-placement segmentation of a thin or flat target — a plate, a tray, a sheet of
paper — with the just-released payload sitting on or near it. The payload **occludes part of the
target's mask**, so the re-segmented centroid is dragged away from the true centre, toward the object
doing the occluding.

The artefact is *repeatable*, which is exactly what makes it dangerous: on
`libero_spatial_swap/pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate` the plate
read as `moved=+0.023 m` on **every** seed. A repeatable number looks like physics, so the natural
response — feed it forward, or nudge toward it — is to chase a measurement error.

Hold the **pre-carry** reference pose for every decision, and treat the post-release segmentation as
report-only:

```python
# plate pose captured pre-carry (pcx, pcy); post-carry re-segmentation is only
# used for the report line, never for control or for the pass/fail test
print("place check ... plate=(%.3f,%.3f) dist=%.3f -> %s" % (pcx, pcy, dist, ok))
```

**Evidence (regression, reverted)**: a nudge term chasing the artefactual shove pushed an
already-good placement off centre and tipped the bowl onto the plate rim — seed 56, bowl z-extent
`0.054` vs `0.044` flat — taking the sweep to 14/15. With **both** the nudge and the `SHOVE`
feed-forward deleted, placement is 15/15 with the object flat on every seed. The general rule: when
the measurement is occluded by your own payload, repeatability is not evidence of truth. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate/fix_code.py`
— `placed` lines 427–456; 2026-09-15.

#### …and let the check *end the loop* — a bare iteration counter can re-carry a good placement

**Trigger**: any place task whose retry loop is bounded only by a counter (`for k in range(MAX_ITERS)`),
when the first placement is already correct.

The rule above says which pose to trust; this one says what to do with the verdict. A loop that only
stops on a counter has no way to notice that it has already succeeded, so it carries a **second** time —
and the second carry is the dangerous one, because by then the target has moved and the re-derivation
can select a different object. On
`libero_spatial_task/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate` seed 51 the
initial program placed the bowl correctly at `(0.709, 0.196)` and then re-carried the **ramekin**.

Make the perception check a first-class exit condition — evaluated at the *top* of each iteration, not
only after the loop:

```python
def bowl_on_plate(plate):
    """A bowl-shaped cloud over the plate's footprint whose underside sits ON the
    plate surface, not on the table (-5 mm)."""
    rgb, d, K, E = observe()
    for c in dedupe(bowl_candidates(rgb, d, K, E, BOWL_PROMPTS)):
        r = float(np.linalg.norm(c["c"] - plate["c"]))
        if r < 0.075 and float(c["lo"][2]) > float(plate["top"]) - 0.006:
            return c
    return None
```

**Evidence**: with the check guarding the loop head, the run exits immediately after the verified
placement (`VERIFIED on plate: c=(0.709,0.196) r=0.006`) instead of re-carrying, and seeds 51–65 all
score 1.0 on the shipped revision. Source: same `fix_code.py` — `bowl_on_plate` lines 309–320, called at
the top of `run()`; 2026-09-16.

#### A verification window *narrower than the object* biases the check by a fixed offset — and widening it can be worse

**Trigger**: any "did it land where I aimed?" check that windows a point cloud around the goal and takes
a median or centroid, when the window radius is comparable to the object's own radius.

```
r_win = max(0.07, r_obj + 0.04) = 0.089 m      for a landed bowl of 0.102 m
pts   = object_points_near(rgb, d, K, E, goal_xy, radius=r_win)
c     = np.median(pts, axis=0)                 # pulled towards the window centre
dist  = math.hypot(c[0] - goal_xy[0], c[1] - goal_xy[1])   # = true error + 0.017, on 15/15 seeds
```

The window keeps only the object's **near half**, so the median lands on the window side: measured
`check = true landing error + 0.017 m` on every development seed (seed 60 landed 0.019, reported 0.036;
seed 65 landed 0.022, reported 0.039). That silently converts an intended `0.035 m` tolerance into an
effective **0.018 m** and fabricated the "not placed" verdicts behind four blocked seeds.

**Do not repair it by widening the window.** That was measured and falsified: at `r_obj + 0.09` the
window takes in the **gripper's fingers**, which sit one object radius towards the wrist, and the bias
flips to **−0.030 m** — worse than the disease, and now in the direction that *accepts* bad placements.
The usable rule is the one this whole file keeps arriving at: **measure the bias against a known-good
placement before trusting the check's tolerance**, and remember that a stable magnitude is not a stable
sign. Prefer a check anchored to something that cannot move with the window — the object's own cloud
extent, or the target pose captured *before* the carry (above). Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— `placed_on_plate` line 356, called at 617; the failing widening experiment is recorded in its docstring
and was **not** shipped; 2026-09-15.

#### Judge a marginal landing by the settled cloud's **z-extent**, not by its xy offset

**Trigger**: a placement that looks correct in every positional sense and still scores 0. The instinct
is to read the landing *offset* — and on this failure mode the offset is the wrong quantity and will
mislead you, because the object can land *tilted* while perfectly centred.

```python
rgb4, d4, K4, E4 = observe()          # costs no sim steps
rest = points_near(rgb4, d4, K4, E4, BOWL_PROMPTS, goal_xy, 0.10,
                   float(plate["top"]) - 0.030, need=60, size_band=(0.040, 0.150))
ext_z = float(rest["hi"][2] - rest["lo"][2])      # compare against the object's TRUE height
```

For a bowl of true height 0.043 a settled `ext_z` of 0.044–0.049 means flat, and 0.051–0.054 means
several degrees of tilt. **Use the *ordering* of `ext_z`, never its magnitude** — the proxy is computed
from a cloud truncated below the support, so a genuinely flat bowl still reads ~0.044.

**Evidence**: across 18 logged runs the extent separated **every** outcome — `≤ 0.049` → reward 1.0 in
**12/12**, `≥ 0.051` → reward 0.0 in **6/6** — while the landing offset separated **nothing**: seed 62
*passed* at `xy_off = 0.0180` and seed 61 *failed* at `0.0086`. The offset also drifts 8–18 mm during
the fall in a direction that is not consistent (mostly −y on seeds 51–61, −x on 62/63/65), which is why
an attempt to compensate it was abandoned when an 8 mm input moved the landing by −9 mm to +35 mm.
**Do not tune to the landing offset.** Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_on_the_wooden_cabinet_and_place_it_on_the_plate/fix_code.py`
— the `VERIFY:` block, and that task's `findings.md` P5; 2026-09-16.

#### Never re-place after the release column stalls short of a reach wall

**Trigger**: a closed-loop placement correction that adds the last measured landing error to the next
release column, on a goal **near the edge of the arm's workspace**.

The correction is open-loop in the one variable that matters here. The plate sat at `x = 0.783` against
the arm's measured `x`-wall at `~0.750` (see `grasp.md`, "Order the list by where each azimuth puts the
RELEASE"): the shifted column went *past* the wall, the arm stopped 3.0–12.8 cm short, and the bowl was
released there — **0.15–0.24 m off the plate, destroying a placement that was already good**, while the
program printed `PLACED ON PLATE` and the simulator returned 0. The program already printed the
diagnostic (`cmd_err`) and merely did not act on it:

```python
got = tcp_xy()
cmd_err = float(np.linalg.norm(got - release_xy))
if cmd_err > 0.02:                 # the arm stopped short: this column is NOT reachable
    open_gripper()                 # releasing nowhere near the goal is worse than not releasing
    retreat(tcp, quat)             # opening at all - re-plan the column instead
    return "unreachable", None
```

**Evidence**: seeds 58, 60, 62 and 65 each logged a shifted `release_xy` at `x` up to `0.806` against
`release tcp achieved x = 0.750`, `cmd_err` 0.031–0.085, and each ended with the bowl 0.15–0.24 m off
the plate while the program believed it had succeeded. The guard above is the proposed repair and is
**documented, not shipped** — the shipped revision keeps the re-place path. Source: same `fix_code.py`
— descent/release block of `attempt` lines 585–596 prints `cmd_err` but does not gate on it; 2026-09-15.

#### A landing check can be HIJACKED by the support — it then reads a perfect landing and fails

**Trigger**: any "find object X near point p" measurement where another, **flatter object of a similar
class** sits at p. Above all: a placement check whose target is the *support surface* — a plate is a
shallow dish and answers the `"metal bowl"` prompt just as well as the bowl does.

The failure is **exact and silent**, which is what makes it worth a section:

```
seed 64:  "BOWL CENTRED ON PLATE" with dist_to_plate_centre = 0.000, z2 = -0.004
          ...and the run's last agentview frame shows the plate EMPTY
```

The servo reading equalled the *plate's own centre* on exactly the two runs that lost the placement
(seeds 64 and 57), and sat 5–12 mm away on every run that passed. Gate on **shape**, since that is the
one thing that separates a dish from a bowl:

```python
FLAT_REJECT = 0.020          # plate 0.011 m, cookie box 0.014 m, bowl 0.044 m
if min_h is not None:
    zlo, zhi = np.percentile(pts[:, 2], [2, 98])
    if float(zhi - zlo) < min_h:
        continue             # this is not the object, whatever the prompt said
```

**Counter-evidence — do NOT gate the carry *servo* the same way.** During the carry the payload is partly
behind the fingers, so a hard gate has nothing to hold onto. Making it a *preference* (gated first,
ungated fallback) still regressed seed 65: the gated pick chose a taller composite mask (bowl-over-plate)
that read `err = 0.005` at the first iteration, the servo stopped without correcting, and the bowl was
released 21 mm off-centre (reward 0) — while the ungated pick on the same code read `err = 0.046` and
corrected over two hops (reward 1.0). **Gate the landing check; leave the servo ungated.** Apply this
whenever the thing you measure *for* is the same kind of thing you measure *against*. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_on_the_cookie_box_and_place_it_on_the_plate/fix_code.py`
— `bowl_points` lines 320–352 (`min_h` gate), `measure_bowl` 396–401, landing check in
`carry_and_release`; 2026-09-15.

**A shape gate is not sufficient on its own — the *radius test* has the same hijack.** The rule above
says "gate on shape", and a height test plus a shape test still passes a payload **perched on the
support's rim**, for two compounding reasons: the mask bleeds over the support, so the payload's
measured *underside* reads at the support's top surface; and a radius test that accepts anything inside
the support's **outline** accepts a payload resting *on* that outline. The radius must be a **fraction
of the support's own measured outline radius**, not the outline:

```python
SUPPORT_R_FRAC = 0.65          # here: 0.040 m of a measured 0.061 m dish outline
if r < SUPPORT_R_FRAC * support_r and rise > 0.028 and c["lo"][2] > support["top"] - 0.004:
    return c                   # sitting IN the dish, not leaning on its edge
```

Measured on `libero_spatial_task/pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate`:
the pre-fix check reported "on plate" at `r = 0.043` — reward 0.000 — and the payload really was
balanced on the rim. Worse than a wrong reading: **the false positive terminated the retry loop after
one attempt**, so the episode ended on a placement the program believed had succeeded. The tightened
test reports `r = 0.009–0.014` and 15/15 seeds pass. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— `bowl_on_plate`, lines 509–532; 2026-09-16.

#### …and a measurement-driven servo must not gate its hops on a reachability probe

The servo in "When the offset is NOT constant across grasps" re-measures after every hop, which is what
makes it robust. Put a `tcp_reaches` gate inside that loop and you break it: a hop the arm cannot make
shows up as an *unchanged measurement*, and the next hop corrects it — but a probe that returns a false
negative aborts the loop instead. Measured: with a 2-hop probe gate the servo aborted 50 mm short on
seed 55 and released 66 mm off-centre on seed 60; without the gate, seed 55 places correctly. The
reachability re-probe rule belongs *before* the grasp (see `manipulation.md`, "A short reachability probe
is a false-negative generator"), not inside the servo. Source: same `fix_code.py` — `servo_bowl_over`
lines 469–501 (no `tcp_reaches` call); 2026-09-15.

### Physics Settling After Release

After releasing a grasped object, give the physics engine time to settle the object before the
episode's reward predicate fires. **A command buys sim time; an observation does not.**

```python
_CMD = {"p": None}                      # the last COMMANDED grip-site pose

def go(p, quat):                        # every Cartesian command goes through here
    p = np.asarray(p, dtype=np.float64).copy()
    _CMD["p"] = p
    goto_pose(p, quat)
    return p

def settle(quat, repeats=3):
    for _ in range(repeats):
        p = _CMD["p"]
        if p is None:                   # nothing commanded yet: hold what we measure
            cur = tcp()
            p = np.array([float(cur[0]), float(cur[1]), float(cur[2]) - GZ])
        go(p, quat)                     # redundant re-command at the SAME pose
```

Two rules about *which* pose, both learned the hard way: hold the pose you **COMMANDED**, in the
grip-site frame — not the one you measure, and not the raw `robot_cartesian_pos` (which sits `GZ`
higher; re-commanding it lifts the tool by `GZ` on every call). `goto_home_joint_position()`
invalidates `_CMD`, since after it no commanded pose is a valid hold target.

`get_observation()` / `segment_sam3_*` / `mask_to_world_points` advance **no** sim steps, so the
old form `open_gripper() ; for _ in range(3): get_observation()` settled nothing at all — it only
looked like settling. That is the same fact as `localize.perception-costs-no-sim-steps`, read in
the opposite direction: perception is *free* (so closed loops cost no clock), which means it is
also *inert* (so it cannot damp anything). Reach for a redundant `goto_pose` at the current pose
whenever you need the world to move: before the fingers open, after the release, and between
small post-release hops.

**Evidence**: the held bowl measured `off_from_goal=0.0045` immediately before `open_gripper()`
and `0.0416` immediately after — the fingers opened on a still-moving payload and the object
jumped 2.7–4.2 cm at the instant of release. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate/fix_code.py`
— `settle` lines 304–311; 2026-09-16.

**A hold that re-commands the *measured* pose is not idempotent — each call ratchets the tool, and the
release height drifts with the *number* of holds.** The servo lands short of its own target, so
`p = tcp_pos(); goto_pose(p)` is a closed loop through an overshooting controller, not a fixed point.
Measured on the same descent with the same payload, varying only how many post-release holds ran:
release at `gripz=0.053` (cmd 0.049, **+4 mm**, seed passed), `gripz=0.062` (cmd 0.051, **+11 mm**,
seed failed), `gripz=0.053` (cmd 0.051, +2 mm, passed). Eleven millimetres above a 12 cm plate is a
drop, not a placement — and nothing in a normal trace shows it, because the achieved height is printed
as if it were the commanded one. **Print the commanded and the achieved height on the same line** or
this term is invisible. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate/v6.py`
— `_CMD`/`go`/`settle` lines 159–185; 2026-09-16 (ingested as
`manipulation.re-command-the-last-commanded-pose-in-a-hold-not-the-measured-one`, a **correction** of
`transport.pass-sim-time-with-a-command-not-an-observation`, whose `settle` is the ratcheting form).

**…but the commanded-pose hold is *also* not a free win — it was measured, and it did not pay.** Two
full 15-seed dev sweeps of each variant (four draws) gave the commanded-pose hold **23/30** against the
shipped measured-pose hold's **26/30**. It does fix the seed whose failure the ratchet explains (that
seed fails both draws under the measured-pose hold and passes one of two under the commanded-pose hold),
but it loses another seed outright and one draw of a third. The plausible reason is the mirror of the
rule above: a hold that re-asserts a **command** keeps driving the tool toward it, so when the command
is itself slightly wrong — and a release command is `rest_z + measured_hang + drop`, i.e. derived from a
measurement — the servo shortfall that the measured-pose hold was accidentally absorbing is gone.
Neither number is separated from this task's demonstrated noise (identical code scored between 10 and 14
across four draws). So: **prefer the commanded pose when you need holds to be countable, or when the
command is known-good; do not adopt it expecting a score gain, and never judge either choice on a single
sweep.**

**Corollary — settle BEFORE you judge, not only before you release.** `open_gripper()` costs ~30 sim
steps and the payload spends most of them in free fall, so a cloud segmented immediately after it is a
measurement of a *moving* object. Worse, it fails **optimistically**: a falling bowl is already inside
the goal footprint's `xy` while still centimetres above the support.

```
seed 53: "placement check dxy=0.0113 (tol 0.045) z=0.0326 surf=-0.0021 -> ON PLATE"
         "bowl verified on the plate -- settling and stopping"
         reward 0.000        <- the bowl was still 3 cm above the plate when the check ran
```

The sequence is: retreat clear → **settle** → re-segment → judge. And match the acceptance band to the
cloud's age: a **raw** post-release cloud needs the strict band (`dxy ≤ 0.030`,
`surf − 0.025 ≤ z ≤ surf + 0.035`) because it is the one that can be mid-flight, while a loop-top
reading from an OBB centre can use the wider `dxy ≤ 0.045`. Getting this backwards is expensive in both
directions: judged too early, the program believes a placement it has not made; judged too strictly
later, it discards a placement it has. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_next_to_the_cookie_box_and_place_it_on_the_plate/fix_code.py`
— `on_plate` 557–574 (`strict` branch), `settle_at_rest` 575–583, call sites 739–760; 2026-09-16.

**NEVER call `goto_home_joint_position()` while holding a grasped object.** Going home
during transport opens the arm configuration and drops the object. Transport in one continuous
arc: lift → translate → descend → release.

| Object type | Transit height | Release height | Notes |
|---|---|---|---|
