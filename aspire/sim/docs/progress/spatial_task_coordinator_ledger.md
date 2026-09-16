# Coordinator Ledger — libero_spatial_task Fix Loop

SUITE=libero_spatial_task
DEVELOPMENT_SEEDS=51-65
HELD_OUT_SEEDS=1-50
Repo commit at campaign start: 0a36d7a02abad08943f2124146d783fb253677b7 (branch FGRebuild)
Campaign start: 2026-09-16

Knowledge/actor mode: unchanged (`default.mode: off`, shadow-operation as described in
`main-agent-prompt.md` §6). No factual-grounding / dynamic-v2 feature was enabled or
configured — nothing in the repository defines such a switch, so the existing settings are
used verbatim.

## Preflight (2026-09-16)

| Item | Value |
|---|---|
| Perception ports 8114 / 8115 / 8116 | 404 / 404 / 404 (**UP**) |
| GPUs 3-7 compute procs at start | 0 on every GPU (idle) |
| Free disk `/` | 177 GB avail (58% used) |
| Suite slate | `outputs/libero_fix_loop/libero_spatial_task/` absent; `outputs/libero_fix_loop_eval/libero_spatial_task/` absent |
| `gen_progress.py` | `libero_spatial_task 0/10 done`, all ten `pending` |

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

| GPU | State | Task | Notes |
|---|---|---|---|
| 3 | EVAL | next_to_the_ramekin | Stage 1 **15/15**, promotion **0007 VERIFIED**; Stage 2 **complete 48/50** (run `026de13c06dfe388`, log `spatial_task_next_to_ramekin_stage2.log`) — held-out failures on seeds 10 and 46, both `completed=0`; GPU now idle |
| 4 | EVAL | on_the_ramekin | Stage 1 **15/15** then **14/15** on a byte-identical repeat sweep (**29/30** combined), promotion **0010 VERIFIED**; Stage 2 **complete 41/50** (run `d47c03b635b81424`) — held-out failures on seeds 10, 18, 21, 22, 27, 40, 41, 43, 44, all `completed=0`; GPU idle |
| 5 | EVAL | on_cookie_box | Stage 1 **15/15** (zero fix iterations), promotion **0006 VERIFIED**; Stage 2 **complete 47/50** (run `a9822c6b28ae68ab`) — GPU idle |
| 6 | EVAL | on_the_wooden_cabinet | Stage 1 **11/15** with 3 BLOCKED seeds (53, 56, 61), promotion **0009 VERIFIED**; Stage 2 **complete 47/50** (run `5734f4475347a652`) — GPU idle |
| 7 | EVAL | on_the_stove | Stage 1 **14/15**, then a full repeat sweep of both v5 and v6 (`rep5`/`rep6`); promotion **0008 VERIFIED**, **v5 shipped unchanged**. Stage 2 **complete 36/50** (run `1027ae9586cb5a01`) — GPU idle |

Queue: **empty, and the campaign is finished.** Stage 1 complete for all ten tasks, all ten promotions
VERIFIED (0001–0010), and all ten Stage 2 evals `status=complete` — **442/500 held-out trials (88.4%)**.
GPUs 3–7 were released as each eval finished; all five are idle and nothing further was dispatched onto
them.

### Stage 2 (held-out seeds 1-50) results

| Task | GPU | Run ID | Passes | Rate |
|---|---|---|---|---|
| pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate | 7 | `07c56ad6eafa444b` | **50/50** | 100% |
| pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_cabinet_and_place_it_on_the_plate | 5 | `4f1d6c15887ef077` | **49/50** | 98% |
| pick_up_the_black_bowl_between_the_plate_and_the_ramekin_and_place_it_on_the_plate | 3 | `954a62be143ef2d9` | **47/50** | 94% |
| pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate | 4 | `b4785212294799a8` | **41/50** | 82% |
| pick_up_the_black_bowl_next_to_the_cookie_box_and_place_it_on_the_plate | 6 | `d39417005b795d5b` | **36/50** | 72% |
| pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate | 3 | `026de13c06dfe388` | **48/50** | 96% |
| pick_up_the_black_bowl_on_cookie_box_and_place_it_on_the_plate | 5 | `a9822c6b28ae68ab` | **47/50** | 94% |
| pick_up_the_black_bowl_on_the_wooden_cabinet_and_place_it_on_the_plate | 6 | `5734f4475347a652` | **47/50** | 94% |
| pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate | 7 | `1027ae9586cb5a01` | **36/50** | 72% |
| pick_up_the_black_bowl_on_the_ramekin_and_place_it_on_the_plate | 4 | `d47c03b635b81424` | **41/50** | 82% |

**Campaign total: 442/500 held-out trials = 88.4%**, all ten runs `status=complete`.

Dev-to-held-out relationship, all ten tasks (dev is the shipped `fix_code.py`; `on_the_ramekin` and
`on_the_stove` report both sweeps where a repeat was run):

| task | dev (51–65) | held-out (1–50) | note |
|---|---|---|---|
| next_to_plate | 15/15 | 50/50 | no gap |
| in_the_top_drawer… | 15/15 | 49/50 | no gap (single-seed miss) |
| next_to_the_ramekin | 15/15 | 48/50 | −4 pts; both misses `completed=0` |
| on_cookie_box | 15/15 | 47/50 | −6 pts |
| on_the_wooden_cabinet | **11/15** (3 BLOCKED) | **47/50** | **+21 pts — dev badly *under*-stated it** |
| between_plate_and_ramekin | 13/15 | 47/50 | 94% vs 87% dev — no drop; the two dev-blocked seeds did **not** cost held-out points at a higher rate |
| from_table_center | 13/15 | 41/50 | −5 pts, on the two dev seeds blocked by the kinematic x-clamp |
| on_the_ramekin | 14/15 (15/15 + 14/15 = 29/30) | 41/50 | −14 pts — the largest clean-dev-to-held-out drop |
| next_to_the_cookie_box | **9/15** (7/15 re-measured initial — see DEVIATION 1b) | 36/50 | **+12 pts — held-out *better* than dev** |
| on_the_stove | 14/15 | **36/50** | **−22 pts — dev badly *over*-stated it** |

