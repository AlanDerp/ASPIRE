# Coordinator Ledger — libero_spatial_swap Fix Loop

SUITE=libero_spatial_swap
DEVELOPMENT_SEEDS=51-65
HELD_OUT_SEEDS=1-50
Repo commit at campaign start: 0a36d7a02abad08943f2124146d783fb253677b7
Campaign start: 2026-09-15

Task registry order (from `gen_progress.py`):
1. pick_up_the_black_bowl_between_the_plate_and_the_ramekin_and_place_it_on_the_plate
2. pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate
3. pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_cabinet_and_place_it_on_the_plate
4. pick_up_the_black_bowl_next_to_the_cookie_box_and_place_it_on_the_plate
5. pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate
6. pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate
7. pick_up_the_black_bowl_on_the_cookie_box_and_place_it_on_the_plate
8. pick_up_the_black_bowl_on_the_ramekin_and_place_it_on_the_plate
9. pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate
10. pick_up_the_black_bowl_on_the_wooden_cabinet_and_place_it_on_the_plate

## GPU Ledger (3-7 only; 0=SAM3, 1=GraspNet, 2=PyRoKi fixed)

| GPU | State | Task | Agent ID | Notes |
|---|---|---|---|---|
| 3 | **BLOCKED** | on_the_cookie_box | ae074d718f43d86b5 | Stage 1 done **13/15** (blocked 60, 64), promotion **0010 VERIFIED**; **Stage 2 NOT STARTED — disk below the 50 GB stop-line** |
| 4 | **IDLE** | — | — | on_the_stove COMPLETE **50/50 = 1.000** |
| 5 | **BLOCKED** | on_the_wooden_cabinet | acd20aed7c223e962 | Stage 1 done 15/15, promotion **0009 VERIFIED**; **Stage 2 NOT STARTED — disk below the 50 GB stop-line** |
| 6 | **IDLE** | — | — | on_the_ramekin COMPLETE **47/50 = 0.940** |
| 7 | **IDLE** | — | — | next_to_the_ramekin COMPLETE **37/50 = 0.740** |

Store the ledger note: GPUs 3 and 5 are retained by `on_the_cookie_box` and `on_the_wooden_cabinet`
respectively; both Stage 2 runs must go back to those GPUs when the disk blocker clears. GPUs 4, 6 and 7
are free and stay free — no substitute jobs are dispatched.

Queue: EMPTY — all ten registered tasks have now been dispatched.
- ~~on_the_wooden_cabinet~~ -> dispatched on GPU 5 (last), after top_drawer's Stage 2 completed

Completed (promotion + full 50-seed Stage 2 manifest) — 8 of 10:

| # | Task (short) | promotion | held-out (seeds 1-50) | failed held-out seeds |
|---|---|---|---|---|
| 1 | between_plate_and_ramekin | 0002 verified | **48/50 = 0.960** | 24, 41 |
| 2 | from_table_center | 0004 verified | **50/50 = 1.000** | — |
| 3 | top_drawer_wooden_cabinet | 0005 verified | **25/50 = 0.500** | 25 seeds (see event log) |
| 4 | next_to_cookie_box | 0003 verified | **50/50 = 1.000** | — |
| 5 | next_to_the_plate | 0001 verified | **50/50 = 1.000** | — |
| 6 | next_to_the_ramekin | 0008 verified | **37/50 = 0.740** | 5,7,9,11,12,14,27,31,34,37,38,47,48 |
| 8 | on_the_ramekin | 0007 verified | **47/50 = 0.940** | 6, 13, 30 |
| 9 | on_the_stove | 0006 verified | **50/50 = 1.000** | — |

Campaign held-out total so far: **357/400 = 0.8925**. Every held-out failure above is recorded as
OUTCOME ONLY — not diagnosed, not tuned against (held-out protocol).

Parked — Stage 1 + promotion complete, **Stage 2 NOT STARTED (disk blocker)**:
- Task 7 on_the_cookie_box (GPU 3) — dev **13/15** (blocked 60, 64; 57 unstable); promotion **0010
  VERIFIED**; `fix_code.py` md5 `95f6b15fb1b93e62e96b226955204ab7`
- Task 10 on_the_wooden_cabinet (GPU 5) — dev **15/15**; promotion **0009 VERIFIED**; `fix_code.py`
  sha256 `5f79f031178bc89332959b2333dbf3c77c440dcf56d777dfceb9fee4618df510`

Nothing is in flight. All ten tasks are dispatched and none is running; Stage 1 is finished for all
ten and every promotion is verified, so the only work left for the campaign is these two Stage 2 runs,
both gated on free disk.

## Dev-seed gate for every task