**The claim recorded here at four tasks — "every task that reached 15/15 dev held ≥98% held-out" — is
FALSIFIED by the wave-2 results and is withdrawn.** Five tasks reached 15/15 dev on the shipped file
(`next_to_the_ramekin`, `on_cookie_box`, `on_the_ramekin` on its first sweep, plus wave-1's
`next_to_plate` and `in_the_top_drawer…`); they landed at **100%, 98%, 96%, 94% and 82%**. The 82% is
`on_the_ramekin`, which then scored 14/15 on a byte-identical repeat sweep — a clean dev sweep is no
guarantee of anything above 8-in-10 held out. In the other direction `on_the_wooden_cabinet` shipped a
dev program *worse* than its own initial code, with three seeds it could not repair, and reached **94%**
held out — higher than two of the 15/15-dev tasks. And `on_stove`, whose 14/15 I spent ~38 min of GPU 7
re-measuring precisely because its worker's evidence was ambiguous, is the campaign's joint-weakest at
72%, tied with `next_to_the_cookie_box` — whose *own* dev score was 9/15, the worst of the ten.

The honest summary is that **dev score is a weak predictor in both directions on this suite**, and the
dev-to-held-out gap is not a fixed conversion. At 15/15 dev the held-out rate spans 82–100%; across
9–14/15 dev it spans 72–94%, and the top of that lower band (94%) belongs to an 11/15 program while the
bottom of the upper band (82%) belongs to a 15/15 one — the two bands overlap almost completely. Three
of the ten tasks scored *better* held out than on dev (the largest, `next_to_the_cookie_box`, by 12
points). Nothing here supports ranking the ten shipped programs by their dev numbers. Sample sizes are
the obvious caveat in both directions: 15 dev seeds and 50 held-out trials, on tasks whose own workers
documented byte-identical-code flips of 1–2 seeds per sweep.

## Event Log

- 2026-09-16: Preflight re-verified. Ports 8114/8115/8116 = 404 (UP). GPUs 3-7 idle
  (0 compute procs each). Disk 177 GB avail. `gen_progress.py` regenerated:
  `libero_spatial_task 0/10 done`, all pending; no prior output/eval/promotion
  directories for this suite (clean slate confirmed). Goal-Swap, Object-Swap and
  Spatial-Swap outputs untouched.

- 2026-09-16: Wave 1 dispatched — five Stage 1 subagents, one per GPU, for tasks 1-5
  (between_the_plate_and_the_ramekin→GPU 3, from_table_center→GPU 4,
  in_the_top_drawer_of_the_wooden_cabinet→GPU 5, next_to_the_cookie_box→GPU 6,
  next_to_the_plate→GPU 7). All five sent in one message. Coordinator now idle;
  no polling.

## Deviations

- **DEVIATION 1 (from_table_center, GPU 4): the dev baseline was not taken on `initial_code.py`.**
  The worker's `initial_code.py` records a single dev trial (seed 51 = 0.000); the 15-seed baseline
  sweep was instead run on its first *fix candidate*. So the task has no 15-seed pre-fix baseline on
  record — only one dev seed of it. The final shipped sweep (13/15) is unaffected and is what Stage 2
  evaluates, but the "initial → shipped" delta for this task cannot be quoted as a clean 15-seed
  number. Recorded here rather than reconstructed after the fact.

- **DEVIATION 1b (next_to_cookie_box, GPU 6): the Stage 0 baseline on record was measured on a
  different file than the one on disk.** The Stage 0 notes recorded 9/15, but the `initial_code.py`
  on disk is a *later* revision (its `lift_and_confirm` samples the lift 3 times; the file behind
  `initial_seed_*.log` sampled 4). The worker re-measured like-for-like on the on-disk file:
  **7/15**, and shipped **9/15**. No `initial → shipped` delta is clean here either.

- **DEVIATION 2 (disk policy, user-approved): Stage 1 scratch is redirected to the `/mnt` volume for
  the remaining tasks.** Free space on `/` fell 177 GB → 124 GB over the first four tasks
  (≈18.5 GB/task: ~10.5 GB Stage 2 + ~8 GB Stage 1). Remaining demand was ≈142 GB against 124 GB
  free — a shortfall of ~18 GB that would have landed during tasks 9-10. A second volume exists
  (`/dev/nvme0n1p1`, 1.8 TB, 1.6 TB free, mounted `/mnt`; `/mnt/nimloth` is user-writable).
  **The user chose, from three options, to redirect Stage 1 scratch to `/mnt/nimloth/aspire_scratch/`
  rather than delete any prior-campaign output.** Under this policy:
  - Stage 1 debug output for tasks 6-10 goes to `/mnt/nimloth/aspire_scratch/<task>/` (~8 GB/task).
  - Stage 2 eval output stays at the canonical `outputs/libero_fix_loop_eval/` (so `gen_progress.py`
    and the suite record are untouched), as do `fix_code.py` and `findings.md` under
    `outputs/libero_fix_loop/`.
  - Nothing is deleted or moved; the four tasks already debugged under `outputs/libero_fix_loop_debug/`
    stay where they are. Cost: the debug artifacts for tasks 6-10 live on a different volume, and the
    final report must say so.


## Event Log (continued)

- 2026-09-16: GPU 7 subagent (`next_to_plate`) returned. Initial 14/15 (seed 53 failed), fixed to
  **15/15**, no blocked seeds. Shipped `fix_code.py` md5 `9d1a8d64…`, sha256 `94f35672…`,
  byte-identical in both ship locations; source hash recorded on the ingested instance matches.
  `attempts/` empty. Stage 2 started on GPU 7 (same GPU), log
  `outputs/libero_fix_loop_eval/spatial_task_next_to_plate_stage2.log`; first seed 01 running.
  Promotion `0001_pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate` recorded +
  VERIFIED (3 skill files, 5 knowledge files; library
  88886173f569f929976fdbcf7866453f6db097f6cbc40987409b1a566a284568).
  - Instances ingested (all `--successful-seeds 51..65`):
    `transport.gate-the-carried-payload-window-by-a-fraction-of-the-hang` (`--improved`),
    `transport.end-a-carry-loop-on-a-perception-only-placement-check` (`--improved`),
    `localize.take-the-relation-from-the-runtime-language-not-the-task-name` (`--improved`),
    `grasp.abandon-a-pinch-wall-after-two-consecutive-air-closes` (no `--improved`; budget guard,
    not a reward flipper). Four distinct top-level anchors (`held_cloud`, `bowl_on_plate`,
    `pick_ramekin_and_target`, `grasp_bowl`) so no two share an AST fingerprint.
  - One findings pattern was deliberately **NOT** ingested: "lock identity inside the CLASS pool,
    never by raw proximity to the anchor" (`choose_target`). Its principle is already carried by
    `localize.anchor-a-relational-targets-identity-to-its-last-position` (promotion 0003 of the
    spatial-swap campaign); its new contribution — that a raw proximity lock can capture a
    *different-class* object (the ramekin at 0.112 m) and must therefore be confined to the class
    pool — was merged into that existing `localize.md` section instead. Avoids a duplicate instance.
  - Skill merges: `transport.md` (third load-bearing detail added to "When the offset is NOT
    constant across grasps…" — the depth floor must scale with the hang, plus footprint rejection
    of a merged mask; and a new `####` "…and let the check *end the loop*" under the pre-carry
    verification section), `grasp.md` (fourth consequence added to the pinch-radius scan: abandon a
    wall after two consecutive air closes), `localize.md` (new `###` "In a `_task` suite the relation
    comes from the RUNTIME LANGUAGE — the task name lies", inserted ahead of the class-screen
    section; plus the class-pool guard merged into "The relation is invalidated by your OWN action").
  - Note for the record: the `_task` remap is confirmed empirically and is the campaign's first
    hard fact about this suite — `env.handle.task_language` reads "…next to the **ramekin**…" for
    `pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate` while the task identifier
    says *plate*. The same identifier in `libero_spatial_swap` means the plate relation.

- 2026-09-16: GPU 4 subagent (`from_table_center`) returned. Shipped `fix_code.py` md5
  `77459c1bd2571a339b615e00b797edea`, sha256 `effec801fc9c43e68c0e8d7b783e6ed917f6c304e99807e8f9b0f9121707afb1`,
  617 lines, byte-identical in both ship locations. Final dev sweep **13/15** (seed 51 and 54-65
  = 1.000; seeds **52, 53** = 0.000 in every attempt, 3 replays each, `attempts/seed_52_BLOCKED.md`
  and `seed_53_BLOCKED.md` written). Both blocked seeds are **kinematic**: their plate sits at
  x 0.757 / 0.781, past the arm's ~0.750 x clamp, so the tool stalls with the bowl's base still
  1.2-1.5 cm above the plate top and releases against the rim. Dev baseline deviation recorded above.
  Stage 2 started on GPU 4 (same GPU), log
  `outputs/libero_fix_loop_eval/spatial_task_from_table_center_stage2.log`.
  - `_task` remap confirmed a **second** time on this task: the runtime language is "Pick the akita
    black bowl next to the **plate** and place it on the plate" while the identifier says
    *from_table_center*. Two bowl-sized containers exist at `(0.589, 0.01)` and `(0.67, 0.30)`;
    picking the table-centre one scores 0.000 and the plate-adjacent one 1.000 with identical carry
    code. The remap moves which object is the target, not just its colour.
  - Promotion `0002_pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate` recorded +
    VERIFIED (1 skill file, 3 knowledge files; library
    `46074666cfcae1169d1d2dd909dbb0f48def3d03ed2f88f6aaab0b186da5473f`).
    - Instances ingested (all `--successful-seeds 51,54..65` = the 13 passing dev seeds):
      `transport.close-the-placement-loop-on-the-payloads-own-measured-base` (`--improved`, anchor
      `place_on_target` lines 314-364) and `transport.pass-sim-time-with-a-command-not-an-observation`
      (`--improved`, anchor `settle` lines 304-311).
    - Third findings pattern **NOT** ingested (duplicate principle): "the tool frame and the state
      frame are different; invert the offset once, centrally" — already carried by
      `manipulation.tcp-offset-inversion` (code `tcp_pos` = ee + 0.1*R[:,2]) and by
      `manipulation.md` §"Measure the TCP, Not the Hand". No new contribution, so no instance.
    - Skill merges: `transport.md` only (3 edits) — (a) **corrected** §"Physics Settling After
      Release", which previously prescribed `open_gripper(); for _ in range(3): get_observation()`.
      That loop settles **nothing** because perception advances no sim steps; it now specifies the
      redundant-`goto_pose` `settle()` and states the inversion of
      `localize.perception-costs-no-sim-steps`; (b) new `####` "Close the *placement* loop on the
      payload's own measured base" next to the servo section, with the sign-flip measurement and the
      three load-bearing details; (c) a cross-reference at the end of "Set the Release Height From
      the Support's Own Surface AND the Grasp Offset" telling the reader that when the offset does
      not reproduce, the *shape* of that recipe is wrong — do not tune the constant.
    - One instance was re-filed during this promotion: `settle` was first ingested under the
      `manipulation` vertical, then moved to `transport` (its knowledge is actually carried by
      `transport.md`, and `manipulation` already owns the TCP-frame pattern). The `manipulation`
      copy was removed; no duplicate id remains.

## Campaign fact — the `_task` remap, measured on all five wave-1 tasks

Recorded from the runtime `env.handle.task_language` string each worker's dev logs carry. **Not one
identifier's implied relation matches its instruction.**

| task identifier (`libero_spatial_task`) | runtime instruction |
|---|---|
| `…next_to_the_plate…` | "Pick the akita black bowl next to the **ramekin** and place it on the plate" |
| `…from_table_center…` | "Pick the akita black bowl next to the **plate** and place it on the plate" |
| `…in_the_top_drawer_of_the_wooden_cabinet…` | "Pick the akita black bowl **on the top of the wooden cabinet** and place it on the plate" |
| `…next_to_the_cookie_box…` | "Pick the akita black bowl **on the stove** and place it on the plate" |
| `…between_the_plate_and_the_ramekin…` | "Pick the akita black bowl **not** between the plate and the ramekin and place it on the plate" |

Two things follow. (1) The remap changes the **support** as well as the relation (`top drawer` → *top
of the cabinet*; `cookie box` → *stove*), so the reference object must come from the string too.
(2) The relation can be **negated** — `…between…` maps to *"not between"* — which no identifier-based
selector can express. Cross-check note: `next_to_the_cookie_box`'s worker spent Stage 1 localizing a
*stove*, which looked like a wrong-file deviation until the runtime string confirmed the remap. It was
correct. Merged into `.claude/libero/skills/localize.md` §"In a `_task` suite the relation comes from
the RUNTIME LANGUAGE".

## Promotions 0003-0005 (wave-1 tasks on GPUs 3, 5, 6)

| Promotion | Task (GPU) | Dev result | Skill files | Knowledge | Library hash |
|---|---|---|---|---|---|
| 0003 | between_the_plate_and_the_ramekin (3) | 13/15; seeds 62, 63 blocked | 3 | 3 | `ab3fd488…` |
| 0004 | in_the_top_drawer_of_the_wooden_cabinet (5) | **15/15** (0/15 initial) | 3 | 2 | `41a81758…` |
| 0005 | next_to_the_cookie_box (6) | **9/15** (7/15 re-measured initial) | 3 | 3 | `7bb7897c…` |

Instances ingested (7 across the three promotions, all with `--successful-seeds` set to the seeds that
actually pass on the shipped file):

- `grasp.calibrate-the-hold-test-to-the-measured-populations-and-keep-it-one-sided` — the air/hold
  boundary belongs in the measured gap between the populations (air 0.011-0.016 vs one-pad wall pinch
  0.042-0.122; the nominal 0.05 half-opening sits *inside* the hold population), and the post-lift test
  must be one-sided for a wall pinch because a large closing delta is settling, not loss.