| # | Task (short) | dev seeds 51-65 | blocked | promotion | Stage 2 (held-out 1-50) |
|---|---|---|---|---|---|
| 1 | between_plate_and_ramekin | fixed 15/15 | none | 0002 VERIFIED | complete **48/50 = 0.960** (fails 24, 41) |
| 2 | from_table_center | fixed 15/15 | none | 0004 VERIFIED | complete **50/50 = 1.000** |
| 3 | top_drawer_wooden_cabinet | 6/15 -> 12/15 | 51, 56, 61 | 0005 VERIFIED | complete **25/50 = 0.500** |
| 4 | next_to_cookie_box | 0/15 -> 15/15 | none | 0003 VERIFIED | complete **50/50 = 1.000** |
| 5 | next_to_the_plate | 15/15 first try | none | 0001 VERIFIED | complete **50/50 = 1.000** |
| 6 | next_to_the_ramekin | 2/15 -> **13/15** (shipped revision re-swept) | 60, 62 | 0008 VERIFIED | complete **37/50 = 0.740** |
| 7 | on_the_cookie_box | **13/15** (57 unstable) | 60, 64 | 0010 VERIFIED | **BLOCKED — not started (disk)** |
| 8 | on_the_ramekin | 13/15 -> 15/15 | none | 0007 VERIFIED | complete **47/50 = 0.940** |
| 9 | on_the_stove | 15/15, no fix | none | 0006 VERIFIED | complete **50/50 = 1.000** |
| 10 | on_the_wooden_cabinet | 14/15 -> **15/15** | none | 0009 VERIFIED | **BLOCKED — not started (disk)** |

## BLOCKER (2026-09-15): disk below the 50 GB stop-line

`df` after the on_the_ramekin and next_to_the_ramekin Stage 2 runs finished: **46 GB available
(89% used)**, down from 72 GB. The campaign rule is explicit: below 50 GB, stop new dispatch and
report the blocker; never delete evidence or outputs to make room. **No new dispatch was started.**
Concretely:

- Task 10 `on_the_wooden_cabinet` has `fix_code.py` (sha256
  `5f79f031178bc89332959b2333dbf3c77c440dcf56d777dfceb9fee4618df510`, md5
  `8337469beed1dbc32533aa667fd3cd3c`, byte-identical in both ship locations, audited clean of
  forbidden APIs) and a **verified** promotion 0009, but its 50-seed held-out Stage 2 has NOT been
  run. It is the last missing manifest of the ten tasks.
- Task 7 `on_the_cookie_box` (GPU 3) was mid-Stage-1 when the line was crossed and was left running
  rather than killed: killing it would have destroyed in-flight evidence, which the protocol forbids
  even more firmly than it forbids new dispatch. **It has since finished Stage 1 at 13/15** (blocked
  seeds 60 and 64; seed 57 documented as unstable), its promotion **0010 is VERIFIED**, and it too is
  now parked with **Stage 2 NOT STARTED** — a new dispatch, covered by the same stop.
- Free space needed to finish: one 50-seed Stage 2 is ~20-25 GB on this suite, so task 10 alone needs
  roughly half the current free space, and task 7's Stage 2 needs the rest. **User action is required**
  — either free space on `/` (or point `outputs/libero_fix_loop_eval` at a larger volume) or
  explicitly authorize the coordinator to prune. Nothing will be deleted by the coordinator.

## Event Log