- `manipulation.count-your-own-motion-against-the-episode-horizon` — shadow the API to count commands
  (goto_pose ≈30 steps, each gripper command exactly 30, one attempt ≈1400 of a 4000 horizon) and gate
  *retries*, never a first attempt.
- `manipulation.a-small-cartesian-command-is-not-executed-bracket-the-hop-size` — realised-step table
  (0.020 m → 0.0079; 0.045 → 0.033; 0.10 → 0.10) and "stop on progress toward the target, not on raw
  motion" (±3 mm oscillation at a kinematic limit defeats a did-it-move test).
- `manipulation.the-score-is-the-final-state-never-act-after-a-placement` — the reward is the last
  inner step's predicate, so any iteration after a successful release can only destroy it.
- `transport.judge-a-release-only-on-a-settled-scene` — the post-`open_gripper()` cloud is a
  measurement of a falling object and fails optimistically; settle, re-segment, then judge strictly.
- Two further instances were declined as duplicates after screening (the TCP-vs-hand frame, already
  `manipulation.tcp-offset-inversion`; and the commanded-vs-measured TCP, already
  `manipulation.measure-the-tcp-not-the-commanded-pose`).

Skill merges (9 edits across `grasp.md`, `manipulation.md`, `transport.md`, `localize.md`), of which
two **corrected wrong guidance already in the library** rather than adding to it:

1. `transport.md` §"Physics Settling After Release" prescribed `open_gripper(); for _ in range(3):
   get_observation()` — a loop that settles **nothing**, because perception advances no sim steps.
   Replaced with the redundant-`goto_pose` `settle()`.
2. `grasp.md` §"Verify a Grasp by the Measured Gripper Gap" prescribed `AIR_GRASP_WIDTH = 0.05` and a
   two-sided `width + SLIP_DELTA` bound — both of which reject the best available grip on a bowl wider
   than the gripper. Scoped to two-pad/friction grasps, with the one-pad wall-pinch populations given
   alongside and an explicit "scope it, do not delete it" for the friction case.

Also merged: the `_task` remap table incl. the negated relation (`localize.md`); the placement
closed-loop on the payload's own base and the "pinch-time direction, in-air magnitude" split of the
off-centre offset (`transport.md`); the sub-floor branch-swap that *flicks* a pinched payload and the
spreading contact signature whose guard must have the right sign (`grasp.md`); the loop-head "already
placed → stop" guard and the command-counting budget (`manipulation.md`); the rim pinch's three
aperture-sequence failure signatures and the warning that loosening `CREEP_TOL` hides the failure
(`grasp.md`).

Pre-existing defect noticed while editing, not introduced by this campaign: `grasp.md` has two
identical `## Gate a Closed Gripper on Aperture AND Finger Height` headings (lines 741 and 1013 before
this campaign's edits). Left alone — out of scope for a promotion, but it should be merged eventually.


## Wave 2 dispatch (2026-09-16)

GPU 4 and GPU 7 came free after `from_table_center` and `next_to_plate` finished Stage 2, with
promotions `0002` and `0001` VERIFIED, satisfying the promotion gate. Dispatched the queue head:

- **GPU 7** ← task 6 `pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate`
- **GPU 4** ← task 7 `pick_up_the_black_bowl_on_the_cookie_box_and_place_it_on_the_plate`

Both subagents were given the DEVIATION 2 scratch redirect in their Stage 0 preamble (see below),
plus two campaign facts measured in wave 1: (a) the `_task` identifier is an opaque dispatch key
and the runtime `env.handle.task_language` can change both the relation and the named *support*
(so `on_the_cookie_box` must not be assumed to mean "inside a cavity"); (b) the shipped fix for
`in_the_top_drawer…` localizes a *cabinet top*, and the `next_to_cookie_box` task's own dev logs
show the runtime instruction is "on the stove" — the identifier lied in both cases.

### DEVIATION 2 operational detail (user-approved option A)

Stage 1 scratch for the wave-2 tasks points at the `/mnt` volume:

```
DEBUG_DIR="/mnt/nimloth/aspire_scratch/libero_spatial_task/<task>"
```

instead of `outputs/libero_fix_loop_debug`. Consequence to carry into the final report: **the
Stage 1 debug artifacts for tasks 6-10 live on a different volume from every other task's.** The
canonical artifacts (`outputs/libero_fix_loop/<suite>/<task>/{initial_code.py,fix_code.py,findings.md,attempts/}`,
`outputs/working_codes/…`, and `outputs/libero_fix_loop_eval/…`) stay on `/` and are unaffected, so
`gen_progress.py` and the suite record are untouched. Nothing existing was moved or deleted.

## Promotion 0006 — `pick_up_the_black_bowl_on_the_cookie_box_and_place_it_on_the_plate`

VERIFIED, library `7bb7897c…` → `0cd2703e…`. Stage 1 was **15/15 on the initial program with zero
diagnose-fix iterations** — the first task in this campaign where nothing needed fixing. `attempts/`
holds no BLOCKED.md.

**Duplicate screening (7 reported patterns → 1 ingested).** The worker reported P1–P7; six of them map
onto library entries that already exist, and on inspection they are *confirmations with new numbers*
rather than new knowledge:

| pattern | existing entry | disposition |
|---|---|---|
| P1 identifier ≠ runtime instruction | `localize.take-the-relation-from-the-runtime-language-not-the-task-name` | merge (new row + the "product word does not ground at all" evidence) |
| P2 same-class decoy beats the target on every score | `localize.select-by-the-named-supports-footprint-not-by-height-or-score` | **no edit** — the entry already states "the DECOY wins on most seeds" (0.891–0.926 vs 0.855–0.922) |
| P3 pinch the wall away from the goal | `grasp.pinch-the-wall-away-from-the-goal-so-the-payload-hangs-goal-side` | no edit — already the entry's subject |
| P4 accept a wall pinch on retention | *none* | **INGESTED** |
| P5 hang measured in the air, not at the grasp | `grasp.measure-the-carried-objects-hang-in-the-air-not-at-the-grasp` | merge (evidence: the stale error's *sign* is scene-dependent, ~15 cm the other way) |
| P6 screen class and support by geometry | `localize.screen-sam3-candidates-by-geometry`, `localize.screen-a-named-support-by-its-own-geometry` | no edit |
| P7 OBB centre over the cloud median | `localize.take-the-centre-from-the-oriented-bounding-box-not-the-cloud-median` | no edit — the worker itself notes it *exactly reproduces* the entry's measured pair (median 0.721 / OBB 0.744) |

**The one ingested instance:** `grasp.gate-a-wall-pinch-on-retention-when-the-hold-floor-is-inside-reading-noise`
(`--lines 269:351`, anchored on the whole top-level `def grasp_bowl` so the slice parses standalone;
`--successful-seeds 51…65`, `--improved`).

### The promotion also *corrects* wave-1 guidance — for the second time this campaign

Promotion 0003 asserted: *"The one test that is always valid: `if w2 < AIR_W: return None`."* This task
falsifies the word "always". Its lift reading floors at **0.052 against an `AIR_W` of 0.050** — a
two-count margin — so that test is one noisy reading away from classifying a genuinely held bowl as an
air close, and the failure would be silent and severe (re-open, drop in flight, reward 0). Both tasks
are one-pad radial wall pinches on the *same 10.5 cm bowl*; their populations differ because of where
the bowl sits:

| | close | lift |
|---|---|---|
| `…between_the_plate_and_the_ramekin…` (wave 1) | ~0.103 | 0.042–0.122, settles to ~0.043 |
| `…on_the_cookie_box…` (this task) | 0.091–0.114 | 0.052–0.061 |

So there is no universal `AIR_W`; the corrected rule is *add the retention ratio when `AIR_W` and the
hold floor are within a few counts, and trust the absolute test alone only when they are far apart.*
The skill text now says this explicitly rather than claiming universality.

This is the second time a promotion has had to repair guidance an earlier promotion introduced (the
first: the `get_observation()` settling loop in `transport.md`; the second: the two-sided gate and
`AIR_GRASP_WIDTH = 0.05` in `grasp.md`). Worth noting as a pattern in its own right — *a rule
generalised from one task's population will be wrong about another's, and the library needs the
correction channel to stay open.*

## Promotion 0007 — `pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate`

VERIFIED, library `0cd2703e…` → `693c25f6…`. Stage 1: **15/15**, one root cause, no blocked seeds,
no seed needed more than 2 replays. Runtime instruction: *"Pick the akita black bowl next to the
cookie box and place it on the plate"* — the identifier says `ramekin`, the instruction says
`cookie box` (remap row 7 added to `localize.md`).

**Ingested (1):** `transport.keep-one-offset-convention-so-the-release-column-has-one-sign`
(`--lines 625:680`, anchored on `def carry_and_place`; `--successful-seeds 51…65`, `--improved`).

**Skill merges (3 files):**
- `transport.md` — the offset **sign** section taught "which sign for which grasp type"
  (`place + off` for a wall pinch, `place − off` for bowl-on-stove). This task shows that framing *is*
  the bug: it invites a per-branch sign, and the branches then disagree. New rule: `off == payload_centre
  − tcp` (measured, sign included) and `release_xy == place − off` **unconditionally**, no per-grasp-type
  sign anywhere. The tell is the **2× factor** — a wrong per-branch sign misses by *twice* the offset
  (here 2·|off| = 12.4 cm), a wrong offset *estimate* misses by the offset once.
- `transport.md` — the landing-check section's "gate on shape" was incomplete: a **mask bleed** lifts the
  payload's measured underside to the support surface, and a radius test that accepts anything inside the
  support's **outline** accepts a payload perched *on* that outline. Added the fraction-of-outline rule
  (0.040 of a 0.061 m dish) and the reason it is severe — the false positive **ended the retry loop after
  one attempt**, so the episode finished on a placement the program believed had succeeded.
- `manipulation.md` — two additions. (a) The cheap read-back reachability screen is legitimate for
  *ordering* walls (3 iterations each; the ladder's own gate needs 14–17), while the laddered probe
  remains mandatory for *disqualifying* — which is exactly what the existing warning says. (b) The hop
  stall test: wave-1's rule ("detect stalls by progress toward the target, **not** by motion") is right
  about the kinematic clamp but not universal — an **unreachable pose** stops the arm dead (<0.004 m)
  where a clamp dithers (~0.0065 m), so both tests belong in the loop. Section heading softened to
  "not by motion alone" so the library does not carry two conflicting rules.
- `localize.md` — remap row 7; the `cookie_box` note now covers *three* identifiers playing three
  different roles (stove support, cabinet-top support, and reference object of a `ramekin` task).

**Declined as duplicates/confirmations:** P2's footprint-vs-height rule and P6's ungroundable reference
name both already exist; P2's *new* part (the outline-radius refinement) was merged as text rather than
ingested as a parallel instance.

### Verified cross-check — a latent bug in already-shipped code (recorded, NOT changed)

The task-6 worker flagged that the same sign pattern appears in
`pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate/fix_code.py` line 424. **Verified
independently by the coordinator:** that file stores `pinch_off = bowl["c"] − [tx, ty]`
(payload-centre − TCP, line 398), so `off = −pinch_off` (line 424) followed by `release_xy = place − off`
computes `place + pinch_off` — wrong by 2·|off|, the identical defect.

Checked against dev evidence: across all 32 dev logs for that task, `carried:` prints show the *measured*
branch succeeding every seed and the string `rejected` never appears — the fallback branch **never fired
on a dev seed**, which is consistent with its 15/15 dev and 50/50 held-out results.

**Deliberately not modified.** That task's Stage 2 is complete and its shipped `fix_code.py` is
byte-for-byte the artifact that produced run `07c56ad6eafa444b`. Editing it now would decouple the
shipped artifact from the evaluated one and would amount to tuning after seeing held-out results, which
the protocol forbids. The 50/50 stands for the code *as shipped*, with a documented latent defect in a
branch the dev set never exercised. Carry into the final report under "known unexercised paths".

### Stage 2 scheduling for the two Stage-1-complete tasks

Tasks 6 (`next_to_the_ramekin`) and 7 (`on_the_cookie_box`) both finished Stage 1 at **15/15** with
promotions **0007** and **0006** VERIFIED, so both are eligible for Stage 2 — but **every GPU is
occupied** (3 and 6 on Stage 2 evals, 4/5/7 on Stage 1), so they are queued rather than started. They
will be launched on whichever of GPUs 3 and 6 frees first, in registry order (6 before 7), using the
coordinator's canonical Stage 2 invocation, captured verbatim from the running evals:

```
.venv-libero/bin/python3 scripts/libero/run_fix_loop_validation.py \
  --suite libero_spatial_task --task <TASK> \
  --gpu <GPU> \
  --fix-code outputs/libero_fix_loop/libero_spatial_task/<TASK>/fix_code.py \
  --output-dir outputs/libero_fix_loop_eval \
  --seeds 1 2 3 ... 50 --resume
```

Note there is **no `CUDA_VISIBLE_DEVICES`** — the `--gpu` flag selects the device inside the runner
(the process environment carries only `MUJOCO_GL=egl` and `TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1`).
`--resume` is what makes a re-launch safe: already-completed seeds are not re-run.

This is a deliberate deviation from the wave-1 pattern, where Stage 2 ran on the *same* GPU that had
just done that task's Stage 1. Here the Stage 1 GPUs were already reassigned to tasks 8-10 by the time
6 and 7 finished, so waiting for their "own" GPU would idle three tasks to no benefit. The promotion
gate is what matters and it is satisfied for both; the GPU identity carries no meaning beyond the
one-job-at-a-time rule.

### Anomaly — `between_the_plate_and_the_ramekin` Stage 2 returned `status=partial`

The run (`954a62be143ef2d9`) came back **partial, not complete**: all 50 seeds were launched but seed 43
produced `NO ARTIFACT exit=-15` — the trial process was **SIGTERM'd**, never reached a verdict.

Investigated before treating it as a task failure:
- Not OOM — `free` shows 478 GB available, and no `killed process` / `oom` lines in the kernel log.
- 3 genuine failures: seeds **23, 34, 44** (`reward=0.000 completed=0 exit=0`, i.e. clean runs that
  simply did not succeed).
- So the run's true score on the seeds that produced verdicts is **46/49 (94%)**, and seed 43 is
  *unknown*, not failed.

Handled by re-running with the runner's own `--resume` (which executes only the seeds lacking a
verdict) rather than by re-running all 50. This is the right instrument for a partial run: it makes a
re-launch idempotent, so a transient infrastructure kill costs one seed, not a whole eval.

**General point for the final report:** a `partial` status is a *coverage* statement, not a score. Any
per-task rate quoted for a partial run must say how many seeds actually produced verdicts — quoting
"46/49" as if it were "46/50" would silently conflate a missing datapoint with a failure.

## DEVIATION 3 (disk policy, user-approved): Stage 2 eval dirs for the remaining tasks are symlinked to `/mnt`

Measured, not estimated: each Stage 2 eval costs **9–17 GB** (median ~13), `/` had **57 GB** free with
**5 tasks still to evaluate (~65 GB)**, and the `/mnt` volume had 1.6 TB free. Continuing as-is meant a
shortfall of ~10–15 GB that would have landed mid-eval.

Three options were put to the user (symlink to `/mnt`; delete the wave-1 Stage 1 debug dirs, ~40 GB;
run as-is and accept ENOSPC risk). **The user chose the symlink.**

Implementation — for the five tasks whose Stage 2 had not yet started:

```
/mnt/nimloth/aspire_scratch/libero_fix_loop_eval/libero_spatial_task/<task>/     <- real directory
outputs/libero_fix_loop_eval/libero_spatial_task/<task>  ->  the above           <- symlink
```

Task dirs: `next_to_ramekin`, `on_cookie_box`, `on_ramekin`, `on_stove`, `on_wooden_cabinet`.

**Verified before use**, because the whole point is that the canonical path must keep working:
- `os.path.isdir()` on the canonical path is True and `os.path.realpath()` resolves to `/mnt`;
- a write through the symlink lands on `/mnt`;
- `glob.glob(canonical + '/runs/*/manifest.json')` returns the **canonical** path, so `gen_progress.py`
  and every other reader that goes through `outputs/libero_fix_loop_eval/...` are unaffected.

**Nothing was moved or deleted.** The five already-completed Stage 2 dirs stay as real directories on
`/`, as does the in-progress `next_to_cookie_box` dir (it only needed one missing seed filled, so
moving it was not worth the risk of touching an existing output mid-run). The cost, which the final
report must state: **the suite's eval output now spans two volumes and two physical layouts** — five
tasks as real directories on `/`, five as symlinks into `/mnt`. Logical paths are uniform; physical
storage is not.

Also recorded here: `status=partial` recurred. `next_to_cookie_box` (run `d39417005b795d5b`) came back
**partial at 35/49** with `seed 31: NO ARTIFACT exit=-15` — the same external SIGTERM as
`between_the_plate_and_the_ramekin`'s seed 43. Neither `run_fix_loop_validation.py` nor `replay_trial.py`
contains any timeout, alarm, or signal-sending logic (grepped), so the kill is **external to the
pipeline and its cause is undetermined**; it is not OOM (478 GB available, no kernel OOM lines) and not
correlated with disk level (the two kills happened at 57 GB and 50 GB free). Both were recovered with
`--resume`, and in the one case where the outcome is known (seed 43) the killed seed **passed** when
re-run — so a partial run understates the score, it does not merely add noise to it.

## Promotion 0008 — `on_the_stove` (GPU 7)

`begin` recorded on the library state `693c25f6797f54b4c74a9fec1610fc75ddf4b4d10a1b078ca76d1c03cefdb0bc`.
The worker reported six patterns (P1-P6); each was screened against the existing library before
anything was written.

**Ingested (2 new instances)**

| Instance | Vertical | Source | What it adds |
|---|---|---|---|
| `transport.command-the-release-height-then-servo-the-tool-to-it` | transport | `on_the_stove/fix_code.py` — `carry_and_place` | P1+P2 as one mechanism: clamp the descent at the release height (`max(gz - dz, rel_z_rel)`), taper the last 3 cm (`dzmax` 0.030 → 0.010), then command the release height absolutely and **servo** the grip-site reading onto it with an integral term |
| `manipulation.re-command-the-last-commanded-pose-in-a-hold-not-the-measured-one` | manipulation | `on_the_stove/v6.py` — `_CMD`/`go`/`settle`, lines 159–185 | P6: a hold that re-commands the **measured** pose is not idempotent |

**Skill text merged (3 files, no duplicates created)**

- `transport.md` — new `####` subsection under the placement-loop family: *"…but the loop above still
  discovers the release height — command it, taper into it, and servo the tool onto it"*. This is a
  **refinement** of the existing "Close the placement loop on the payload's own measured base": reaching
  the base is necessary but not sufficient, because the *stop test* is a measurement. Plus the explicit
  caution that this change must not be judged by a per-seed sweep result, since the 3 mm it removes is
  the margin that flips marginal seeds.
- `transport.md` — **corrected** the `settle` snippet in *"Physics Settling After Release"*: it
  prescribed `p = tcp_pos(); goto_pose(p)`, i.e. the ratchet. Now `_CMD`/`go`/`settle`, with the
  measured +4 / +11 / +2 mm drift and the print-both-heights rule.
- `localize.md` — new `###` section *"A mask that is only part of the object has no valid centre"*: the
  arc-mask failure and the **agreement gate** against an exact-by-construction offset, generalised to
  "whenever two independent estimates exist and one is exact, use the other only where they agree".
  Positioned as the sibling of the existing *stacked-object mask bleed* section; points at
  `localize.avoid-held-object-mask-contamination` as the inverse contamination.
- `manipulation.md` — new `###` corollary under *"Measure the TCP, Not the Hand"* (P6), explicitly
  flagged as a **correction** of `transport.pass-sim-time-with-a-command-not-an-observation`, whose
  stored `settle` is the ratcheting form.
- `manipulation.md` — refined *"Measure the Container's Reach Regime Per Seed"* with P5: the same seed
  can flip under **byte-identical** code, so re-run a plausible-looking failure before diagnosing it,
  justify fixes by mechanism + a printed quantity, and report a sweep as one *draw* (with this task's
  14/15 vs 13/15 version comparison as the worked example).

**Screened out**

- **P4 (damped fine phase)** — declined, not merged. The worker's own evidence is that the loop already
  converged at the noise floor (last-iteration lateral error 0.8–4.1 mm, uncorrelated with reward) and
  that damping "does not move the converged point". A mechanism argument with no discriminating
  measurement does not meet the bar the rest of this library is held to; it is recorded here so the
  idea is not lost.
- **P5 as a code instance** — already covered in substance by `manipulation.md` *"Measure the Container's
  Reach Regime Per Seed — Do Not Tune Against One Seed's Outcome"*; merged as a refinement rather than
  duplicated (see above).
- Four further items the worker itself marked "already in the library" (grip-site/TCP frame offset,
  laddered Cartesian motion, support-footprint selection, fraction-of-outline landing check) were
  verified as present and left alone.

### The shipping decision the worker handed back (v5 vs v6), and how it was resolved

`findings.md` §7 ends by declining to ship v6 and asking the coordinator to decide "by *repeating* the
sweep, not by this single comparison". Shipped was v5 at **14/15** (seed 53 fails, mechanism diagnosed
and reproducible: the `settle` ratchet put the release 11 mm above its own command). v6 — which removes
exactly that mechanism — measured **13/15** (failing 52 and 59), a difference that is squarely inside
the byte-identical-code variance this task demonstrated on seeds 58 and 59.

The decision was taken the only way it can honestly be taken: **repeat both versions' full dev sweeps**
(tags `rep5`, `rep6`, 15 seeds each, GPU 7) and compare two draws per version rather than one. Picking
v6 on mechanism alone would be the same error in the other direction; picking v5 on a single draw is
what the new skill text forbids. Both sweeps are logged under the task dir and their result is recorded
in the Campaign Log below. **Note what this costs:** ~38 minutes of GPU 7, which is why `on_cookie_box`
(15/15, promotion 0006 VERIFIED) is still queued rather than running.

`findings.md` will carry a short **coordinator addendum** recording the repeat, the final ship choice
and the md5 actually shipped, so the artifact and its evidence stay in one place. `finish`/`verify` are
run **after** that addendum, so the recorded `findings_sha256` is the file's final state.

### Anomaly follow-up — the `exit=-15` at the trial process

The earlier record ("external to the pipeline, cause undetermined") stands after a wider search, with
one thing now positively **excluded**: `cap/envs/runner.py` defines `TRIAL_TIMEOUT_SECONDS = 1000` and
`cap/utils/parallel_eval.py` has a result watchdog that does `p.terminate()` — i.e. there *is* SIGTERM
machinery in the repository — but it lives on the **multi-worker in-process runner** path
(`run_parallel_with_setup`, taken only when `num_workers > 1`). The fix-loop Stage 2 does not use it: it
spawns one `replay_trial.py` per seed as a subprocess and those children carry no timeout wrapper. So
the watchdog is not the sender. Separately, the *Stage 1 subagents'* dev sweeps do wrap each seed in
`timeout 900` (and one agent used `timeout 1800`), which would show up as the same `exit=-15` in a
sweep log — that is a different context and not the cause of the two Stage 2 partials, both of which
came from runner-driven runs.

## Campaign log — promotions 0008/0009 and the last two Stage 1/Stage 2 dispatches

**Promotion 0008 (`on_the_stove`) — VERIFIED**, library `4014cb9be3eede75c07c4b600fcdfdf50abc8b9949956716108a08469dce838a`.
Two instances ingested, three skill files edited (details in the "Promotion 0008" section above). The
v5-vs-v6 question the worker handed back was settled by **repeating both full dev sweeps** on GPU 7
(`rep5`, `rep6`): v5 **26/30**, v6 **23/30**, so **v5 ships unchanged** and the deliverable is byte-for-
byte the artifact the report evaluated. The promotion records the ratchet mechanism *and* the measured
cost of its candidate fix, so neither half of the finding is overstated. Written up in full in the
task's `findings.md` "Coordinator addendum", which is part of what `finish` hashed.

**Stage 2 launched for `on_stove`** on GPU 7 immediately after `verify` (run `1027ae9586cb5a01`).

**`on_cookie_box` Stage 2 filled its last missing seed**: the resume brought run `d39417005b795d5b` from
`partial 35/49` to **`complete` 36/50** — i.e. the seed the external SIGTERM killed **passed** when
re-run, which is the second time that has been observed (see the anomaly section: a partial run
*understates* the score, it does not merely add noise). Launched `on_cookie_box`'s own Stage 2 — GPU 7
was held by the repeat sweeps, so it went to **GPU 5**, which `on_the_wooden_cabinet` had just released
(run `a9822c6b28ae68ab`).

**`on_the_wooden_cabinet` Stage 1 returned a weak result — recorded as weak.** 12/15 initial → **11/15**
shipped, with **three BLOCKED seeds** (53, 56, 61, each with an `attempts/seed_<N>_BLOCKED.md`). The
worker's diagnosis is that the deciding variable is the payload's *post-release landing tilt* — read off
the settled cloud's z-extent, which separated all 18 logged runs (`≤0.049` → 1.0 in 12/12, `≥0.051` →
0.0 in 6/6) while the landing offset separated none — and that it is set by a one-pad pinch on a bowl
wider than the gripper plus a ~12 mm free fall from the arm's kinematic floor. Its one unexplored lever
(lower the release by relaxing the 2 mm descent-stall threshold) was **deliberately not attempted**,
because the three deterministic failures had exhausted their replay budget and the change could not
have been re-validated. Its own residual-risk section also states plainly that the reward is not
reproducible on this task (seed 58: 0.0 → 1.0 under byte-identical code; seed 53 passing under
`initial_code.py` and failing under `fix_code.py` on a numerically identical trajectory).