- 2026-09-15: GPU 3 subagent (on_the_cookie_box) returned. Stage 1 finished **13/15** on dev seeds
  51-65 with the shipped code: seeds 51-59, 61-63, 65 all reward 1.0; **seeds 60 and 64 hit the
  3-replay limit and are BLOCKED**, and **seed 57 is documented as UNSTABLE** (it fails ~2 in 3
  attempts with byte-identical commands, so it is not counted as a clean pass). Shipped `fix_code.py`
  md5 `95f6b15fb1b93e62e96b226955204ab7`. Disk re-checked after the task: **46 GB available — still
  below the 50 GB stop-line, so no Stage 2 was dispatched.** GPU 3 is retained by this task and parked.
  Promotion `0010_pick_up_the_black_bowl_on_the_cookie_box_and_place_it_on_the_plate` recorded +
  VERIFIED (4 skill files, 5 knowledge files; library
  be41c995fd18b9a8c7d6cf3a1d6b72967b655c87239ce0eaa7f6ac96e1c8e542).
  - Instances ingested (all --successful-seeds 51,52,53,54,55,56,57,58,59,61,62,63,65 --improved;
    four distinct top-level anchors so no two share an AST fingerprint):
    grasp.scan-the-pinch-radius-a-fixed-offset-from-the-rim-is-a-coin-flip (f1efe196…, ast 1f2cc644…,
    anchor `pinch_directions`),
    manipulation.a-short-reachability-probe-is-a-false-negative-generator (8d207477…, ast 2dc3f668…,
    anchor `tcp_reaches`),
    transport.a-landing-check-hijacked-by-the-support-reads-perfect-and-fails (1918d32b…, ast
    99470415…, anchor `bowl_points`),
    localize.take-the-centre-from-the-oriented-bounding-box-not-the-cloud-median (9d79b36e…, ast
    28566324…, anchor `obb_center_xy`).
  - Skill merges: grasp.md (new section "Scan the Pinch *Radius* — a Fixed Offset From the Rim Is a
    Coin Flip", incl. the toppled-bowl stop guard `if (b_hi - b_lo) > max(0.055, 1.35 * h_bowl):
    break`), transport.md (two subsections: the landing-check hijack — `FLAT_REJECT = 0.020`, plate
    0.011 m vs bowl 0.044 m, the false-success signature `dist_to_plate_centre = 0.000, z2 = -0.004`
    with an EMPTY plate in the frame — **plus the counter-evidence that gating the carry servo
    regressed seed 65 and must not be done**; and that a measurement-driven servo must not gate its
    hops on a reachability probe), localize.md (new `####` "Prefer the *oriented bounding box* centre
    over any cloud statistic" — OBB 0.744 vs median 0.721 on seed 51, 23 mm — with the ordering rule
    that the OBB must be fitted *after* the support clip), manipulation.md (new refinement "in a
    grasp-search loop the sink is close_gripper, so cap closes separately" — `MAX_CLOSES = 12` checked
    in *both* loops, plus the toppled-bowl stop guard, against seed 53's mid-motion
    `ValueError: executing action in terminated episode` and seed 60's 25 closes on one bowl).
  - The promotion's counter-evidence is deliberately recorded alongside the fix: gating the carry
    *servo* with the same shape test regressed seed 65 (released 21 mm off-centre, reward 0) because
    the payload is partly behind the fingers during the carry. Gate the landing check; leave the
    servo ungated.
  - **All ten registered tasks now have a verified promotion.** Two of them (7 and 10) still lack a
    Stage 2 manifest; both are parked on the disk blocker.

- 2026-09-15: Preflight re-verified. Ports 8114/8115/8116 = 404 (UP). GPUs 3-7 idle.
  Disk 182 GB avail. `gen_progress.py` regenerated: libero_spatial_swap 0/10 done, all pending.
  Goal-Swap (10/10 done) and Object-Swap (10/10 done) outputs and promotion ledgers preserved.
  Wave 1 dispatched: tasks 1-5 on GPUs 3-7.

- 2026-09-15: GPU 7 subagent (next_to_the_plate) returned. 15/15 dev seeds passed
  first try (`tries=1`), no BLOCKED.md. Stage 2 started on GPU 7 (same GPU), log
  `outputs/libero_fix_loop_eval/spatial_next_to_plate_stage2.log`. Seeds 01-02
  reward 1.000. Disk after task: 162 GB avail.
  Promotion `0001_pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate`
  recorded + VERIFIED (3 skill files, 5 knowledge files).
  - Instances ingested: localize.hollow-container-extent-midpoint-not-median,
    localize.screen-class-before-spatial-relation-for-same-mesh-twins,
    transport.track-by-position-continuity-after-a-release,
    transport.measure-carried-offset-sign-for-a-radial-wall-pinch.
  - Skill merges: transport.md ("Compensate the Release Pose for an Off-Centre
    Grasp" — sign is scene-specific), localize.md (container-centre variant,
    class-screen-first disambiguation, new position-continuity tracking section),
    grasp.md (lift re-read direction + akita bowl table row).

- 2026-09-15: GPU 3 subagent (between_the_plate_and_the_ramekin) returned. Initial
  6/15, fixed to 15/15 (9 seeds fixed: 55,56,58,59,61,62,63,64,65), no blockers.
  Stage 2 started on GPU 3, log
  `outputs/libero_fix_loop_eval/spatial_between_plate_and_ramekin_stage2.log`.
  Disk after task: 153 GB avail.
  Promotion `0002_...` recorded + VERIFIED (3 skill files, 5 knowledge files).
  - Instances: grasp.rank-radial-pinches-by-their-release-column,
    manipulation.solve-ik-success-is-not-reachability,
    localize.spatial-relation-goal-selection-by-midpoint-distance,
    localize.re-localize-every-attempt-after-a-failed-release.
  - Skill merges: grasp.md (radial-list ordering by release column + wall gate),
    manipulation.md (solve_ik != reachability; ladder the wall probe),
    localize.md (re-localize movable objects every attempt; spatial-relation
    goal selection by midpoint of ALL named references).

- 2026-09-15: GPU 6 subagent (next_to_cookie_box) returned. 0/15 -> 15/15, all 15
  seeds fixed, each on its FIRST replay attempt, no blockers. Stage 2 started on GPU 6,
  log `outputs/libero_fix_loop_eval/spatial_next_to_cookie_box_stage2.log` (pid 1727068).
  Disk after task: 150 GB avail.
  Promotion `0003_pick_up_the_black_bowl_next_to_the_cookie_box_and_place_it_on_the_plate`
  recorded + VERIFIED (4 skill files, 6 knowledge files; library
  44838b5d44dc993bdc2fe511b892b00af2d6d24185192a98edb4b76887a72536).
  - Instances ingested (all --successful-seeds 51..65):
    transport.servo-on-the-held-objects-own-cloud,
    localize.anchor-a-relational-targets-identity-to-its-last-position,
    localize.screen-masks-by-physical-feasibility-not-score,
    manipulation.bound-the-perception-budget-per-prompt,
    grasp.release-with-the-object-already-touching-the-surface.
  - Skill merges: transport.md (new subsection "When the offset is NOT constant across
    grasps, stop compensating it — servo on the held object's own cloud"),
    localize.md (new subsection "The relation is invalidated by your OWN action — lock
    identity to the last measured position" + new "Pick the gates by *physical
    feasibility*..." subsection under Screen-by-Geometry),
    manipulation.md (new "mask_to_world_points is where the budget actually goes"
    refinement under Budget API Calls), grasp.md (new "On a radial wall pinch, release
    with the object already *touching* the surface").
  - DEVIATION 3 below records a transcription error in one of these five instances and
    its correction.

- 2026-09-15: **Task 5 COMPLETE.** GPU 7 Stage 2 (`next_to_the_plate`) finished
  `status=complete n=50 passes=50 rate=1.000`,
  manifest `outputs/libero_fix_loop_eval/libero_spatial_swap/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate/runs/7e65efebb9e74efa/manifest.json`.
  First fully complete Spatial-Swap task (promotion 0001 + 50/50 held-out). `gen_progress.py`
  regenerated -> `21/26 tasks done | 4 need Stage 2 | 1 pending` (disk-found task list;
  benchmark discovery unavailable in this shell). Disk 147 GB.
  GPU 7 released and re-dispatched with wave-2 task `next_to_the_ramekin`
  (agent a2286ca71ca923b68).

- 2026-09-15: GPU 4 subagent (from_table_center) returned. Initial 12/15 (58, 59, 63
  failed); fixed to 15/15, no blockers, `attempts/` empty. Stage 2 started on GPU 4,
  log `outputs/libero_fix_loop_eval/spatial_from_table_center_stage2.log` (pid 1745007).
  Disk after task: 146 GB avail.
  Promotion `0004_pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate`
  recorded + VERIFIED (4 skill files, 4 knowledge files; library
  586511b23014bf42dfff1ba0a9163fa523863899e6943ec2d680b3fb375431a2).
  - Instances ingested (all --successful-seeds 51..65):
    grasp.pinch-the-wall-away-from-the-goal-so-the-payload-hangs-goal-side,
    manipulation.measure-the-tcp-not-the-commanded-pose,
    transport.do-not-chase-a-post-release-estimate-of-an-occluded-target.
    (Findings Pattern C — re-localise before each retry — was NOT ingested as a new
    instance: promotion 0002 already created
    localize.re-localize-every-attempt-after-a-failed-release covering the same
    principle. Its new contribution, the identical-air-gap diagnostic signature, was
    merged into that existing skill section instead. Avoids a duplicate instance.)
  - Skill merges: grasp.md (new "rank the walls by their alignment with the *goal
    direction*" subsection — the direction-free generalisation of 0002's x-ranking, same
    0.750 reach clamp confirmed independently), manipulation.md (new subsection on
    using the TCP measurement in planning, incl. the previously-undocumented ~1.2 cm z
    lag and the measured-z release descent), transport.md (new "Verify the Placement
    Against the Target Pose Measured BEFORE the Carry"), localize.md (stale-pose retry
    diagnostic appended to the re-localise section).

- 2026-09-15: GPU 5 subagent (top_drawer_wooden_cabinet) returned. Initial 6/15 ->
  **12/15 net**, with **three BLOCKED seeds (51, 56, 61)** — the campaign's first partial
  result. Stage 2 started anyway on GPU 5 (a generalizable `fix_code.py` exists), log
  `outputs/libero_fix_loop_eval/spatial_top_drawer_stage2.log` (pid 1788802). fix_code
  audited: 0 forbidden-API matches. Disk after task: 125 GB avail.
  Blocked-seed causes recorded verbatim from findings.md, NOT re-diagnosed by the
  coordinator: 51 and 61 = workspace limit (the same solve_ik hand-x clamp; required TCP x
  exceeds the envelope, "not fixable by control on these seeds"); 56 = the trust gate
  suppresses the only held-bowl mask, and the free-space offset itself is unreliable.
  Promotion `0005_...` recorded + VERIFIED (4 skill files, 5 knowledge files; library
  af145e37474b7adeaae35574e854caacdcab0417eb73df8db6029a2209e3d271).
  - Instances ingested (all --successful-seeds = the 12 passing dev seeds):
    localize.physical-sanity-gate-on-a-segmentation-of-a-held-object,
    grasp.ladder-the-pinch-descent-until-the-tcp-has-really-arrived,
    transport.re-measure-the-grasp-offset-in-free-space-after-the-lift,
    manipulation.detect-a-reach-clamp-do-not-fight-it.
    Four distinct top-level anchors (`is_trustworthy`, `profile`, `bowl_near`,
    `carry_and_place`) so no two instances share an AST fingerprint.
  - Skill merges: localize.md (held-object physical-sanity gate + its free-space
    asymmetry under Never-Re-Localize-While-Held), grasp.md (new "a *fixed-length* hop
    ladder lands short, because the arm tracks HIGH" refinement), transport.md
    (free-space offset re-measurement + the sign flip, under Compensate-the-Release-Pose),
    manipulation.md (new "detect a reach clamp from a *constant* residual — then stop, do
    not fight it").

- 2026-09-15: GPU 4 subagent (on_the_stove) returned. **Initial program already scored
  15/15** on dev seeds 51-65, every seed on its FIRST pinch candidate — no fix needed, no
  blocked seeds. Stage 2 started on GPU 4, log
  `outputs/libero_fix_loop_eval/spatial_on_the_stove_stage2.log` (pid 1823768). Disk after
  task: 104 GB avail.
  Promotion `0006_pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate` recorded
  + VERIFIED (3 skill files, 5 knowledge files; library
  bd5d73b2caa387c38cd599eeafde49a47fd50d4ae228e331c05c496739e0c789).
  - Instances ingested (all --successful-seeds 51..65):
    localize.select-by-the-named-supports-footprint-not-by-height-or-score,
    localize.screen-a-named-support-by-its-own-geometry,
    grasp.three-way-gap-gate-for-a-radial-wall-pinch,
    manipulation.one-retry-fits-the-episode-budget.
    (Findings Pattern 3 — order radial pinches by goal direction — was NOT ingested: it is
    the same principle as promotion 0004's
    grasp.pinch-the-wall-away-from-the-goal-so-the-payload-hangs-goal-side. Merged into that
    existing skill section as a third independent confirmation instead, which also removes
    the last excuse for a fixed azimuth since here the GOAL moves and the object does not.)
  - Skill merges: localize.md (two new subsections — support-footprint selection and
    screening the named support by its own geometry), grasp.md (calibrated three-way gap
    gate under Verify-a-Grasp-by-the-Measured-Gripper-Gap + third confirmation in the
    goal-direction wall-ranking section), manipulation.md (measure the retry cost by
    injecting the failure — 142 → 175 steps).

- 2026-09-15: GPU 6 subagent (on_the_ramekin) returned after a resume: initial 13/15
  (seeds 51, 61 failed) -> fix_code.py **15/15, no blocked seeds**; the two failures flipped
  0.000 -> 1.000 with landings 0.021 m and 0.010 m. Stage 2 started on GPU 6 (same GPU), log
  `outputs/libero_fix_loop_eval/spatial_on_the_ramekin_stage2.log` (pid 1856784). Disk after
  task: 82 GB avail.
  Promotion `0007_pick_up_the_black_bowl_on_the_ramekin_and_place_it_on_the_plate` recorded +
  VERIFIED (3 skill files, 4 knowledge files; library
  b753b37273e145cb6bf0f18c2cb4dfc563c6707141154d95e96572b96cbf6788).
  - Instances ingested (all --successful-seeds 51..65, --improved):
    localize.clip-a-stacked-objects-cloud-at-its-supports-measured-top (code_hash be38a6d5…),
    localize.anchor-a-spatial-relation-to-the-named-supports-own-measurement (dd97be00…),
    transport.height-gate-a-servoed-object-measurement-by-the-tool-z (237aef44…).
    Three distinct AST fingerprints (c3e6e4de…, e29386c5…, ae75712a…).
  - Skill merges: localize.md (new `####` "Anchor the relation to the *named support's own
    measurement*" under support-footprint selection, with the `table_z = min(lo[2])` counterexample;
    new `###` "A *stacked* object's mask bleeds through its support — clip the cloud at the support's
    measured top"), transport.md (the height-gated measurement window appended to "When the offset is
    NOT constant across grasps…", incl. the 0.134 m decoy lock-on counterexample), grasp.md (corollary
    that a servo-driven release de-thrones the release-column ordering; the 13/15 air-grasp on the
    promoted first candidate now costs one attempt and nothing else).
  - Findings' 4th pattern ("half the wall-pinch candidate list air-grasps") was recorded as an
    observation into grasp.md, not as a new instance — it is the library's existing
    "one side air-grasps, the mirrored side works" behaviour, already covered by
    grasp.radial-wall-pinch-candidates.

- 2026-09-15: GPU 7 subagent (next_to_the_ramekin) returned. Initial 2/15 -> **11/15 net**, with
  **four BLOCKED seeds (58, 60, 62, 65)** — the second partial result this campaign. Reported cause of
  the four: each landed *inside* the 0.035 m tolerance (0.019-0.032 m from the goal cell) and was then
  thrown away by the program's own recovery — `placed_on_plate` under-reports the landing by ~0.017 m
  (window narrower than the bowl), so the effective tolerance is ~0.018 m and the re-place path
  commands a release column at x = 0.768-0.834 against the ~0.750 m wall, releasing 3.1-8.5 cm short.
  **The subagent flagged that the shipped `fix_code.py` is NOT the revision its 11/15 sweep covered**
  (a post-sweep change of the final descent step, 14 mm -> 8 mm). That breaks the dev-seed gate Stage 2
  relies on, so the same agent was resumed (not re-spawned) to re-sweep the shipped revision on seeds
  51-65 and either keep the 8 mm file or revert to the measured 14 mm one, so the shipped artifact is
  a revision that was actually measured. Promotion 0008 is therefore **deliberately not begun yet** —
  it must anchor the final shipped revision.
  fix_code.py sha256 at the time of the request: 8df6e6db44f41e6ba5ff171af52613fe0754d3c3132d8ab0d5aa91ac85d1aedd.

- 2026-09-15: **Task 3 COMPLETE.** GPU 5 Stage 2 (`top_drawer_wooden_cabinet`) finished
  `status=complete n=50 passes=25 rate=0.500`,
  manifest `outputs/libero_fix_loop_eval/libero_spatial_swap/pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_cabinet_and_place_it_on_the_plate/runs/7490f832b88bf95a/manifest.json`
  (validated: 50 seed entries, all keys present, `identity.code_sha256` bound to the promoted
  `fix_code.py`). Failed held-out seeds: 1,2,3,4,5,9,10,11,13,14,16,17,21,24,26,27,28,29,31,32,36,37,45,48,50.
  Partially expected: its Stage 1 ended 12/15 with three BLOCKED seeds (51, 56, 61), two of which were
  recorded by the subagent as a workspace reach limit rather than a control defect — the lowest
  dev-seed ceiling in the campaign so far. Recorded as OUTCOME ONLY; not diagnosed, not tuned against
  (held-out protocol). Disk after task: 80 GB.
  GPU 5 released and re-dispatched with the last queued task `on_the_wooden_cabinet`
  (agent acd20aed7c223e962). `docs/progress/fix_loop_progress.md` regenerated by the eval runner.

- 2026-09-15: **Task 9 COMPLETE.** GPU 4 Stage 2 (`on_the_stove`) finished
  `status=complete n=50 passes=50 rate=1.000`,
  manifest `outputs/libero_fix_loop_eval/libero_spatial_swap/pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate/runs/1f5f58430ca46a27/manifest.json`
  (validated: 50 seed entries, `identity.code_sha256` 06b3b395…). Its Stage-0 program had already
  scored 15/15 on dev seeds with no fix, and it transfers: **50/50 held-out, zero failures**. Disk
  after task: 72 GB. GPU 4 is now **idle** — the queue is empty, so it is deliberately left
  unassigned rather than given a substitute job.

- 2026-09-15: GPU 7 subagent (next_to_the_ramekin) completed the requested re-sweep. The shipped
  `fix_code.py` (sha256 `8df6e6db44f41e6ba5ff171af52613fe0754d3c3132d8ab0d5aa91ac85d1aedd`,
  byte-identical in both ship locations) is **13/15** on dev seeds 51-65 (60, 62 fail), versus 11/15
  for the 14 mm-descent revision: the two flips are 58 and 65 fail->pass, and **no seed regressed**,
  so the 8 mm step was kept. The subagent's own per-seed attribution is worth recording verbatim in
  spirit: at the accept/reject boundary the step changed nothing (first-attempt landing moved <=2 mm
  on the 11 seeds that pass in both, 8 of them bit-for-bit identical), so 13 vs 11 is mostly
  run-to-run variation in the chaotic post-rejection retry, and 58/65 are *unstable*, not fixed.
  Promotion `0008_...` recorded + VERIFIED (3 skill files, 4 knowledge files; library
  dc6c2c7ce5399cc1295a16c969d8e04c379dc91bfe6690f1c7296936eca91afd).
  - Instances ingested: grasp.measure-the-carried-objects-hang-in-the-air-not-at-the-grasp
    (4f852137…, ast 7ad254da…), localize.find-an-ungroundable-reference-object-by-geometry-screened-by-table-level
    (f517683f…, ast 576ebf9e…), transport.a-verification-window-narrower-than-the-object-biases-the-check
    (339fe27a…, ast 0374b303…). The third is a **documented defect**, ingested with no development
    successes and no --improved flag, because the shipped `placed_on_plate` is what fabricates the
    bad verdicts; its value is the falsified widening experiment.
  - Skill merges: grasp.md (new "Measure the carried object's *hang* in the air, not at the grasp",
    incl. the silent-failure mode where a missing z floor makes the helper inert — the third
    independent appearance of "a measurement window needs a height gate"), localize.md (new "The
    *reference* object has no usable prompt at all — find it geometrically, screened by table
    level", the mirror of support-footprint selection), transport.md (two subsections: the
    verification-window bias and why widening is worse, and the proposed-but-unshipped guard against
    re-placing after the release column stalls short of the reach wall).
  - Findings' patterns 4 (release at goal minus the pinch offset) and 5 (rank pinches by release-column
    reachability) were NOT ingested — they restate transport.measure-carried-offset-sign-for-a-radial-wall-pinch
    (promotion 0001) and grasp.rank-radial-pinches-by-their-release-column (0002) respectively.
  - Stage 2 started on GPU 7 (same GPU), log
    `outputs/libero_fix_loop_eval/spatial_next_to_ramekin_stage2.log` (pid 1879280).

- 2026-09-15: **Task 8 COMPLETE.** GPU 6 Stage 2 (`on_the_ramekin`) finished
  `status=complete n=50 passes=47 rate=0.940`, manifest
  `.../pick_up_the_black_bowl_on_the_ramekin_and_place_it_on_the_plate/runs/cec8033f62368cfb/manifest.json`
  (`identity.code_sha256` 77ec15f9…). Failed held-out seeds **6, 13, 30** — recorded as OUTCOME ONLY,
  not diagnosed, not tuned against. Dev gate was 15/15.

- 2026-09-15: **Task 6 COMPLETE.** GPU 7 Stage 2 (`next_to_the_ramekin`) finished
  `status=complete n=50 passes=37 rate=0.740`, manifest
  `.../pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate/runs/c7dd65e29c3763a7/manifest.json`
  (`identity.code_sha256` 8df6e6db…, i.e. bound to the re-swept shipped revision). Failed held-out
  seeds 5, 7, 9, 11, 12, 14, 27, 31, 34, 37, 38, 47, 48 — OUTCOME ONLY, not diagnosed, not tuned
  against. This is consistent with its dev gate being the campaign's weakest complete one (13/15 with
  two of those flips the subagent itself called retry noise rather than an accuracy gain), and with
  the two defects it documented but could not ship a validated fix for (the +0.017 m placement-check
  bias and the re-place path that stalls past the reach wall).

- 2026-09-15: GPU 5 subagent (on_the_wooden_cabinet) returned. Initial 14/15 (seed 59 failed) ->
  **15/15, no blocked seeds**. Shipped file re-measured end-to-end after the final edit, so the file
  shipped is the file measured (md5 8337469b…, sha256 5f79f031…, byte-identical at both paths).
  Promotion `0009_pick_up_the_black_bowl_on_the_wooden_cabinet_and_place_it_on_the_plate` recorded +
  VERIFIED (2 skill files, 3 knowledge files; library
  fa02361eb4c385a42bed5ca7777e4c678953121381ce482a4ffefcb16f938a17).
  - Instances ingested: grasp.ladder-the-approach-too-re-read-the-tcp-every-hop (fb130324…, ast
    3c2481e4…), localize.the-raised-candidate-to-keep-follows-the-support-the-task-names (8f0cf9c7…,
    ast d39800cc…).
  - Skill merges: manipulation.md (new "The **approach** is usually the largest move in the pick —
    ladder it too", with the 0.250 m / 0.103 m probe table; and the loop-shaped home-recovery
    evidence — 9 home moves and a terminated episode on seed 59 vs exactly 1 on every shipped run),
    localize.md (new `####` "…and when the support lookup fails, the raised candidate to keep follows
    the support the task *names*", the min-vs-max wrong-object trap).
  - Findings P1 named `grasp.md` as its target file; it was merged into `manipulation.md` instead,
    because the existing `hop_to` material and the "Ladder Every Cartesian Motion Into ≤30 mm Hops"
    section — the exact section P1 says to extend — live there. Placement decision, not an omission.
  - Findings P2 (never recover by going home) was **not** ingested as a new instance: the store
    already carries `manipulation.no-home-retry-under-object` and
    `manipulation.no-home-with-positioned-object`. Its new contribution — the measured cost of a home
    reset *inside a candidate loop*, and the local-retreat replacement — was merged into that
    existing section instead.

## DEVIATIONS

1. **Phantom `debug_smoke` task (unresolved).** A subagent wrote a replay output to
   `outputs/libero_fix_loop/libero_spatial_swap/debug_smoke/` instead of the
   prescribed `outputs/libero_fix_loop_debug`. `gen_progress.py` scans that
   directory, so it now reports an 11th `libero_spatial_swap` task named
   `debug_smoke`, inflating the suite from 10 to 11 entries. NOT deleted: the
   creating subagent may still be live and the repo rule forbids deleting
   outputs without confirmation. To be raised with the user; the ten real tasks
   are tracked independently in this ledger.

2. **Instance-store extraction limit.** `cap/knowledge/ingest.py` requires the
   `--lines` snippet to parse standalone (it `.strip()`s the first line). The
   grasp-width lift check (P5) lives mid-`attempt()`, and `attempt()` is the only
   column-0 boundary in that region. `attempt()` was therefore ingested once, as
   the transport instance for P1; P5 is recorded in `grasp.md` and its
   `--effect` text rather than as a second instance with an identical AST
   fingerprint (which would be a duplicate rather than an abstraction).

3. **Coordinator transcription error, self-corrected (promotion 0003).** The first
   ingest of `transport.servo-on-the-held-objects-own-cloud` passed its `--effect`
   text in a double-quoted shell string containing backticks (`hop`, `tol`,
   `release_xy = tcp_xy()`). The shell treated them as command substitution and
   stripped those fragments from the recorded `observed_effect`. The other four
   instances in the same batch were unaffected (they contained no backticks).
   Correction: the corrupted YAML was copied to
   `/tmp/servo_instance_CORRUPT.yaml` (sha256
   `6d7760562d16ebb9189efba306ff93e1b79fa9cf529fd9bf10e70fe743697744`) for audit,
   removed (the store's `_write_immutable` refuses to overwrite differing
   content), and re-ingested with the intended text. No task evidence or output
   was deleted — only this coordinator-authored knowledge record, written minutes
   earlier in the same promotion. Later ingests use single-quoted `--effect`
   arguments.

4. **Instance anchored on an enclosing function (promotion 0007).** The clip
   pattern's executed code is lines 717-727 of `fix_code.py`, *inside* `run()`.
   `cap/knowledge/ingest.py` requires the snippet to parse standalone, and it is
   indented, so `--lines 717:727` raises `unexpected indent` (verified). The only
   column-0 boundary in that region is `def run(...)` at line 642, so the instance
   `localize.clip-a-stacked-objects-cloud-at-its-supports-measured-top` carries the
   whole 142-line `run()` body, and its `--effect` text states the exact executed
   line range. Same class of limitation as DEVIATION 2. No other promotion-0007
   instance shares its AST fingerprint (`c3e6e4de…`), so the store has no collision.

5. **Permission to re-open a finished Stage 1 (next_to_the_ramekin).** The GPU 7
   subagent shipped a `fix_code.py` that was *not* the revision its 11/15 dev sweep
   measured (one post-sweep change: final descent step 14 mm -> 8 mm). The campaign
   requires Stage 2 to evaluate an artifact whose dev-seed gate was measured on that
   artifact, so the same agent was resumed to re-sweep the shipped revision and
   settle which one ships. This is dev-seed work only (seeds 51-65); no held-out
   seed was, or will be, consulted, and no held-out code change results from it.

6. **A 4th development replay on seeds 60 and 62 (next_to_the_ramekin).** The
   subagent's Stage 1 hard limit is 3 replays per seed; the three seeds it left
   blocked had used their 3 when the first sweep was written. The re-sweep of the
   shipped revision (DEVIATION 5) necessarily re-ran every seed, so 60 and 62 now
   have 4 development replays. Both are still failures and the extra replay was
   used only to measure the shipped revision, not to search for a fix and not to
   raise the task's dev-seed score by retrying — the score moved because of the
   revision, and the agent independently flagged that two of the flips are retry
   noise rather than an accuracy gain. Recorded because the letter of the limit was
   exceeded, even though its purpose was not.

7. **A subagent relocated one of its own evidence directories
   (on_the_wooden_cabinet).** The Stage 1 agent moved the failing Stage-0 replay output
   `trial_59` to `.../attempts/stage0_baseline_trial_59_reward_0.000` so that a Stage 2
   parser cannot confuse the `reward_0.000` baseline directory with the `reward_1.000`
   fixed run for the same seed. Nothing was deleted — the directory was renamed within
   the task's own workspace, and the move is documented in the subagent's return.
   Recorded because the campaign forbids deleting or overwriting outputs, and a move is
   adjacent to that.

8. **The 50 GB stop-line was crossed (see BLOCKER above).** Dispatch stopped
   immediately on detection and the last task's Stage 2 was not started. This is a
   protocol-mandated halt rather than a departure from procedure, but it is recorded
   because it leaves the campaign incomplete: nine of ten tasks have held-out
   manifests, task 10 does not, and task 7's Stage 2 is also unstarted. No evidence or
   output was deleted to make room.