**Promotion 0009 (`on_the_wooden_cabinet`) — VERIFIED**, library
`cc34910fd244b7292cf1f0c192076a97c65cd70ecfbf94b5b73e7805d4699b51`. Screened from six reported
patterns:

| Pattern | Disposition |
|---|---|
| P1 continuity guard on a held estimate | **ingested** — `transport.gate-a-held-estimate-by-positional-continuity-not-by-plausibility` (vertical transport; the worker's `main`); merged into `transport.md` as a `####` beside the held-object servo family. Recorded **without** the `improved` flag, because the shipped program scored *worse* than its own initial code (11/15 vs 12/15) — its value is the mechanism and the two seeds it repaired |
| P2 single-mask dropout tolerance | merged into the same section as a companion rule, explicitly labelled weaker-evidence (no dev seed required it) |
| P3 absolute-TCP descent to the payload's own base | already in the library (*"Close the placement loop on the payload's own measured base"*) — no new text |
| P4 verify after release from perception only | already in the library (`localize.perception-costs-no-sim-steps`, *"settle before you judge"*) — no new text |
| P5 `ext_z` tilt diagnostic | **merged** as a new `####` in `transport.md` — *"Judge a marginal landing by the settled cloud's z-extent, not by its xy offset"*, including the note that the offset drift is inconsistent and must not be compensated |
| P6 radial-pinch tilt + free fall from the kinematic floor | **merged** into `grasp.md` beside the one-pad pinch population table, **with its negative result** (raising `PINCH_FRAC` 0.62 → 0.80 did not improve the hang and regressed seeds 52 and 55) so a future session does not repeat it |

**Deviation-adjacent note (recorded rather than hidden): promotion and Stage 2 were overlapped for
`on_the_wooden_cabinet`.** An idle GPU (6) existed while its promotion was still being written, so its
Stage 2 was launched first and the promotion completed during the eval. This cannot contaminate either
side — Stage 2 replays a frozen `fix_code.py` through `run_fix_loop_validation.py` and neither reads nor
writes the knowledge library, and held-out outcomes are OUTCOME ONLY and were not consulted while
screening the six patterns above (the screening was done from `findings.md`, which contains dev seeds
51–65 only). Same reasoning applied to `on_cookie_box`, whose Stage 2 also started on a GPU freed by a
different task's Stage 1.

---

## Promotion 0010 (`on_the_ramekin`) — VERIFIED

Library `61f0fa5d6f49b2655ff7e98341c9b402b9b1c121a44abd40f2d50426613e6210` (from `cc34910f…`).
Four skill files changed (`grasp.md`, `localize.md`, `manipulation.md`, `transport.md`), two instances
ingested, `knowledge/evidence/events.jsonl` appended. This is the only promotion that touched **all
four** skill files — a fair summary of the task, whose root causes landed one in each vertical.
Findings recorded at sha256 `a033aa98…`.

Screened from the six patterns the worker reported:

| Pattern | Disposition |
|---|---|
| P1 rim-circle fit of a round object's centre | **ingested** — `localize.fit-a-circular-rim-to-audit-the-centre-and-read-the-clearance`, anchored on `rim_cloud`; new `##` section in `localize.md`. Genuinely new: no instance in the library does a circle fit. The finding is explicitly that it **audits** the OBB rather than replacing it (the OBB agreed with the fit to ~2 mm), and that the fitted radius is a free self-check |
| P2 calibrate the landing bias and aim off by it | **ingested** — `transport.calibrate-an-open-loop-landing-bias-from-the-dev-seeds-own-final-offsets` (`--improved`, seeds 51–64 = the two-draw intersection), merged into `transport.md` **immediately beside** the existing rule that a constant bias is "a margin, not a fix". The two do not conflict and the contrast *is* the knowledge: the same constant is fatal on an **open** placement loop and cosmetic on a **closed** one |
| P3 never re-command the low release pose | **already in the library** (0008's `manipulation.re-command-the-last-commanded-pose…` plus the `###` in `manipulation.md`). Merged a *corroboration* paragraph only — this task's drag was 2.4 cm in a single call (`tcp_z` 0.0598 → 0.0839), an order of magnitude larger than 0008's millimetre ratchet, same mechanism |
| P4 tool floor and the drop it forces | **merged** into `grasp.md` beside the one-pad-pinch free-fall discussion, as a **second independent negative** for raising the pinch (0.78 h made seeds 55/62/65 worse here; `PINCH_FRAC` 0.62 → 0.80 regressed 52/55 on the wooden-cabinet task) |
| P5 compensate the Cartesian deadband | **already in the library** — `manipulation.a-small-cartesian-command-is-not-executed-bracket-the-hop-size`, and `manipulation.md` already carries the 0.020 → 0.0079 table. No new text |
| P6 read `task_language`, treat the identifier as opaque | **already in the library** — `localize.take-the-relation-from-the-runtime-language-not-the-task-name` plus the `###` in `localize.md`. The *new* content is the remap table itself, below |

### The `_task` remap rows for tasks 8/9/10 — recorded here, and why here

The three outstanding rows of the runtime-instruction table had to land inside an **open** promotion,
and 0008/0009 were already `finish`ed and `verify`ed by the time these three tasks finished, so they
land in 0010. All three were read from the Stage 1 artifacts — each task's `findings.md` and its
dev-seed sweep logs — never from held-out outcomes:

| task identifier | runtime `env.handle.task_language` |
|---|---|
| `…on_the_ramekin…` (task 8) | "Pick the akita black bowl **on the cookie box** and place it on the plate" |
| `…on_the_stove…` (task 9) | "Pick the akita black bowl **on the top of the cabinet** and place it on the plate" |
| `…on_the_wooden_cabinet…` (task 10) | "Pick the akita black bowl **on the stove** and place it on the plate" |

Two new structural facts, both now written into `localize.md`:

1. **The remap is not injective.** Tasks 7 and 9 share one instruction ("on the top of the cabinet");
   tasks 4 and 10 share another ("on the stove"). A runtime string is therefore not a key back to a
   task, and an instance recorded against "the stove task" is ambiguous unless the identifier is
   stored with it.
2. **Two identifiers are effectively swapped.** Task 9 (`on_the_stove`) runs the *cabinet-top*
   instruction and task 10 (`on_the_wooden_cabinet`) runs the *stove* instruction. The identifier's
   support is not merely wrong, it can be *the other task's* support.

Task 8 is also the cleanest illustration of the decoy case yet: the instruction is constant on all 15
dev seeds, the scene holds **two identical akita bowls** — one on the cookie box (the target), one on
the ramekin (the decoy) — and the identifier names *the decoy's* support.

**Deviation-adjacent note: none for this promotion.** Unlike 0008/0009 an idle GPU was available (4,
the one its own Stage 1 had held), so Stage 2 was launched **after** `verify`, in the intended order.
Held-out outcomes were not consulted during screening.
