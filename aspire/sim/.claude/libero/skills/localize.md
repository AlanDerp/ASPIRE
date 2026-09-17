---
name: localize
description: Object localization via SAM3 — prompting strategies, multi-prompt fallback pattern, 3D centroid extraction, and per-object prompt registry. Grows through experiment.
---

# Localize — SAM3 Prompting & Object Localization

> This skill tracks **what SAM3 prompts work for which objects** and the standard
> localization helper pattern. Add entries to the prompt registry as you discover
> working prompts through experiment.

---

## Standard Localization Helper

```python
import numpy as np

def localize_object(rgb, depth, K, E, prompts):
    """Try prompts in order, return (center, pts, mask) for first hit with ≥10 points."""
    depth_img = depth[:, :, 0] if len(depth.shape) == 3 else depth
    if isinstance(prompts, str):
        prompts = [prompts]
    for prompt in prompts:
        masks = segment_sam3_text_prompt(rgb, prompt)
        if not masks:
            continue
        best = max(masks, key=lambda d: d["score"])
        mask = best["mask"].astype(np.uint8)
        pts = mask_to_world_points(mask, depth_img, K, E)
        if pts is None or len(pts) < 10:
            continue
        center = get_oriented_bounding_box_from_3d_points(pts)["center"]
        return center, pts, mask
    return None, None, None
```

**Usage:**
```python
obs = get_observation()
cam = obs["agentview"]
center, pts, mask = localize_object(
    cam["images"]["rgb"], cam["images"]["depth"],
    cam["intrinsics"], cam["pose_mat"],
    ["<specific prompt>", "<fallback prompt>"]
)
if center is None:
    raise RuntimeError("Object not found")
```

**Why OBB center over mean:** `get_oriented_bounding_box_from_3d_points` gives a more
robust center estimate for elongated or partially occluded objects than `pts.mean(axis=0)`.

---

## Prompt Registry

Discovered working prompts, indexed by object. Add entries as you find them.
List prompts in priority order — first hit wins.

| Object | Working Prompts | Suite/Task | Notes |
|---|---|---|---|
| patterned metal bowl | `metal bowl` (0.95), `silver bowl` (0.92), `bowl` (0.91) | libero_goal_swap / put_the_bowl_on_top_of_the_cabinet | `plate` (0.91) is a *different* object (red-rimmed plate) — never use a bare `bowl` prompt without checking the box |
| wooden cabinet | `cabinet` (0.25–0.48), `wooden cabinet`, `drawer` (0.12), `shelf` | same | Low score but usable; the mask mixes the top face with the sloped front slats — always reduce it with the z-plateau pattern below |
| wine bottle / stove (distractors) | `wine bottle` (0.93), `stove` (0.90) | same | Useful to know they are present so a loose prompt does not steal them |
| top drawer handle (bar) | `handle` | libero_goal_swap / open_the_top_drawer_and_put_the_bowl_inside | Side approach (axis −y, fingers closing along world z); used with a closed-loop pull, not a fixed displacement |
| metal bowl in an open drawer | `metal bowl` | same | **The top-scoring mask is the drawer, not the bowl** — always screen the top ~12 masks by geometry (see "Screen SAM3 Candidates by Geometry" below) |
| cream cheese box (flat slab) | `cream cheese`, `butter`, `box` | libero_goal_swap / put_the_cream_cheese_in_the_bowl | 7.6 × 4.0 × 1.77 cm slab. Screen on geometry, not score: `40 ≤ n ≤ 5000`, z-extent ≤ 0.035 m, `0.01 ≤ min(ext)`, `max(ext) ≤ 0.10`, `z_hi ≤ 0.06` for a box still on the table — and lift the z screen for a box that has moved (see "Lift the Height Screen" below). A bare `box` prompt also fires on the arm |
| metal bowl (empty, on the table) | `metal bowl`, `bowl`, `silver bowl` | same | Top-3 masks by score, then require a container's *shape*: `200 ≤ n ≤ 20000`, z-extent ≥ 0.020 m (a bowl has depth), `max(ext) ≤ 0.20` m. Rejects the table/wall masks that score comparably |
| butter box (flat slab) | `butter box` (0.354), then `butter` (0.067), `box`, `carton` | libero_object_swap / pick_up_the_butter_and_place_it_in_the_basket | 7.5 × 3.9 × 1.6 cm. The product word does **not** ground and ranks a sibling first (`butter stick` puts the chocolate-pudding box at 0.108 above the butter's 0.090) — see "Prompt the Packaging Word" below. Geometry alone cannot separate the two boxes (7.5×3.9×1.6 vs 8.3×5.0×2.9 cm), so rank by the warm-colour fraction instead |
| chocolate pudding box | `brown box` (0.578), then `chocolate pudding` (0.002), `pudding` (0.006), `box` (0.426) | libero_object_swap / pick_up_the_chocolate_pudding_and_place_it_in_the_basket | 8.5 × 5.5 × 3 cm. The product name does **not** ground; a colour+shape descriptor does — see the variant under "Prompt the Packaging Word" below. A bare `box` also fires on the orange-juice carton and the basket, so the descriptor is only usable together with the geometry screen on the top 3 candidates |
| woven basket (goal container) | `basket` (top-1), `wicker basket`, `woven basket` | libero_object_swap / pick_up_the_butter_and_place_it_in_the_basket + pick_up_the_chocolate_pudding_and_place_it_in_the_basket | The basket's mouth centre is **not** its cloud median — use the top-rim percentile box (see "Take a Container's Mouth Centre From Its Top Rim" below). Its interior floor is a depth hole on both tasks, so the release height must come from the rim |
| stove control (articulated post/lever) | `black knob` (0.41), `knob`, `stove knob` | libero_goal_swap / turn_on_the_stove | ~200 masks come back but the **top-scoring one is always the control**, and depth inside its mask is fully valid, so no geometry screening is needed. The cloud still needs *splitting*: pinch the raised band (`z > zlo + 0.55·(zhi−zlo)`), not the object's OBB centre — the wide base dominates it |
| bbq sauce bottle (tall, capped) | `bottle`, `sauce bottle`, `sauce`, `bbq sauce` — **for candidates only, never for ranking** | libero_object_swap / pick_up_the_bbq_sauce_and_place_it_in_the_basket | No prompt identifies it. Three bottles are on the table and a whole-class prompt prefers the wrong one every time (`bottle` 0.957 decoy vs 0.945; `bbq sauce` 0.129–0.15 decoy vs 0.002–0.147). Its neutral-grey cap, the obvious "it must be the sauce" cue, belongs to the **decoy**. Rank the grouped candidates by the intrinsic colour signature instead (`sat - val`: sauce 0.744–0.773 vs decoy 0.159–0.253) — see "Rank same-class distractors per *physical object*" below. Body ≈ 3.2 cm across, ~14 cm tall |
| soup can (either instance) | `can` (0.92–0.94), `tin can` (0.88–0.92), `metal can` (0.88), `food can` (0.87), `soup can` (0.80–0.83), `can of alphabet soup` (0.62–0.77) | libero_object_swap / pick_up_the_alphabet_soup_and_place_it_in_the_basket | **Every one of these returns *both* cans**, and the ranking is by apparent size, so it carries no identity information (`can of alphabet soup` and `can of tomato sauce` both prefer the same wrong can). Use them to *find candidates* only. The goal can is the one with the **blue** label — `mean(B) − mean(R)` = +1.0 vs −14.2. 6.1 cm diameter, 7.8 cm tall |
| alphabet soup / tomato sauce (as words) | **none** — `alphabet soup` (0.094), `tomato sauce` (0.033), `soup` (0.018), `vegetable soup` (0.006) | same | The product words do not ground at all. A bare `alphabet soup` scores highest on the **milk carton** (0.58 under `milk carton`), which is the tell that the prompt has not grounded |
| cream cheese slab | `blue box` (0.494, 0.248–0.498 across seeds), then `cream cheese` (0.019), `cheese box` (0.111), `box`, `carton` | libero_object_swap / pick_up_the_cream_cheese_and_place_it_in_the_basket | Product and packaging words both fail — `cheese box` ranks the brown **butter** slab (0.111) above the target (0.104). The colour+shape descriptor is what grounds it; put it **first** in the prompt list, since the first prompt yielding a candidate wins. It also fires on the blue orange-juice carton, so keep the geometry screen as the outer gate. 7.8 × 4.0 × 1.8 cm |
| milk carton | `milk carton` (0.385–**0.469** across seeds), then `juice box` (0.922, **tied**), `box` (0.805, **tied**), `carton` (0.754, tied) | libero_object_swap / pick_up_the_milk_and_place_it_in_the_basket (and as a distractor on alphabet soup) | The **only** prompt that leans the right way, and only by **0.047–0.080** (0.469 vs 0.404 / 0.449 vs 0.369 / 0.385 vs 0.338) — far too small to ship as a selector. Every *packaging* word ties **exactly** on the milk brick and its orange-juice twin (`juice box` 0.922/0.922, `box` 0.805/0.805), which inverts the usual "use the packaging word" advice. On the alphabet-soup scene this is also the object a bare `alphabet soup` prompt lands on (0.58), a useful tell that a different prompt has not grounded |
| ketchup bottle | `grey cap` (0.867 on the cap mask), `bottle cap` (0.840); **not** `ketchup`/`ketchup bottle`/`tomato ketchup`/`red bottle` | libero_object_swap / pick_up_the_ketchup_and_place_it_in_the_basket | Every product word **inverts** the ranking: `ketchup bottle` scores the maroon decoy 0.797 above the ketchup's 0.738, `red bottle` 0.492 vs 0.461, `sauce` tied at 0.750. Not shipped — a cap-colour prompt is exactly the assumption the bbq-sauce task shows to be unreliable — but as a *second signal* it is strong. Ship the measured two-region signature instead (see below) |
| orange-juice carton | `juice box` (0.922 on the target, 0.406 on the milk carton), `orange juice carton` (0.809), `orange juice`, `carton`, `box` | libero_object_swap / pick_up_the_orange_juice_and_place_it_in_the_basket | 2.7 × 5.0 × 13.4 cm. **The cleanest counter-example to "a packaging word that grounds identifies the object."** `juice box` grounds strongly here, but on the *milk* task the identical prompt ties 0.922 / 0.922 on these same two cartons — so grounding is not identity, and a grounding prompt can still be a coin flip between siblings. Ship it to *find candidates*, rank by the bright-orange fraction (below) |
| salad dressing bottle (tall, dark-green cap) | **none** — `salad dressing` (0.154), `dressing` (0.235), `salad dressing bottle` (0.664); `bottle` / `sauce bottle` return it at 0.914–0.949 but **always behind a sibling** | libero_object_swap / pick_up_the_salad_dressing_and_place_it_in_the_basket | Product words do **not** ground: `salad dressing` and `dressing` both place the target and a sibling within **0.001** of each other, i.e. they are ranking by apparent size, and `salad dressing bottle` grounds two siblings equally. Three tall bottles share the scene (target with a green cap; a ketchup-style bottle with a pale cap at `(0.773, 0.027)`; a dark bottle with a neutral-grey cap at `(0.497, −0.237)`), and the best sibling scores **0.953–0.957** against the target's **0.906–0.949** — the raw prompt ranking is **inverted on 15/15 seeds**. Use `bottle` to *find candidates* only, then rank by the cap band's signed green difference (below). Note the bbq-sauce row's warning holds again: the neutral-grey cap is the **decoy** there too |

---

## Check *Which* Anchor Actually Varies Before Optimising for Variation

**Trigger**: deciding where to spend robustness effort on a new task in this suite. The instinct is to
harden perception against object-pose variation. Measure first — in `libero_object_swap` **the
manipulated object does not move at all across seeds; only the container does.**

Measured: the tomato-sauce can sits at `cx=0.482, cy=-0.241, base=0.013, top=0.081` on **all 15**
development seeds, identical to the millimetre. The alphabet-soup sibling's can is likewise fixed at
`(0.402, -0.083)` across all 15 of its seeds. The **basket**, on both tasks, takes 15 *distinct*
values (x 0.657–0.684, y 0.245–0.271).

```python
can = pick_target(find_cans())
print("  target can cx=%.3f cy=%.3f warm=%.1f" % (can["cx"], can["cy"], can["warm"]), flush=True)
basket_xy, _ = find_basket_clear()                       # this DOES move
print("  basket xy=%s" % np.round(basket_xy, 3), flush=True)
```

**Why it matters**: "generalization across seeds" in this suite means *container-position*
generalization. Effort spent making object identity or object geometry seed-robust is mostly wasted,
while effort spent on **container localisation and release accuracy** is where the held-out failures
actually come from — on the same task the release residual ranged 0.013–0.104 m and was the only
quantified risk to held-out seeds. Print both anchors every seed and compare across the sweep; a fixed
pose shows up immediately, and a print is cheaper than a robustness mechanism. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_tomato_sauce_and_place_it_in_the_basket/fix_code.py`
— `run`; 2026-09-14.

**Scope caveat**: established on two `libero_object_swap` tasks. Treat it as a hypothesis to check in
one sweep (two prints, 15 seeds) on any other suite, not as a fact to assume — the same discipline the
rest of this file applies to descriptors.

## Disambiguation: Two Similar Objects in Scene

When a scene contains two visually similar objects, `max(score)` often returns the wrong one.
Use **bbox pixel area** to discriminate by size:

```python
def localize_smallest_bbox_mask(rgb, prompts, max_cy=None):
    """Select the mask with smallest bbox pixel area (most compact matching shape).
    max_cy: if set, only accept masks with bbox center-y below this row (upper image = farther away).
    Add min_w/max_w/min_h/max_h filters as you learn the object's image footprint.
    """
    for prompt in prompts:
        masks = segment_sam3_text_prompt(rgb, prompt)
        if not masks:
            continue
        best_mask = None
        best_area = float('inf')
        for m in masks[:10]:
            bbox = m.get('box', None)
            if bbox is None:
                continue
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            px_area = w * h
            cy = (bbox[1] + bbox[3]) / 2
            if (max_cy is None or cy < max_cy) and px_area < best_area:
                best_area = px_area
                best_mask = m
        if best_mask is not None:
            return best_mask["mask"]
    return None
```

**Key**: `area_pct` in trace dicts truncates to 99.00 for all masks. Compute area from `box` coordinates instead.

### In a `_task` suite the relation comes from the RUNTIME LANGUAGE — the task name lies

**Trigger**: the suite identifier ends in `_task` (`libero_spatial_task`, `libero_goal_task`,
`libero_object_task`) and the scene holds more than one candidate for the relation named by the task
identifier.

The `_task` suites **remap the language instruction**. The task identifier and the BDDL file name keep
one relation; `env.handle.task_language` carries the goal the simulator actually rewards. Read the
string at runtime and drive the selector from *it* — never from the identifier you were dispatched
with, and never from the file name:

```python
language = str(getattr(env.handle, "task_language", ""))
# "Pick the akita black bowl next to the ramekin and place it on the plate"
#   class pool = attribute prompt ("black bowl": 0.777/0.773 vs 0.287 for the look-alike)
#   reference  = the SMALLEST on-table bowl-like candidate that is not in the pool
#   target     = the pool member NEAREST that reference  (NOT nearest the goal)
ramekin = min(rest, key=lambda c: max(c["ext"][0], c["ext"][1]))
target  = min(pool, key=lambda c: float(np.linalg.norm(c["c"] - ramekin["c"])))
```

**Evidence**: for `pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate` in
`libero_spatial_task` the runtime instruction reads **"…next to the ramekin…"** on all 15 development
seeds, while the task identifier says *plate*. On seed 51 the akita nearest the **ramekin**
`(0.490, 0.310)` was carried, placed and scored **reward 1.0**, and the akita nearest the *plate*
`(0.659, 0.325)` was never touched; the shipped revision scores **15/15**. The remap is **per-suite**:
the same identifier in `libero_spatial_swap` really does mean "next to the plate" (see the class-screen
section below, which resolves it against the goal) — so the runtime string is the only reliable
source. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate/fix_code.py`
— `pick_ramekin_and_target` lines 264–292, language read in `run()` at line 466; 2026-09-16.

**The remap is stronger than a relation swap: in `libero_object_task` it rotates the GOAL OBJECT
itself, so the identifier is not merely imprecise — it names the wrong thing.** The `_task` variant of
the object suite is a fixed-point-free permutation over the ten object names, and it is constant per
BDDL across all 15 development seeds. **All ten** confirmed by reading
`env.handle.task_language`:

| task identifier / BDDL name | runtime instruction names |
|---|---|
| alphabet_soup | cream cheese |
| bbq_sauce | ketchup |
| butter | orange juice |
| chocolate_pudding | salad dressing |
| cream_cheese | alphabet soup |
| ketchup | **milk** |
| milk | **butter** |
| orange_juice | chocolate pudding |
| salad_dressing | tomato sauce |
| tomato_sauce | **bbq sauce** |

The tenth row arrived the way the other nine did — read off `env.handle.task_language` on 15/15
development seeds of `pick_up_the_tomato_sauce_and_place_it_in_the_basket`, which prints
`Pick the bbq sauce and place it in the basket` every seed. What makes it worth recording is that it
had been **written down first as a prediction**. Nine rows assign nine distinct targets, leaving
`tomato_sauce` and `bbq_sauce` as the only unassigned source and the only unassigned target, so the
row was forced to `tomato_sauce → bbq_sauce` — and the nine observed rows form a **single 10-cycle**
(`alphabet_soup → cream cheese → alphabet soup` is the one 2-cycle; the rest close one long ring
`bbq_sauce → ketchup → milk → butter → orange_juice → chocolate_pudding → salad_dressing →
tomato_sauce → bbq_sauce`), which is what made the last row derivable at all — a general permutation
would have left it open. One prediction, then confirmed, is a retrodiction and not proof of the
generative rule: the table above is now *observation* on all ten rows, and the "single 10-cycle"
sentence is the explanatory story that survived one test, not a law. Do not use it to derive an
eleventh row — the object suite has exactly ten tasks, so there is none to derive.

So a program that grounds the identifier's noun — or that trusts the file name — grabs the decoy, and
the decoy is genuinely present in the scene: on `pick_up_the_ketchup_and_place_it_in_the_basket` the
red bottle *is* on the table and scores well under the prompt `ketchup`, while the rewarded object is
the **milk carton**. The remedy is the same one line as above, applied one level earlier — parse the
noun out of the runtime string and key the prompt registry on *that*, never on the identifier you were
dispatched with:

```python
lang = str(getattr(env.handle, "task_language", ""))
noun = lang.lower().replace("pick up the ", "").replace("pick the ", "")
noun = noun.split(" and ")[0].strip()          # "Pick the milk and place it..." -> "milk"
prompts = PROMPTS.get(noun, [noun, "box", "carton", "bottle", "can"])
```

Print the parsed noun on every run — a silent mis-parse here is indistinguishable from a perception
failure downstream. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_ketchup_and_place_it_in_the_basket/fix_code.py`
— `run` lines 363–369, `PROMPTS` registry lines 53–66; 15/15 development seeds; 2026-09-16.

**On `libero_object_task` the remap changes the *goal object itself* — and the identifier's noun is left
in the scene as live bait.** The relation-remap above is the `libero_spatial_task` form. The object suite
does something strictly harder to notice: the runtime instruction names a **different object** from the
task identifier, and the object the identifier names is **physically present** and plausible. Five
confirmed cases, including one where the bait is of a *different class* from the goal:

| task identifier (`libero_object_task`) | runtime `env.handle.task_language` | identifier's object in scene? |
|---|---|---|
| `…the_alphabet_soup…` | "Pick the **cream cheese**…" | yes — blue cream-cheese box |
| `…the_bbq_sauce…` | "Pick the **ketchup**…" | yes — bbq-sauce bottle |
| `…the_chocolate_pudding…` | "pick the **salad dressing**…" | yes — pudding box |
| `…the_cream_cheese…` | "Pick the **alphabet soup**…" | yes — blue cream-cheese box |
| `…the_salad_dressing…` | "Pick the **tomato sauce**…" | yes — green-capped dressing bottle, at `(0.656, −0.102)`, a **different package class** from the goal can |

So on this suite you cannot sanity-check a program by asking "does the scene contain what I'm looking
for?" — it does, and it is the wrong thing. Two consequences: derive the target's *appearance
descriptor* from the runtime string (which is what the identifier-noun → descriptor mapping does below),
and never let a *plausibility* check stand in for reading the string. Note the third and fourth rows are
**reciprocal** — `…the_chocolate_pudding…` asks for the salad dressing and `…the_cream_cheese…` asks for
the alphabet soup — so the mapping is not even a fixed permutation to memorise; it is per-task and must
be read at runtime. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_cream_cheese_and_place_it_in_the_basket/fix_code.py`
— `target_signature` lines 183–194; 2026-09-16.

#### The remap reaches a third suite: `libero_goal_task`

`libero_goal_task` shares its ten identifiers with `libero_goal_swap` and remaps them the same way the
two suites above do. **Nine rows are measured so far — the campaign is still in progress, so treat
this as an opening table, not the finished one.**

| task identifier (`libero_goal_task`) | runtime `env.handle.task_language` | what the remap moves |
|---|---|---|
| `put_the_bowl_on_the_plate` | **"Put the wine bottle on the plate"** | the object |
| `push_the_plate_to_the_front_of_the_stove` | **"Push the cream cheese to the front of the stove"** | the object (relation + support survive) |
| `put_the_bowl_on_the_stove` | **"Put the plate on the stove"** | the object (support survives) |
| `put_the_bowl_on_top_of_the_cabinet` | **"Put the plate on the top of the drawer"** | the object **and the site** |
| `open_the_middle_drawer_of_the_cabinet` | **"open the bottom drawer of the cabinet"** | **only the positional descriptor** |
| `put_the_cream_cheese_in_the_bowl` | **"put the wine bottle in the bowl"** | the object (support survives) |
| `put_the_wine_bottle_on_top_of_the_cabinet` | **"put the wine bottle in the bowl"** | the object, relation, **and support** — *identical to the row above* |
| `put_the_wine_bottle_on_the_rack` | **"Put the cream cheese on the rack"** | the object |
| `turn_on_the_stove` | **"Turn off the stove"** | the **POLARITY** of the goal — an antonym, not a different noun |

**The fourth row is the first *site* remap measured in this suite, and it is a double one.** The
identifier names a **bowl** as the payload and a **cabinet** as the support; the runtime string names a
**plate** on the **top of the drawer**. The scene holds both a bowl and a plate and exactly one drawer
cabinet, so a program that reads the identifier builds the right kind of plan for the wrong object *onto
the wrong surface* — and the identifier's own noun is again present as bait. The plate is white with a red
rim, `r_out ≈ 0.070 m`, rim top z ≈ 0.007. Source:
`outputs/libero_fix_loop/libero_goal_task/put_the_bowl_on_top_of_the_cabinet/findings.md`; 2026-09-17.

**The fifth row is the most dangerous shape of all: the object class and the support are both correct and
only the *ordinal* is wrong.** `open_the_middle_drawer_of_the_cabinet` runs as `"open the bottom drawer of
the cabinet"` — "drawer" and "cabinet" both match, so every sanity check that compares nouns **passes**,
and a program that targets the middle drawer is aiming at a drawer that exists, is reachable in principle,
and is not the goal. Here the identifier's descriptor is not merely bait, it is a *plausible* neighbour one
level up in the same column. Parse the ordinal out of the runtime string and never from the identifier:

```python
language = getattr(env.handle, "task_language", "") or ""
want = _ordinal(language)      # \b(bottom|lowest|lower)\b -> 0, middle -> 1, top|upper -> 2
```

Measured on all 15 development seeds (`parsed ordinal: bottom`, string constant); the middle drawer opens
to its stop for reward 0.0 on 12/15 and the top drawer likewise — i.e. the program *could* open the wrong
drawers perfectly. Source:
`outputs/libero_fix_loop/libero_goal_task/open_the_middle_drawer_of_the_cabinet/findings.md`; 2026-09-17.

**The sixth row kills the last shortcut. There is no noun → payload table, and it is not even a
function.** `put_the_cream_cheese_in_the_bowl` runs as **"put the wine bottle in the bowl"**. Put that
beside rows 1 and 3 and the trap is structural: the identifier's noun **`bowl`** resolves to the
**wine bottle** in row 1 and to the **plate** in row 3 as the *payload*, and to the *support* here in
row 6. One noun, three different roles. So the identifier's noun cannot be mapped to a payload, cannot be
mapped to a role, and cannot even be used to decide whether the thing it names is the goal or the
destination. Anything you build that "translates" identifiers will be wrong for some task in the suite,
and wrong *silently* — the object it names is usually present and plausible.

The identifier's noun is worse than useless as a prompt, and this task measures how much worse: the
blue cream-cheese box sits in the scene at `(0.62, 0.11)`, and on its own box the prompt `cream cheese`
scores **0.020** where the generic `box` scores **0.660**. The identifier's noun does not merely rank
the wrong object first — it ranks *below a word that names no object at all*. Never let it enter a prompt
list at any rank, including as a last-resort fallback. Read the runtime string instead, on every seed,
before anything else:

```python
task_language = str(getattr(env.handle, "task_language", ""))
print("TASK_LANGUAGE=%r" % (task_language,), flush=True)
```

**The seventh row is where the table stops being a table: the remap is not injective.** Two *different*
identifiers resolve to the **same** runtime string — `put_the_wine_bottle_on_top_of_the_cabinet` and
`put_the_cream_cheese_in_the_bowl` both run as **"put the wine bottle in the bowl"**. This is stronger
than the previous rows: row 6 already showed the identifier's noun does not determine the payload, but a
one-to-one table from identifier to instruction would still have been constructible. It is not. Measured
three independent ways on this campaign's pair:

1. Each worker's own log, under two distinct task output paths, prints the same
   `TASK_LANGUAGE: 'put the wine bottle in the bowl'` on every one of its 15 development seeds.
2. The two scenes render **byte-identical agentview snapshots** (`md5 4d6efa1a416a82c78f75c3ab2721043`).
   So it is not merely two instructions that read alike — the harness loads the same world.
3. The harness itself still distinguishes them: `task_id=2` for the cabinet identifier against
   `task_id=6` for the bowl identifier, with distinct resolved task names.

So the map `identifier → runtime string` is many-to-one, and *nothing observable in the scene* separates
the two members of a collision class. The consequence for a fix program is narrow and worth stating
exactly: it does **not** invalidate reading the runtime string — that read is still the only correct
source of the goal, and the program above scored 15/15 on this identifier while parsing it. What it kills
is any *caching or memoisation keyed on the instruction string*, any per-instruction prompt table built
across tasks, and any inference of "which task is this" from the rendered scene. Two identifiers are one
runtime problem; do not expect their held-out scores to differ. The mechanism is unexplained — the
harness distinguishes the pair by an internal id that a fix program may not read — so this records the
measurement, not a cause. Sources:
`outputs/libero_fix_loop/libero_goal_task/put_the_wine_bottle_on_top_of_the_cabinet/findings.md` and
`…/put_the_cream_cheese_in_the_bowl/findings.md`; 2026-09-17.

**The eighth row is the plainest, and it is worth having as a control.** `put_the_wine_bottle_on_the_rack`
runs as **"Put the cream cheese on the rack"** — the relation (`on`) and the support (`rack`) both survive
and only the **object** is swapped, exactly the shape of the second row. Nothing subtle: the identifier
names a wine bottle, the payload is a blue cream-cheese box. Its value is as an uncontaminated
measurement — 40 recorded runs across four sweeps, every one printing the identical string, with no
collision against any other identifier. It also adds a second entry to the `wine bottle` → *not a bottle*
column (see the sixth row's note that no noun → payload table exists): the noun `wine bottle` here
resolves to a cream-cheese box, and in rows 1, 6 and 7 to an actual wine bottle used as *payload* for a
`bowl`-named identifier. Sources:
`outputs/libero_fix_loop/libero_goal_task/put_the_wine_bottle_on_the_rack/findings.md`; 2026-09-17.

**The ninth row is a new class: the remap inverts the goal.** `turn_on_the_stove` runs as **"Turn off the
stove"**. Every row above moves the *object*, the *support*, the *site*, the *relation*, or an *ordinal* —
all of them keep the **verb** and the **polarity**. This one keeps the object (`stove`), the support, and
the relation entirely intact and negates the *goal state*: the identifier asks for `on`, the runtime string
asks for `off`. Noun-comparison sanity checks pass, exactly as in the fifth row, and the failure is again
invisible to them.

The consequence is sharper than "the wrong target". The actuator is a **knob swept by a stepped wrist
yaw**, and the correct direction is a **sign**, not a location: with the band pinched on the control, a
single **−10° (world CW)** step gives `reward=1.0, terminated=True, task_completed=True`, while the full
**+120° (world CCW)** sweep — the direction `libero_goal_swap`'s own `turn_on_the_stove` needed — never
leaves `reward=0.0`. A full −120° CW ladder also ends at 1.0, so the off state lies clockwise of the grip
and over-rotating clockwise keeps it. Therefore derive the direction from the runtime string's polarity and
never from a constant:

```python
def stove_off_requested(text):
    words = set("".join(c if c.isalpha() else " " for c in text.lower()).split())
    if "off" in words:
        return True
    if "on" in words:
        return False
    return True          # neither word present -> assume the safer state

SWEEP_SIGN = -1.0 if stove_off_requested(TASK_LANGUAGE) else 1.0
```

The A/B is clean because the *grasp is held constant*: on seed 51 both revisions share the pinch target
`(0.2543, 0.1999, 0.0374)`, `yaw0 = -0.4`, `band_n = 395`, and `gap after pinch = 0.0247 m`; they differ
only in direction, and the scores are 0/15 (initial, `yaw -0.4 -> 119.6`) versus **15/15** (shipped,
`yaw -0.4 -> -120.4, sign -1`). The one executable diff between the two files is the `SWEEP_SIGN` line.

**Do not try to read the burner's glow as an online cue — it is thermally lagged.** The wrong direction is
not merely ineffective; it drives a burner **on**, which is visible as redness in the agentview. But the
signal arrives far too late to steer with. Measured with `redness_timeline.py` (`R - max(G,B)` in a crop
around the stove) over the saved keyframes of the *failing* CCW run (seed 51, 88 agentview frames, steps
0–1176): `maxred` is **19** for the first 51 frames, first exceeds 80 at **step 1095**, and holds at **145**
for the final 37 frames to the end of the episode — i.e. only in the last ~7%, *after* the sweep has
finished. The three successful runs never glow at all (`maxred` 19, 20, 20; `nred>80 == 0` in all three).
So a red-glow check cannot decide when to stop sweeping; it can only confirm the mistake afterwards.
Sources: `outputs/libero_fix_loop/libero_goal_task/turn_on_the_stove/findings.md` and
`…/fix_code.py` (lines 50–70); 2026-09-17.

**Generalisation across nine measured rows: the identifier is an opaque dispatch key.** It has now lied
about the relation, the support, the goal object, the *surface*, a positional descriptor, and finally the
**polarity of the goal itself**; and its noun is not a function of the payload. The runtime string has
never lied. The only safe reading is to parse the runtime string and treat the identifier as a key that
carries no goal information at all — including *which direction to turn a knob*.

Measured on 15/15 development seeds of `put_the_cream_cheese_in_the_bowl` (string constant, `TASK_LANGUAGE`
identical on every seed). Source:
`outputs/libero_fix_loop/libero_goal_task/put_the_cream_cheese_in_the_bowl/findings.md`; 2026-09-17.
Note this task's `initial_code.py` and `fix_code.py` are the same program (a docstring-only diff), so the
15/15 attests that reading the runtime string is *consistent with* a passing program — it is not an A/B
against an identifier-driven program.

The first identifier's noun is wrong **and** it is present in the scene as bait: two akita bowls sit in
that scene and neither is the goal. The payload is a **wine bottle** — a different object class from the
identifier's `bowl`, so the *grasp family* changes with the remap, not just the target's colour or
position (the `libero_object_task` form above). A program that reads the identifier gets a bowl task and
fails on a bottle scene. Measured on 15/15 development seeds; the string is constant across seeds.
Source: `outputs/libero_fix_loop/libero_goal_task/put_the_bowl_on_the_plate/findings.md`; 2026-09-17.

**The second row is a *partial* remap, and that is the case worth naming.** Here the identifier's
*relation* and *support* both survive — "push … to the front of the stove" is exactly what the
identifier says — and only the **object** is swapped, `plate → cream cheese`. So the remap does not have
to invert or negate anything for a program to break: a planner that reads the task and constructs a
push-to-a-reference-region plan from the *identifier* gets a valid plan for **the wrong payload**, which
is a failure that looks like a perception bug. Note the direction of the trap: the identifier's noun is
again bait, and here it is a **large flat object in the same scene** (a plate), the exact shape class
the localiser is looking for. Treat the runtime string as the sole source of the goal object even when
the relation around it is right. Source:
`outputs/libero_fix_loop/libero_goal_task/push_the_plate_to_the_front_of_the_stove/findings.md`; 2026-09-17.

**The third row repeats the partial shape and shows what the substitution can cost.** Here again the
support survives ("on the stove" is exactly what the identifier says) and only the object is remapped,
`bowl → plate`. But the substituted object is a **14 cm cone-rimmed plate whose `2·rmax` exceeds the jaw
opening**, so it cannot be pinched diametrally at all — the remap changes the **grasp mechanism**, not
just the payload. The generalizable reading: because `_task` identifiers are dispatch keys, a *partial*
remap (relation and support intact) is the hardest kind to notice, precisely because most of the
identifier checks out. The cost is not "the wrong object" but "a plan built for the wrong *kind* of
object" — see [grasp.md](grasp.md), "Pinch the Rim Band When the Object Is Wider Than the Jaws", for
what that costs when the mismatch is geometric. Ground the goal object from the runtime string and take
its geometry from the mask before choosing a grasp family. Measured on all 15 development seeds; the
string is constant across seeds. Source:
`outputs/libero_fix_loop/libero_goal_task/put_the_bowl_on_the_stove/findings.md`; 2026-09-17.

**The remap is not a synonym swap — it can invert, negate, and change the *support*.** Across all ten
`libero_spatial_task` tasks, **not one** identifier's implied relation matched its runtime instruction:

| task identifier (`libero_spatial_task`) | runtime `env.handle.task_language` |
|---|---|
| `…next_to_the_plate…` | "…next to the **ramekin**…" |
| `…from_table_center…` | "…next to the **plate**…" |
| `…in_the_top_drawer_of_the_wooden_cabinet…` | "…**on the top of** the wooden cabinet…" |
| `…next_to_the_cookie_box…` | "…**on the stove**…" |
| `…between_the_plate_and_the_ramekin…` | "…**not** between the plate and the ramekin…" |
| `…on_the_cookie_box…` | "…**on the top of** the cabinet…" |
| `…next_to_the_ramekin…` | "…next to the **cookie box**…" |
| `…on_the_ramekin…` | "…**on the cookie box**…" |
| `…on_the_stove…` | "…**on the top of** the cabinet…" |
| `…on_the_wooden_cabinet…` | "…**on the stove**…" |

Note the `cookie_box` rows: the **same product word** appears in three identifiers and remaps to three
*different* roles — the **stove** and the **cabinet top** as supports, and here the **cookie box** as
the *reference object* in a task whose identifier says `ramekin`. So the identifier's noun is not even
a stable key to the relation — treat the whole identifier as opaque, not just the preposition.

Note the `between_the_plate_and_the_ramekin` row: the relation is **negated** — "not between" — so a
selector that keys on the identifier's preposition picks precisely the wrong bowl, and there is no way
to infer the negation from the identifier at all. The same remap changes *which support* is named
(`top drawer` → *top of the cabinet*; `cookie box` → *stove*; `on_the_cookie_box` → *top of the
cabinet*), so the reference object must also come from the string.

**The remap is not injective, and it can swap two identifiers outright** — two of these ten facts are
worth carrying into any `_task` work:

* **Two identifiers share one instruction.** `…on_the_cookie_box…` and `…on_the_stove…` both read
  *"…on the top of the cabinet…"*, and `…next_to_the_cookie_box…` and `…on_the_wooden_cabinet…` both
  read *"…on the stove…"*. So a runtime instruction is **not** a key back to a task, and an instance or
  finding recorded against "the stove task" is ambiguous unless the identifier is stored with it.
* **Two identifiers are effectively swapped.** `…on_the_stove…` runs the *cabinet-top* instruction and
  `…on_the_wooden_cabinet…` runs the *stove* instruction. The identifier's support is therefore not
  merely wrong, it can be the *other task's* support — a selector that resolves "the support the
  identifier names" will confidently carry from the wrong piece of furniture, which is why the support
  must be resolved from the runtime string via its own footprint (see "The instruction names a
  *support*" above).

Practical rule for a `_task` suite: parse the runtime string for the relation **and** the reference,
print it on every seed, and treat the identifier as an opaque dispatch key that carries no goal
information. Sources: the ten `outputs/libero_fix_loop/libero_spatial_task/*/fix_code.py`, their
`findings.md` and their dev-seed logs, all 2026-09-16 (the last three rows from tasks 8/9/10, which
completed after this table was first written). On the sixth, `segment_sam3_text_prompt(rgb,
"cookie box")` scored **0.003** — the identifier's product word does not merely name the wrong
support, it does not ground at all.

### Screen the class FIRST, then apply the instruction's spatial relation

**Trigger**: the instruction names a spatial relation ("the bowl **next to the plate**") and the
scene holds two instances of an *identical mesh* plus a lighter look-alike decoy. Ranking by the
relation alone is then a coin flip, because the decoy and the true target can sit at the same
distance from the goal object.

```python
def black_class_pool(cands):
    """Keep only the target CLASS: the attribute prompt separates the meshes from the decoy;
    the measured diameter is a redundant back-up if the attribute prompt fails outright."""
    if not cands:
        return []
    best = max(c["black"] for c in cands)
    pool = [c for c in cands if c["black"] >= BLACK_CLASS_FRAC * best] if best > 0.3 else []
    if not pool:                                     # attribute prompt failed entirely
        big = [c for c in cands if max(c["e"][0], c["e"][1]) >= BIG_BOWL_DIAM]
        pool = big if big else cands                 # fall back to size, then to all
    return pool

def pick_target(cands, goal_xy):
    pool = black_class_pool(cands)                   # class first ...
    if not pool:
        return None
    for c in cands:
        c["dist"] = math.hypot(c["c"][0] - goal_xy[0], c["c"][1] - goal_xy[1])
    return sorted(pool, key=lambda c: c["dist"])[0]  # ... then the spatial relation
```

Two traps this avoids. First, **the product words in the instruction do not ground**: on
`pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate` the phrase `akita black bowl`
scored 0.09 at best, while the generic `black bowl` prompt scored 0.81 on the true meshes and 0.28
on the look-alike dish — prompt the *attribute*, not the product name (same lesson as "Prompt the
Packaging Word … Not the Product Word" below). Second, note which object the relation is applied
*to*: here the relation's job is to choose between two equal-score twins, so it must run on the
class-filtered pool, never on the raw candidate list.

**Why it works + evidence**: on that task seed 51 the twins scored 0.809 / 0.809 at `(0.663, 0.322)`
and `(0.493, 0.308)`, and the lighter dish scored 0.283; the decoy sat 0.301–0.333 m from the plate
against the true twin's 0.259–0.309 m — **within 2 mm** on seed 51, so a bare nearest-object rule
picks either one. The class screen followed by the relation selected the correct akita twin on
**all 15** development seeds (51–65). Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate/fix_code.py`
— `black_class_pool`, `pick_target_bowl`, `bowl_candidates`; 2026-09-15.

### …and when *no* prompt separates them, resolve the relation against ALL the objects it names

The rule above assumes an attribute prompt can carve out the target class. When it cannot — the
instruction names only a **relation**, and the candidates are the same object kind — the relation
itself becomes the selector, and it must be resolved against every reference the instruction names,
not just the most obvious one:

```python
def pick_goal_bowl(bowls, plate, ramekin):
    """Instruction: "the bowl between the plate and the ramekin" -> nearest the MIDPOINT of
    BOTH named references, not nearest to whichever one you happened to localize."""
    cx, cy = 0.5 * (plate[0] + ramekin[0]), 0.5 * (plate[1] + ramekin[1])
    return min(bowls, key=lambda b: math.hypot(b[0] - cx, b[1] - cy)), (cx, cy)

# A named container that no prompt grounds can still be identified by its geometry:
ramekin = sorted(cands, key=lambda c: max(c["e"][0], c["e"][1]))[0]   # smallest bowl-like object
bowls   = [c for c in cands if c is not ramekin]
```

**Why it works + evidence**: on
`libero_spatial_swap/pick_up_the_black_bowl_between_the_plate_and_the_ramekin_and_place_it_on_the_plate`
SAM3 grounded **all three** round objects for every bowl prompt tried — `bowl` 0.906–0.930,
`metal bowl` 0.914–0.941, `small bowl` 0.926–0.949 — while the word `ramekin` scored ~0.001 and only
`white bowl` / `cup` grounded it at 0.106–0.125. So the vocabulary separates *nothing* here, and the
target had to come from the relation. The margin between the goal bowl and the decoy under the
midpoint rule was 0.036–0.15 m across seeds 51–65 (seed 57: 0.092 vs 0.244) — never close — so the
relation is stable exactly where the prompt is not. Add a roundness screen (`min/max` horizontal
extent ≥ 0.70) to the candidate geometry: a spurious long blob at `(0.100, −0.036)`,
`ext = (0.077, 0.145, 0.110)`, otherwise passes the size filters. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_between_the_plate_and_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— `pick_goal_bowl`, `bowl_candidates`, `run`; 2026-09-15.

### The instruction names a *support* — select by its footprint, never by height or score

**Trigger**: the instruction is support-relative — "the bowl **on the stove**", "on the cookie box", "on
the ramekin" — and the scene contains a same-class look-alike that is **also elevated**. Then the usual
fallbacks all fail together:

```
prompt score:   decoy 0.891–0.926   vs   target 0.855–0.922     # the DECOY wins on most seeds
base z:         decoy 0.224         vs   target 0.026           # decoy is on the cabinet top
```

"The bowl that is not on the table" and "the bowl with the largest base z" both select the wrong
object, because **height alone cannot express "on the stove"**.

```python
def pick_on_stove(cands, stove, table_z=None):
    if not cands:
        return None
    if stove is not None:
        lo, hi = stove["lo"], stove["hi"]
        pool = [c for c in cands
                if lo[0] - FOOT_PAD <= c["cx"] <= hi[0] + FOOT_PAD
                and lo[1] - FOOT_PAD <= c["cy"] <= hi[1] + FOOT_PAD]
        if pool:
            return min(pool, key=lambda c: abs(c["base"] - stove["top"]))
        print("  no bowl inside the stove footprint", flush=True)
    if table_z is not None:
        raised = [c for c in cands if c["base"] > table_z + 0.008]
        if raised:
            return min(raised, key=lambda c: c["base"])
    return max(cands, key=lambda c: c["n"])
```

**Both tests are load-bearing.** The footprint test alone accepts anything that happens to sit on the
support; the `abs(base − support_top)` test alone is satisfied by an object resting on the *table*
inside that footprint, and would never accept the elevated decoy at all. `FOOT_PAD = 0.05` is slack
for an object overhanging the edge — the decoys sat 0.16 m and 0.30 m outside the padded footprint on
every seed, so the pad buys tolerance without admitting anything.

Note the third element: `z` for the grasp is measured from the **object's own base**, not the table, so
the same code grasps a bowl on the table and one 3.7 cm up on a raised support with no change.

**Evidence**: selected the correct object on **15/15** development seeds; every seed's printed candidate
list shows the decoy (base 0.224) rejected and the target (base 0.026) chosen. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate/fix_code.py`
— `pick_on_stove` lines 249–270, called from `run` line 511; 2026-09-15.

#### Anchor the relation to the *named support's own measurement* — never to a scene-level estimate

The footprint test above needs a `support_top` to compare against. **Where that number comes from is
what decides the whole episode.** On `libero_spatial_swap/pick_up_the_black_bowl_on_the_ramekin_and_place_it_on_the_plate`
the same-class decoy sits on the table and the target on the ramekin, and the two are separated by
bottom-z alone:

```python
def key(b):
    on_ramekin = 1 if b["lo"][2] > ramekin_top - ON_RAMEKIN_SLACK else 0   # SLACK ~ 0.012
    d_ram = math.hypot(b["cx"] - ramekin["cx"], b["cy"] - ramekin["cy"])
    return (-on_ramekin, d_ram)          # support-relative, NOT a table estimate
```

A first attempt instead derived `table_z = min(lo[2] over all candidates)`. **A dark side object whose
mask bottom-z runs *below* the table poisons that min** — the wooden cabinet here reads `zlo = −0.049`,
which dragged the estimated "table" 6 cm down, marked **both** bowls elevated, and sent every grasp of
the episode to the decoy. The scene-level statistic is not merely noisier than the support's own cloud;
it is *falsifiable by a distractor that is in no way related to the relation you are resolving*.

Two further points, both measured:

- The **distance tie-break is not decoration.** Once an earlier failed attempt has knocked the object
  down, nothing is elevated any more and `on_ramekin` reads 0 for every candidate; the in-plane distance
  to the support centre is then the only term that decides. It was also the deciding term on the 13/15
  seeds where the mask bleed below flipped `on_ramekin` to 0 (decoy 0.203–0.244 m from the ramekin
  centre vs 0.046–0.062 m for the stacked bowl).
- **Score and footprint do not separate same-class twins.** Seed 51: `bowl` scored 0.879 for the decoy
  and 0.715 for the target; footprints 0.102 vs 0.095. Ranking by either is a coin flip.

**Evidence**: correct target on **15/15** seeds in both sweeps, including the 13 where only the distance
term decided. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_on_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— `pick_target_bowl` lines 272–307 (key at 295–298); 2026-09-15.

#### …and when the support lookup fails, the raised candidate to keep follows the support the task *names*

The support-relative selection above needs a `support` object. What should the fallback do when the
support could not be localized at all? The tempting answer is "keep the raised candidate" — but there
can be **more than one raised candidate, on different supports**, and then the *direction* of the
fallback decides the object:

```
libero_spatial_swap/pick_up_the_black_bowl_on_the_wooden_cabinet...:
  target  bowl base 0.221   on the wooden cabinet (0.216 m tall)   <- the instruction's support
  decoy   bowl base 0.026   on the stove slab     (0.020 m tall)   <- identical bowl, 0.028 score margin
  max(raised, key=base) -> the TARGET      min(raised, key=base) -> the DECOY
libero_spatial_swap/pick_up_the_black_bowl_on_the_stove...:
  the same scene, but the instruction names the LOW support, so the direction inverts
```

So **the fallback is a property of the support the instruction names, not a constant** — and a sibling
task's default must not be inherited. Note the failure mode this creates in review: copying
`min(raised, key=base)` from the stove task into this one passes every test on the stove task and
silently returns the decoy here. Write the direction explicitly, print which branch fired, and note
which support the task names:

```python
if table_z is not None:
    # The instruction names the TALL support ("on the wooden cabinet"), so if the cabinet
    # lookup fails the raised candidate to keep is the HIGHEST one: the lowest raised
    # candidate here is the identical decoy on the 0.020 m stove slab.
    raised = [c for c in cands if c["base"] > table_z + 0.008]
    if raised:
        return max(raised, key=lambda c: c["base"])
```

**Evidence**: the primary footprint path localized the cabinet on **15/15** seeds (score ≥ 0.836,
`ext = (0.22–0.25, 0.25–0.26, 0.207)`) and selected the target (base 0.221) over the decoy (base 0.026,
outside the footprint) on 15/15; SAM3 score cannot do it at all (0.926 vs 0.898). The fallback itself is
a latent-bug fix and did not fire on any seed, which is exactly why it is worth recording — it is a
wrong-object trap that no seed would have exposed. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_on_the_wooden_cabinet_and_place_it_on_the_plate/fix_code.py`
— `find_cabinet` lines 205–234, `pick_on_cabinet` 265–292; 2026-09-15.

### Screen the *support* by its own geometry — its prompt fires on the other furniture too

Having decided to select *by* the support, the support lookup itself must be reliable. On the same
scene, `stove` scored the real slab at 0.70–0.86 — but the 0.21 m-tall drawer cabinet **also** answered
`stove` (0.20–0.25) and `wooden cabinet` (0.80), and the stove's own burner disc came back as a smaller
`stove`/`plate` mask. Taking the top score there is luck, not identification.

```python
for prompt in STOVE_PROMPTS:                      # ("stove", "burner", "stovetop")
    for m in sorted(segment_sam3_text_prompt(rgb, prompt), key=lambda x: -float(x["score"]))[:6]:
        pts = mask_to_world_points(m["mask"].astype(np.uint8), d, K, E)
        if pts is None or len(pts) < 200:
            continue
        lo, hi = np.percentile(pts, 2, axis=0), np.percentile(pts, 98, axis=0)
        w, dp, h = hi - lo
        if h > 0.10:                    # the cabinet is 0.21 m tall -> rejected
            continue
        if float(lo[2]) > 0.020:        # resting on the table
            continue
        if max(w, dp) < 0.10:           # a slab, not a fragment or the burner
            continue
        return dict(lo=lo, hi=hi, top=float(np.percentile(pts[:, 2], 95)), ...)
```

Three gates, each with a measured margin: **height** (stove 0.028 vs cabinet 0.209), **base level**
(stove −0.008 vs the table at −0.011), **width** (stove 0.176–0.182 vs the burner's 0.090 fragment).
The same shape as "Screen SAM3 Candidates by Geometry, Not by Score" below, applied to furniture: pick
gates whose margins sit *between* the competing objects. Take the support's **top** from the 95th
percentile of its own points (`top = 0.020` here) so the grasp height and release drop derive from the
support rather than the table.

**Evidence**: returned the true slab on **15/15** seeds (seed 51: `stove=(0.400,−0.106) top=0.020
ext=(0.182,0.116,0.029)`, extents 0.176–0.182 × 0.119–0.139 elsewhere); the cabinet was never
selected. Source: same `fix_code.py` — `find_stove` lines 190–219; 2026-09-15.

### A *stacked* object's mask bleeds through its support — clip the cloud at the support's measured top

**Trigger**: the instruction names an object *on* (or *in*) a support, and the object's mask bottom-z
comes out **at or below the level of the surface it is supposedly standing on**. SAM3 merges same-class
neighbours — a ramekin is bowl-class, a plate is bowl-class — so the mask of the supported object runs
down through the support and out onto the table. On
`libero_spatial_swap/pick_up_the_black_bowl_on_the_ramekin_and_place_it_on_the_plate` this happened on
**13 of 15** seeds: measured `zlo = −0.005` (table level) against `zlo = +0.028` (the ramekin's rim) on
the one natively clean seed.

The symptoms are **always downstream and never look like a perception bug**:

```
in-plane median centre dragged toward the support/table points
  -> the wall pinch is aimed 1-2 cm off and the fingers land ON the object and shove it
     (seed 52: bowl jumped (0.434,0.212) -> (0.403,0.286) on the first pinch)
b_lo under-reports the underside by ~3.5 cm
  -> tcp_to_bottom = gz - b_lo is ~3.5 cm too large
  -> the object is RELEASED 3.5 cm above the goal surface: dropped, not set down
     (landed 0.030-0.043 m off vs 0.011-0.025 m on the seeds whose mask was clean)
```

```python
# support = the named support object's own cloud (the ramekin)
sup = float(np.percentile(support["pts"][:, 2], 90))
d_sup = math.hypot(goal_obj["cx"] - support["cx"], goal_obj["cy"] - support["cy"])
obj = goal_obj["pts"]
if d_sup < 0.09 and goal_obj["lo"][2] < sup - 0.004:      # bleed-through detected
    cut = obj[obj[:, 2] > sup - 0.004]
    if len(cut) >= MIN_PTS:
        obj = cut
        print(f"  stacked bowl: clipped cloud at support top {sup:.3f}", flush=True)
cx, cy, lo, hi, obj = cloud_geom(obj)   # centre + underside now measured, not inferred
```

**This is not a heuristic threshold, it is the measurement.** The object's real underside *is* the
support's rim, so the clip restores the true centre *and* the true underside at once, and the release
height error drops out automatically because `tcp_to_bottom` is derived from the corrected `b_lo`. The
`d_sup < 0.09` guard is what keeps the clip off a same-class object that merely happens to share the
scene (the decoy bowl sat 0.203–0.244 m from the ramekin centre on every seed).

**Evidence**: 3659 → 2856 points on seed 51; after the clip every one of the 15 seeds reads
`zlo = +0.027..+0.029` instead of `−0.005`, and with the servo below the sweep is **15/15** (the two
failing seeds 51 and 61 flipped 0.000 → 1.000). Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_on_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— `run` lines 717–727; 2026-09-15.

### A mask that is only *part* of the object has no valid centre — gate a free-space read-back against an exact geometric offset

**Trigger**: you measure a *held* payload in free space (to re-derive its hang, or the offset that
turns the goal point into a release column) and feed the result straight into a control target. The
window you segment in has a floor, and if that floor is not clear of the payload the mask comes back as
a thin **arc** — the part of the payload visible above the floor — whose bounding box is a full radius
off the payload's axis. Nothing about an arc looks wrong: it is a plausible blob with a plausible
centre, and it is the *only* thing measured, so there is nothing to compare it against.

```
seed 59 repeat: air offset=(0.007,-0.049)   vs   pinch offset=(0.000,+0.051)
                -> sign of the wall offset flipped, release_xy 5 cm past the plate
                -> release_xy=(0.714,0.259) for a plate centred at (0.721,0.210)
```

Two independent guards, and they are cheap:

```python
off_pinch = np.asarray(grasp["off"], dtype=float)[:2]   # EXACT by construction: the tool was
off = off_pinch                                         # commanded to the wall at a measured radius
hb = held_bowl(rgb, d, K, E, cur[:2], grip_z - 0.11, 0.13)   # floor BELOW the payload's base
if hb is not None:
    off_air = np.clip(np.array([hb["c"][0] - cur[0], hb["c"][1] - cur[1]]), -0.08, 0.08)
    if float(np.linalg.norm(off_air - off_pinch)) < 0.020:   # ADOPT only where they AGREE
        off = off_air
    h_cand = grip_z - float(hb["lo"][2])
    if 0.002 < h_cand < 0.090:
        hang = h_cand
```

1. **Put the window floor below the payload's own base** (`grip_z − 0.11` for a payload whose base
   hangs ~0.05 below the grip site, not `grip_z − 0.09` which sat just under its rim). This removes
   the arc in the first place.
2. **When an exact estimate of the same quantity already exists, adopt the measurement only inside an
   agreement band.** A radial wall pinch gives one: the tool was commanded to the wall at a *measured*
   radius, so `grasp["off"]` is exact by construction and is a free reference for a noisy read-back.
   Where the two disagree, the **mask** is wrong, not the grasp — keep the exact value. The band here
   is 20 mm, ~2σ of the read-back's own noise; on every good reading the gate is a no-op
   (`d = 0.003–0.007`).

Generalise the second rule past payloads: **whenever two independent estimates of one quantity are
available, and one of them is exact by construction, use the other only where they agree — never blend
them and never prefer the perception measurement because it is fresher.** A disagreement is itself the
signal, and it costs one subtraction to compute.

**Evidence**: seed 59's repeat put `release_xy` 5 cm past the plate from a sign-flipped arc centre; the
agreement gate rejects exactly that reading and is a no-op on the good ones. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate/fix_code.py`
— `carry_and_place`, free-space block, `held_bowl` window; 2026-09-16. Related: the *inverse*
contamination — a carried mask that absorbs the **gripper** — is
`knowledge/skill-code-instances/localize/localize.avoid-held-object-mask-contamination.yaml`.

### When neither score nor geometry separates them, rank by a colour descriptor of the mask

**Trigger**: the text prompt does not ground at all — the top score is below ~0.4 and two candidates sit
within a few percent of each other — *and* the geometric screen does not separate them either, because
the two objects are the same kind of thing (here: nine of the ten objects in the object suite are "a
box"). Such a scene is not solvable by a better prompt alone, so the last observable that distinguishes
the target is its **appearance**: the colour of its packaging.

```python
px = rgb[mask.astype(bool)].astype(np.float64)      # mask = this candidate's mask
warm = 0.0
if len(px):
    warm = float(((px[:, 0] > 1.4 * px[:, 1]) & (px[:, 0] > 1.4 * px[:, 2])
                  & (px[:, 0] > 90)).mean())
# collect EVERY candidate that survives the geometric screen, then:
warm_c = [k for k in cands if k["warm"] >= WARM_MIN]
pool = warm_c if warm_c else cands
pool.sort(key=lambda k: (-k["warm"], -k["score"]))
return pool[0]
```

`warm` is the fraction of mask pixels that are saturated red — red channel more than 1.4× both other
channels and above 90. It is a *descriptor of the target*, used exactly the way a SAM3 prompt is: no
ground truth is read, and the pixel test is a property of the observation. Keep the geometric screen as
the outer gate (it rejects the tall/wide distractors cheaply) and use the colour descriptor only to rank
what survives it — here it also re-ranks the *right* candidate to the top even when a different prompt
ranked it second.

**Why it works + evidence**: on `libero_object_swap/pick_up_the_butter_and_place_it_in_the_basket` the
butter's warm fraction measured 0.392–0.418 across all 15 development seeds against 0.033–0.034 for the
chocolate-pudding box — a >10× margin against a `WARM_MIN = 0.15` threshold that **no seed ever came
within 0.2 of**. Compare with the score margin on the same object: 0.090 vs 0.108, i.e. the wrong
ordering. Source: `outputs/libero_fix_loop/libero_object_swap/pick_up_the_butter_and_place_it_in_the_basket/fix_code.py`
— `find_box`; 2026-09-14.

### Rank same-class distractors per *physical object* by an intrinsic colour signature

**Trigger**: the scene holds two or more objects of the *same class* — several bottles, several boxes —
and the task names exactly one. This is a stricter failure than the one above: the prompt does not
merely rank badly, it ranks the **wrong object first on every phrasing**, because a whole-class prompt
prefers the bigger, brighter instance. On
`libero_object_swap/pick_up_the_bbq_sauce_and_place_it_in_the_basket` the amber decoy bottle scored
0.129–0.15 on `bbq sauce` against the true sauce's 0.002–0.147, 0.238–0.348 vs 0.006–0.381 on `ketchup`,
and 0.957 vs 0.945 on `bottle`. **Prompt score is not an identity signal when two objects share a class.**

Two changes make the colour descriptor do the work:

1. **Group candidates per physical object before ranking.** SAM3 returns the same bottle under several
   prompts; unioning the masks that share a centroid recovers *one* object's full mask and stops a
   single bottle from occupying two ranking slots. **The merge radius matters more than it looks** —
   the 2 cm used here was later found to be too small (a cap and a shoulder fragment each sit within
   2 cm of their own bottle, so one bottle became 10 groups); see "Prune candidate groups
   largest-mask-first" below, which supersedes this radius.
2. **Rank by an intrinsic signature, not a threshold.** Use `sat - val` of the group's *median* body
   colour, so a dark near-fully-saturated target beats a lighter, brighter one.

```python
def mask_colour(rgb, mask):                    # -> (median_rgb, sat, val)
    px = rgb[mask > 0].astype(np.float64)
    if len(px) < 50:
        return None
    med = np.median(px, axis=0); mx = float(med.max())
    if mx <= 1e-6:
        return None
    return med, float((mx - float(med.min())) / mx), mx / 255.0

# groups: candidates bucketed by centroid within 2 cm, unioning their masks
for g in groups:
    med, sat, val = mask_colour(rgb, g["union"])
    g["rank"] = sat - val
best = max(groups, key=lambda g: g["rank"])
if best["colour"] is None or best["colour"][1] < 0.85:      # signature unavailable
    best = max(groups, key=lambda g: g["best"]["score"])    # fall back to prompt rank
```

Keep an explicit **fallback gate** (`sat < 0.85`) so a scene where the signature is unavailable degrades
to the prompt ranking rather than to `max()` over an unusable list.

**Why it works + evidence**: on the bbq_sauce task the decoy's `sat - val` was 0.159–0.253 while the true
sauce measured 0.744–0.773; the worst runner-up over seeds 51–65 was 0.479, i.e. a margin **≥ 0.28 on
every** development seed. Switching the selector took the task from **0/15 to 15/15**. The selector uses
no position information, which matters because `libero_object_swap` is position-generalization only: the
appearance signature is a portable identity key, and the observed position cluster (x ∈ [0.483, 0.501])
is not load-bearing. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_bbq_sauce_and_place_it_in_the_basket/fix_code.py`
— `find_bbq`, `bottle_candidates`, `mask_colour`; 2026-09-14.

Prefer this when the script must **choose among** same-class objects; use the `warm`-fraction threshold
above when the descriptor only has to **admit or reject** one target.

#### An *exact* prompt tie is not a near-tie — it is mask order, and the outcome stops tracking the program

Everything above assumes the prompt rank is at least *ordered*, even when it is wrong. When two
candidates of the class receive the **same** score that assumption fails outright: `sorted(..., key=-score)`
is a stable sort with nothing left to compare, so the winner is whichever mask SAM3 happened to return
first. The task outcome is then **uncorrelated with anything the program does** — the failure is not in
the grasp, the carry or the release, all of which are executed perfectly on the losing seeds.

**Diagnostic**: grep the candidate dump for two identical `score=` values on different candidates. The
signature in the episode log is the worst kind to debug — identical grasp, carry and release lines on
two seeds, one scoring 1.000 and the other 0.000, with no behavioural difference to fix.

**And no prompt repairs it.** On `libero_object_task/pick_up_the_orange_juice_and_place_it_in_the_basket`
(the runtime language names a *different* object than the directory does) the scene holds two small flat
brown boxes: `brown box` scored **0.559 / 0.559** on seed 58 and **0.617 / 0.617** on seed 64. Ten
alternative phrasings were probed on the failing seed — `dark brown box` 0.414 / 0.402, `maroon box`
0.206 / 0.188, `brownie box` 0.138 / 0.138 (a tie again), `chocolate box` 0.100 / 0.096, `chocolate`
0.071 / 0.069, `dark box` 0.369 / 0.365, and the product word itself at 0.001 / 0.006 / 0.050 — so the
best margin *any* phrasing achieves on the pair whose identity is in question is **0.018**, against a
colour margin of 22.6 levels on the same pair. When the class-level prompt ties, the prompt is a
**recall device only**: it decides which candidates *exist*, never which one is the target. The
geometric screen does not help either — the two boxes differ by 9 mm in extent and 10 mm in height,
which is the same size as their pose-to-pose variation.

Source: `outputs/libero_fix_loop/libero_object_task/pick_up_the_orange_juice_and_place_it_in_the_basket/fix_code.py`
— `screen_candidates` lines 98–132 (the score sort at 107, the descriptor at 116–121); 2026-09-16.

#### Variant — a *signed channel difference* needs no tuned constant

`sat - val` above is one way to build the signature. A cleaner one, when the distinguishing feature is a
label printed on otherwise similar packaging, is a **signed difference of two channel means over the
candidate's own mask**:

```python
px = rgb[mask.astype(bool)].astype(np.float64)              # this candidate's own mask
if len(px) < 50:
    continue
descriptor = float(px[:, 2].mean() - px[:, 0].mean())        # B - R for a blue label
# collect EVERY candidate that survives the geometric screen, then take the extreme:
target = max(cands, key=lambda k: k["descriptor"])
```

Pick the channel pair from the target's packaging — `B − R` for a blue label, `R − max(G, B)` for a red
one — and let the sign carry the decision. Because it is a *difference* of two means over the same
pixels, the scene's lighting level cancels; because it is *signed*, there is no absolute threshold to
tune and no seed on which the constant happens to land near the boundary.

**Choosing between the two forms**: use the signed difference when one channel's level is stable across
the candidates (it is the safer default — no constant); use the thresholded fraction when a single
specular highlight could swing a mean (a fraction over many pixels resists one bright outlier better).

**Why it works + evidence**: on
`libero_object_swap/pick_up_the_alphabet_soup_and_place_it_in_the_basket` two soup cans of **identical
geometry** (6.1 cm diameter, 7.8 cm tall) share the scene, and no prompt separates them —
`can of alphabet soup` (0.773 / 0.621) and `can of tomato sauce` (0.641 / 0.436) both rank the *same*
wrong can first because the score tracks apparent size, and a bare `alphabet soup` (0.094) lands on the
milk carton. `blueness = mean(B) − mean(R)` separated **+1.0 (target) vs −14.2 (distractor) on all 15
development seeds**, no overlap, no constant. Single-can reward probes confirmed the identity
independently: placing only the can at `(0.402, −0.083)` scored 1.000, placing only the can at
`(0.752, 0.027)` scored 0.000. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_alphabet_soup_and_place_it_in_the_basket/fix_code.py`
— `find_cans`, `pick_target`; 2026-09-14.

**A second instance, and the rule for choosing the *direction* of the difference.** On
`libero_object_task/pick_up_the_orange_juice_and_place_it_in_the_basket` two flat brown boxes tie at an
identical prompt score (see above), and the separator is
`chroma = mean(B) − max(mean(R), mean(G))`: the target's dark maroon box reads **−24.2…−24.3 on all 15
development seeds** (spread 0.1), its look-alike **−46.9…−48.3**, and a 4 × 1.5 cm orange carton
fragment that also survives the screen on 6 seeds **−73.6…−74.2** — a **≥ 22.6 level margin with no
overlap**, against a 0.000 score margin on the very same pair. Two things carry over:

- **Choose the direction by where the *non-targets* land, not by where the target lands.** `max(chroma)`
  is correct here because it *also* rejects the orange fragment; `min(chroma)` would have selected it.
  Measure the whole surviving set once and check that the target is the extreme **and** that every other
  candidate is on the far side of the axis. A sign chosen from the target alone can be right about the
  target and wrong about the field.
- **Keep the hue/saturation gate in front of it**, because a `max()` over the axis is otherwise decided
  by whatever bright neutral mask appears — see the next variant. Here the two real boxes read sat 0.42
  and 0.59 while the basket liner reads 0.07, so `SAT_MIN = 0.18` never touches a real candidate; that
  gap is the reason to set the gate from measured values rather than from a round number.

This pair is also the cleanest negative result in the library for the *geometric* screen: the two boxes
differ by 9 mm in extent and 10 mm in height — the same size as their own pose-to-pose variation —
while the descriptor's spread across seeds is 0.1 level against a 22.6 level margin, i.e. the colour
axis is ~200× the noise and every geometric statistic is ~1× it. Source: same `fix_code.py` —
`pick_candidate` lines 135–156 (admission at 150, ranking at 156); 2026-09-16.

#### Admit by hue *before* ranking — a neutral non-object can hold the extreme of the colour axis

The signed-difference variant above takes `max(distance, key=...)` over every candidate that survives
the geometric screen. That is unsafe whenever SAM3 also returns a **bright neutral** mask of a
non-object — the basket liner, a wall, the table edge. Such a mask has no hue, so it can sit at the
extreme of *any* axis that measures "how much of one channel is present", and a single-stage ranking
then returns it instead of the target.

**Fix: two stages — admit by hue, then rank by the difference.**

```python
# stage 1 -- admit: the target's packaging is *chromatic in the right direction*
warm = [c for c in cands if c["R"] - c["B"] > WARM_MIN]     # rejects neutral grey masks
pool = warm if warm else cands                              # never rank an empty list
# stage 2 -- rank: the signed channel difference, maximised
target = max(pool, key=lambda c: c["B"] - c["R"])
```

**Why two stages**: the descriptor that *identifies* the target (white label content, i.e. a higher `B`)
is also the descriptor a bright grey distractor maximises. The admission removes every neutral mask on a
property the *class* has and the distractor lacks; only then does the `B − R` ranking measure "how much
white is on a red label". Note the admission need not be the class's *defining* property — it only has
to be a property the distractor lacks.

**Why it works + evidence**: on `libero_object_swap/pick_up_the_milk_and_place_it_in_the_basket` the
scene holds two bricks whose measured extents agree to the millimetre (milk 14.3 × 5.9 × 4.4 cm vs
orange juice 14.2 × 5.4 × 3.0 cm), the whole-class prompts tie **exactly** (`juice box` 0.922 / 0.922,
`box` 0.805 / 0.805, `carton` 0.754) and the product prompt leans right by only 0.047–0.080. SAM3 also
returns the basket liner as a tall "carton" candidate: 300 points, z-extent 0.140, **`R − B` = 10.2**,
per-pixel min channel 104, x-width 0.289 m. Since the milk's `B − R` is −39.6 and the juice's is −62.9,
a bare `max(B − R)` returns the grey liner. The two-stage form — `WARM_MIN = 20` then `max(B − R)` —
selected the milk brick with a **≥ 22.7 grey-level margin (milk −39.5…−40.0 vs juice −62.7…−63.0) on all
15 development seeds**, exactly 2 candidates every seed and no seed within 20 levels of flipping, and
the liner never appeared as a candidate on any seed. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_milk_and_place_it_in_the_basket/fix_code.py`
— `pick_milk` (admission/ranking pair), `find_cartons` (geometry screen); 2026-09-14.

**This supersedes the bare-`max(blueness)` form recorded for the alphabet-soup task above.** That
selector was correct *on that scene* only because no neutral mask outranked the target there; it is not
the general form. When reusing a colour rank on a new scene, first check what the *most extreme*
candidate is — if it is grey or white, the ranking needs an admission stage in front of it.

**How small the margin can get, and what then actually holds the rank.** On
`libero_object_task/pick_up_the_cream_cheese_and_place_it_in_the_basket` the two cans share geometry
exactly and the target's own `B − R` margin was only **+0.5** — a value small enough that any bright
neutral mask would outrank it, which is precisely the hazard above. What kept the rank correct was the
**numeric size and extent gate**, not the descriptor: the basket mask carries **11935–12312 points**
against a 9000 cap and a **0.19 m** extent against a 0.14 cap, so it never becomes a candidate at all;
the sibling can is excluded by the descriptor (−17.4), giving a **≥ 17.9 grey-level margin on all 15
development seeds**. The lesson is that "screen then rank" is only safe when the screen's caps are set
from *measured* distractors — a 9000-point cap is doing real work here and a round-number 10 000 would
have admitted the basket. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_cream_cheese_and_place_it_in_the_basket/fix_code.py`
— `find_can_candidates` lines 122–180 (the gate at 140–151), `pick_target_can` line 195; 2026-09-16.

#### Variant — rank on *saturation itself* and the admission stage disappears

The two stages above exist because the rank key is a **signed channel difference**, and any neutral
mask can sit at one extreme of a difference. Change the key and the hazard changes with it. If you rank
on `sat − val` (saturation of the mask's median body colour, minus its value), a neutral cannot win:
a grey has `sat ≈ 0`, so its descriptor is `−val < 0`, strictly below every chromatic candidate. The
single stage is then already safe — and cheaper, since it needs no threshold to tune.

```python
def mask_colour(rgb, mask):
    """Median body colour -> (sat, val, signed descriptor)."""
    px = rgb[mask > 0].astype(np.float64)
    if len(px) < 50:
        return None                       # too small to have a colour
    med = np.median(px, axis=0)           # median, not mean: survives a specular highlight
    mx = float(med.max())
    if mx <= 1e-6:
        return None
    sat = (mx - float(med.min())) / mx
    val = mx / 255.0
    return dict(med=med, sat=sat, val=val, desc=sat - val)
# ... rank:  max(pool, key=lambda g: (g["col"]["desc"], g["score"]))
```

**Why the `− val` term is not decoration.** Plain `sat` alone is degenerate on this scene: the goal
bottle and the runner-up carton both read `sat = 1.00` at the median, so a bare `max(sat)` ties and the
outcome collapses onto candidate order — the same failure as an exact prompt tie. Subtracting `val`
breaks the tie along brightness: the goal is the *darker* of the two fully-saturated objects.

**Measured** on `libero_object_task/pick_up_the_tomato_sauce_and_place_it_in_the_basket` (dev seed 51,
whole-mask median colour; target and runner-up stable on all 15 seeds):

| candidate | median RGB | sat | val | `sat − val` |
|---|---|---|---|---|
| **goal bottle** | (62, 20, 0) | 1.00 | 0.24 | **+0.757** |
| orange-juice carton (runner-up) | (80, 55, 14) | 0.82 | 0.31 | +0.511 |
| red-labelled can | (58, 48, 29) | 0.50 | 0.23 | +0.273 |
| milk carton | (89, 51, 40) | 0.55 | 0.35 | +0.202 |
| **basket outer mask** | (149, 146, 136) | 0.09 | 0.58 | **−0.497** |

The basket mask is the **brightest object in the scene** — `val` 0.58, the maximum of the whole table —
and it still lands at the *bottom* of the axis, because saturation drives it there. That is the whole
point of the variant: the property that made the neutral dangerous (`val`) is the same property that
now buries it. Margin target − runner-up was **+0.242, +0.244, +0.246, +0.250** across seeds 51–65
against a *constant* 0.511 runner-up; no seed came within 0.24 of flipping. 15/15 development seeds.
Source: `outputs/libero_fix_loop/libero_object_task/pick_up_the_tomato_sauce_and_place_it_in_the_basket/fix_code.py`
— `mask_colour` lines 105–116, consumed by `find_goal` lines 196–197; 2026-09-16.

**When to prefer it, and when not.** Prefer `sat − val` when the target's identity *is* its colourfulness
(a deeply saturated label against washed-out siblings) — here the goal bottle is the only object on the
table at full saturation. Do **not** reach for it when the identity is a *hue* (blue can vs red can):
both are fully saturated, the descriptor ties, and you need the signed-channel form instead. The rule is
the same one as everywhere else in this file — pick the key that is extreme for the target and *not*
extreme for the distractor you are actually afraid of.

#### The hazard can also be a *warmer* non-target — and then admit-by-hue cannot help at all

The admission stage above exists to remove a mask that sits at the extreme of the colour axis *without*
being chromatic. That fix has a blind spot, and it is the one a warm-labelled target walks into: when
the rank key is `R − B` and a **different-class object on the same table is warmer than the target**,
the admission and the ranking measure the *same axis*. Anything warmer passes the admission **and** wins
the rank. Two stages over one axis are one stage.

On `libero_object_task/pick_up_the_salad_dressing_and_place_it_in_the_basket` (the runtime instruction
names a *different object*, see the remap table) the goal is the **red-labelled can** at `R − B = +20.0`
against the identical-geometry blue alphabet-soup can at `−1.5` — a stable 21.4–21.5 margin, plenty.
But the amber bbq-sauce bottle reads **+36.3** and the milk carton **+41.4**: **both warmer than the
target**, so `max(red)` over the surviving set returns the bottle, and the admission stage admits it.

**What actually holds the rank here is the geometry screen, and the lesson is the size of its caps.**

```python
CAN_H_LO, CAN_H_HI = 0.045, 0.105   # goal can zhi-zlo 0.077-0.079; bottles/carton 0.136-0.144
CAN_MAX_EXT = 0.13                  # goal can max OBB extent 0.091-0.098; others 0.144-0.148
ext = np.sort(np.asarray(obb["extent"], dtype=np.float64))
if (zhi - zlo) > CAN_H_HI:          # the term that rejects the warmer distractors
    continue
if ext[2] > CAN_MAX_EXT or ext[0] < 0.025 or ext[1] < 0.025:
    continue
```

The amber bottle's `zhi` is **0.148**, so a round-number `0.15` cap would have **passed it** and the rank
would have returned the bottle with no error anywhere. The measured cap `0.105` sits **3.1 cm** below
the shortest distractor. The `max(extent) ≤ 0.13` gate independently rejects the same two objects
(0.144 / 0.148) — the two gates are deliberately redundant because they fail differently: the cloud
percentile needs no OBB fit and gave a **> 5.5 cm** separation here, while the OBB cap alone would have
left only **1.4–4.8 mm** against the same two distractors, a margin a thin bottle's depth noise can eat
in one frame. **Give the screen an absolute height gate (`zhi − zlo`) whenever the goal is the shortest
object of its kind on a table holding taller ones.**

**Evidence**: exactly 2 candidates on all 15 development seeds; the two distractors that outrank the
target on the rank axis (+36.3, +41.4) never became candidates on any seed; target `red` +20.0, sibling
−1.5, margin 21.4–21.5 with no seed within 21 levels of flipping. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_salad_dressing_and_place_it_in_the_basket/fix_code.py`
— `find_can_candidates` lines 141–209 (height gate 172–176, extent gate 179–180, descriptor 195),
constants 39–44, `pick_target_can` 225–241; 2026-09-16.

#### Variant — restrict the signed difference to the *cap band*, and take a median not a mean

`libero_object_task/pick_up_the_chocolate_pudding_and_place_it_in_the_basket` (runtime language "pick
the salad dressing" — the object is remapped) adds a refinement to the `B − R` form: the identity lives
on the **cap**, while the bottle body is neutral-to-dark and dilutes a whole-mask mean toward zero. So
compute the signed difference over the **top quarter of the mask's row span** only:

```python
CAP_GREEN_MIN = 12.0

def cap_signature(rgb, mask, frac=0.25):
    """Signed green difference of the top band of the mask (the cap)."""
    mk = mask > 0
    ys = np.where(mk.any(axis=1))[0]
    if len(ys) == 0:
        return -999.0
    y0, y1 = int(ys.min()), int(ys.max())
    cut = y0 + int(frac * (y1 - y0)) + 1
    cap = np.zeros_like(mk)
    cap[y0:cut, :] = mk[y0:cut, :]
    cpx = rgb[cap].astype(np.float64)
    if len(cpx) < 30:
        return -999.0
    med = np.median(cpx, axis=0)
    return float(med[1] - max(med[0], med[2]))          # G - max(R, B): signed, and warm-safe
```

Three parts are separately useful and worth keeping even if you drop the band: the band restriction
itself; a **median** rather than a mean, so a specular highlight on the plastic cannot swing the axis;
and `minus max(R, B)` so the descriptor is signed for a green target rather than confounded with a warm
one.

Screen first, then rank, exactly as above — but note the screen is the *opposite shape* from the
flat-box case: this object is **tall and narrow**, so the gates are `ext_z >= 0.055`, `ext_z >= 1.15 *
max(ext_x, ext_y)`, `max(ext_x, ext_y) <= 0.10`, `lo_z <= 0.035`. The per-task screen changes; the
"screen then rank" structure is what generalizes. Candidates are then group-pruned at **4 cm** by
descending mask size, so one object's mask fragments cannot occupy several slots:

```python
kept = []
for g in sorted(cands, key=lambda g: -int(g["mask"].sum())):
    if all(float(np.linalg.norm(g["c"][:2] - k["c"][:2])) > 0.040 for k in kept):
        kept.append(g)
green = [k for k in kept if k["cap_green"] >= CAP_GREEN_MIN]
best = max(green, key=lambda k: k["cap_green"]) if green else max(kept, key=lambda k: k["score"])
```

**Evidence**: the target reads **+26 / +27** on the cap-green axis while every sibling reads **≤ −2.0**,
so `CAP_GREEN_MIN = 12.0` sits in a gap of ~28 levels. The threshold is a *measured* gap, not a
round number. On all 15 development seeds the prompt list is derived from the runtime string
(`"dressing" in lang` promotes `green bottle` to the head of the list), which is what makes the
identity check a confirmation rather than a search. Source:
`outputs/working_codes/libero_object_task_pick_up_the_chocolate_pudding_and_place_it_in_the_basket_fix.py`
— `cap_signature` lines 135–149, `find_target` lines 152–196; 2026-09-16.

**Caveat — the band is in *image* rows, so it is only the cap if the object is upright in the frame.**
That held on every seed here (the scene camera sees the table from above and the bottle stands). On a
scene where the object may be lying down, take the band from the object's own `R` axis instead of from
image rows, or the "cap" will be an arbitrary slice of the body.

**The same band, on the neutrality axis instead of the hue axis.** The descriptor need not be a signed
*hue* difference — when the discriminating property is that a cap is **grey**, use the band's
*desaturation* instead:

```python
def mask_colour(rgb, ys, xs, top_row):
    """Mean body colour and top-band colour/saturation of a mask."""
    px = rgb[ys, xs].astype(np.float64)
    mx, mn = px.max(axis=1), px.min(axis=1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1.0), 0.0)
    top = ys < top_row          # top_row = box[1] + 0.25*(box[3]-box[1])  -> the CAP band
    tb = px[top] if top.any() else px
    tmx, tmn = tb.max(axis=1), tb.min(axis=1)
    tsat = np.where(tmx > 0, (tmx - tmn) / np.maximum(tmx, 1.0), 0.0)
    return dict(mr=float(px[:, 0].mean()), mb=float(px[:, 2].mean()),
                sat=float(sat.mean()), tsat=float(tsat.mean()))

sized = [c for c in cands if H_MIN <= c["h"] <= H_MAX and max(c["dx"], c["dy"]) <= FOOT_MAX]
warm  = [c for c in sized if (c["mr"] - c["mb"]) > WARM_MIN and c["tsat"] < TOP_NEUTRAL]
target = max(warm, key=lambda c: c["sc"]) if warm else max(cands, key=lambda c: c["sc"])
```

On `libero_object_task/pick_up_the_bbq_sauce_and_place_it_in_the_basket` (runtime language "pick the
ketchup") the target's cap saturation is **0.03** against **0.95–0.98** for the two saturated-capped
siblings and 0.23–0.39 for the box/can distractors — so `tsat < TOP_NEUTRAL` is the load-bearing term
and it alone does the separation. The two supporting gates are not decoration: `mr − mb > WARM_MIN`
rejects the grey can (−1.8) and the blue box (−21.0), and the **footprint** gate rejects the basket
(0.162 m) — which also has a near-neutral top band (**0.01**) and would otherwise be a false positive
that passes the cap test. The two-pool fallback (`warm` else all candidates) keeps an unexpected scene
degrading to the top score rather than crashing. 15/15 development seeds, the target seated at
(0.458–0.459, 0.058) with score 0.949–0.957 every seed.

**The role this cue plays is set by the runtime language, not by the cap.** This is the sharpest
`_task`-suite lesson in the row: the neutral-grey cap is the **decoy's** tell when the goal is bbq
sauce (see the bbq-sauce row above) and the **target's** tell when the goal is ketchup — the same
physical object, the same measurement, opposite sign of usefulness. It is a reliable *object*
signature; never hardcode which side of the comparison it belongs on. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_bbq_sauce_and_place_it_in_the_basket/fix_code.py`
— `mask_colour` lines 58–72, `bottle_candidates` lines 75–103, `pick_ketchup` lines 106–129 (the gates
at 116–121); 2026-09-16.

#### Variant — *white label content* separates a carton from its bottle siblings when no prompt does

A different descriptor for a different class split. Here the target is a **carton** and its rival is a
**bottle** of the same product family — the same shape of problem as the entries above, but no hue
channel separates them, because the target is the *achromatic* one.

```python
WHITE_MIN      = 0.02
WHITE_CUE_NOUNS = ("milk", "orange juice", "cream cheese", "butter", "chocolate pudding")

def mask_features(rgb, mk):
    ys, xs = np.where(mk)
    if len(ys) < 100:
        return None
    px = rgb[ys, xs].astype(np.float64)
    white = float((px.min(axis=1) > 120).mean())      # min(R,G,B) > 120 => near-neutral AND bright
    return {"white": white, "n": int(len(ys))}

def pick_target(cands, noun):
    if noun not in WHITE_CUE_NOUNS:                   # the cue is NOT universal (see below)
        return max(cands, key=lambda c: c["score"])
    white = [c for c in cands if c["white"] >= WHITE_MIN]
    pool = white if white else cands                  # degrade to prompt score, never crash
    return max(pool, key=lambda c: (c["white"], c["score"]))
```

**Two details are load-bearing, and both are about placement rather than the descriptor.**

- The **geometry screen must be the outer gate**, never the colour rank on its own. On this scene the
  *basket* reads `white = 0.62` — far above the carton's 0.04 — so a bare `max(white)` over all masks
  selects the container. Screen by height/footprint/base-level first (this removes the basket, a flat
  1.8 cm box and a 7.8 cm can), *then* rank.
- Restrict the cue to the **nouns it was measured on**. The white read is not a general-purpose
  "target-ness" score: applied to any other noun it would confidently select the milk carton. Written
  as an explicit allow-list, the program degrades to a plain prompt-score rank elsewhere instead of
  silently mis-selecting — the same lesson as "Calibrate the descriptor to *this* target" below,
  enforced in code rather than in a comment.

**Evidence**: the fraction of mask pixels with `min(R,G,B) > 120` reads **0.036–0.045 for the milk
carton** against **0.002–0.008** for all three bottles, the can and the flat box — a ≥4.5× margin on
every one of the 15 development seeds, with the runner-up never within 0.028. No prompt does this job:
`milk` scores the carton 0.177, `milk carton` 0.338, and the packaging word `box` ranks the *flat blue
box* above it (0.621 vs 0.500). One prompt does rank the carton first — `juice box` at 0.910–0.918 —
which is a packaging-word coincidence, not an identity test, and is exactly the kind of lucky constant
this descriptor replaces. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_ketchup_and_place_it_in_the_basket/fix_code.py`
— `mask_features` lines 151–161, `pick_target` lines 248–268; 2026-09-16.

#### When the decoy is the *dark* version of the target's hue, use a hue *conjunction* fraction

A single signed channel difference has one failure mode the two variants above do not cover: **the
decoy shares the target's hue and differs only in brightness.** A saturate-and-dark red has almost as
much `R − B` as a bright orange-tan, so the difference separates them but thinly — and if the decoy is
the *darker* one, a brightness-blind axis favours it.

**Fix: make the descriptor a conjunction of channel *ratios* plus a brightness floor**, i.e. a
*fraction* over the mask rather than a difference of means:

```python
def orange_frac(px):
    """Fraction of mask pixels that are bright orange (warm WITH green in it)."""
    if len(px) == 0:
        return 0.0
    R, G, B = px[:, 0], px[:, 1], px[:, 2]
    return float(((R > ORANGE_R_B * B) & (G > ORANGE_G_B * B) & (R > ORANGE_MIN_R)).mean())
# 1.15                 1.05                   120
```

Each term does a distinct job, and all three are needed:

- `R > 1.15 · B` — the hue is warm.
- `G > 1.05 · B` — the warm hue still has green in it, which is what makes it **orange** rather than
  merely **red**. This is the term that discards the decoy: a saturated red (R 58 / G 25 / B 8) and a
  warm brown both have a large `R − B` but little green, so they collapse toward 0.
- `R > 120` — a brightness floor, calibrated from the target's *label* pixels (its mean mask R is 90.7,
  but the label runs above 120 and those pixels are the ~21% the fraction counts).

**Why a fraction beats a difference here**: the two are not independent — the fraction is the
difference plus a threshold — but the fraction is *scale-free* and the difference is not. On this
scene the target's `R − B` is 62 against the decoy's 50 (a **24 %** separation, which any lighting
change could close), while the fractions are 0.207 against 0.001 (a **3400 %** separation), because the
decoy's dark pixels fall out of the numerator entirely rather than merely scoring lower.

**Why it works + evidence**: on
`libero_object_swap/pick_up_the_orange_juice_and_place_it_in_the_basket` the scene holds four tall
siblings that all pass a geometry screen — the target (2.7 × 5.0 × 13.4 cm), a **milk carton**
(2.8 × 5.7 × 14.3 cm — a 9 mm height difference, so geometry cannot screen it), a ketchup bottle and a
dressing bottle. The measured fractions were target **0.206–0.207**, milk carton **0.006**, ketchup
0.001–0.002, dressing bottle 0.000, on **all 15 development seeds** — a 34× margin with no seed within
0.19 of the boundary. Bare `R − B` would have separated the target from the ketchup by 12 grey levels
only, and bare `B − R` would have ranked the *milk* carton first. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_orange_juice_and_place_it_in_the_basket/fix_code.py`
— `orange_frac` (the three-term predicate), `pick_orange_juice` (the admit-then-rank pair); 2026-09-14.

**Choosing among the descriptor families so far**: distinguish the decoy first. Is it the *dark*
version of the target's hue (→ this conjunction fraction), a *neutral* non-object at the extreme of a
single axis (→ admit by hue, then rank), or a same-hue sibling differing in *saturation* rather than
value (→ the two-region split)? The `sat − val` scalar covers none of these.

#### Calibrate the descriptor to *this* target — none of these signatures is universal

A descriptor that worked on one task can invert on the next. Measured across the completed
object_swap tasks, on targets that are all "a small package on a table":

| Task | Discriminating signature | Result there |
|---|---|---|
| butter | warm fraction, red channel × **1.4** | target 0.392–0.418 vs decoy 0.033 — works |
| bbq sauce | `sat − val` of the median body colour | target 0.744–0.773 vs decoy 0.159 — works |
| alphabet soup | `mean(B) − mean(R)` (signed) | target +1.0 vs decoy −14.2 — works |
| cream cheese | blue fraction, blue channel × **1.2** | target 0.395–0.446 vs decoy 0.062 — works |
| cream cheese, **reusing bbq sauce's `sat − val`** | `sat − val` | target **−0.065** vs decoy **+0.35** — **ranks the decoy first** |
| ketchup, **reusing bbq sauce's `sat − val`** | `sat − val` | maroon **0.757** vs ketchup 0.267 — **ranks the decoy first** |
| ketchup, body saturation alone | body `sat` | ketchup 0.553–0.579 vs dressing 0.473–0.505 — margin **0.05**, unusable |
| milk | `mean(B) − mean(R)` (signed), **after** a `R − B > 20` hue admission | target −39.5…−40.0 vs juice −62.7…−63.0 — works, **≥ 22.7 grey levels** |
| milk, **bare `max(B − R)` with no admission** | `mean(B) − mean(R)` over *all* candidates | the **basket liner** wins (`R − B` = 10.2, x-width 0.289 m) — returns a non-object |
| orange juice | **bright-orange** pixel fraction (`R > 1.15 B` **and** `G > 1.05 B` **and** `R > 120`) | target 0.206–0.207 vs milk carton 0.006 / ketchup 0.001 — works, **34×** |
| orange juice, signed channel difference alone | `R − B` | target 62.1 vs ketchup 50.3 — only **12 grey levels**; the decoy is the *dark* version of the same hue, so the difference nearly closes |
| orange juice, **reusing milk's `B − R`** | `mean(B) − mean(R)` | **`B − R` ranks the milk carton first** |
| tomato sauce | `mean(R) − mean(B)` — the alphabet-soup key with the **sign inverted** | +13.9 on all 15 seeds, against the sibling's −14.2 for *this same can* — so the inversion cross-validates the asset. **Correct but NOT load-bearing here**: only one can-shaped candidate survived the geometry screen, so nothing needed ranking |
| salad dressing | **cap band** signed green difference, `median(G) − max(median(R), median(B))` over the top 25 % of the mask's image rows | target **+21.0** on all 15 seeds vs best sibling **≤ −1.0** — works, **≥ 22 grey levels**, no seed within 20 of flipping. A **third sign again** — the discriminating channel is *green*, not red or blue |

**`sat − val` has now failed on two of the three tasks that tried it.** It is not a general
same-class key — treat it as a single-instance curiosity from the bbq-sauce task. The rule that
survives is the *method*: **derive the channel, the multiplier and the sign from a measurement of the
target itself, then confirm the decoy sits far outside it.** The bbq-sauce key only works for a
strongly-*saturated* target; the cream-cheese package is a *desaturated* blue (median RGB
`[63, 68, 87]`) and the ketchup is the **less** saturated of two red bottles, so in both cases the sign
flips. Three practical consequences:

- **Calibrate the multiplier, don't copy it.** A 1.4× red-channel test that isolates a warm label will
  *reject a desaturated one*; the cream-cheese run needed **1.2×**. Measure the target's median first.
- **Report the margin, not the threshold.** The durable quantity is the target's *minimum* against the
  decoy's *maximum* (here 0.395 vs 0.074 — a 5.3× gap), not the `BLUE_MIN = 0.20` constant that happens
  to sit between them. That is also the number that tells you whether the next task can reuse it.
- **When no single scalar has margin, split the mask into regions.** See the two-region variant below —
  on the ketchup task every whole-mask scalar failed and only a body+cap split produced separation.
- **Ask whether the descriptor is load-bearing before shipping it as a fix.** A calibrated descriptor
  can be *correct and unnecessary*: on the tomato-sauce task `mean(R) − mean(B)` measured +13.9 on all
  15 seeds (the sibling's key with the sign inverted, correctly identifying the can that had been the
  *decoy* in the alphabet-soup scene) — yet only **one** can survived the geometry screen, so nothing
  needed ranking and the descriptor made no difference to the outcome. Say so, rather than presenting a
  colour fix that did not do the work; the honest version is what makes the cross-task sign table usable.

#### When no whole-mask scalar separates them, split the mask into regions by image row

**Trigger**: several objects of the target's class, no prompt ranks the target first, *and* the
whole-mask descriptors above either pick the wrong sibling or have no usable margin. Typically the
target is neither the most saturated nor the largest instance — it is distinguished by a *part* of
itself (a cap, a lid, a label band).

```python
def appearance(rgb, cand):
    """Body redness and cap achromaticity of one candidate's own mask."""
    mk = cand["mask"] > 0
    ys = np.where(mk.any(axis=1))[0]
    y0, y1 = int(ys.min()), int(ys.max())
    cut = y0 + int(0.30 * (y1 - y0)) + 1          # top 30% of rows = the cap
    cap = np.zeros_like(mk); cap[y0:cut, :] = mk[y0:cut, :]
    body = mk.copy();        body[y0:cut, :] = False
    bpx = rgb[body].astype(np.float64)
    cpx = rgb[cap].astype(np.float64)
    cand["body_red"] = float((bpx[:, 0] > 1.25 * np.maximum(bpx[:, 1], bpx[:, 2])).mean()) \
        if len(bpx) else 0.0
    cs = colour(cpx)
    cand["cap_sat"] = cs[1] if cs is not None else 9.0
    cand["cap_val"] = cs[2] if cs is not None else 0.0
    return cand

# select: BOTH halves are load-bearing
pick = [c for c in cands if c["body_red"] >= BODY_REDMIN and c["cap_sat"] <= CAP_SATMAX]
best = max(pick, key=lambda c: (c["cap_val"], -c["cap_sat"])) if pick \
    else max(cands, key=lambda c: c["score"])          # explicit fallback
```

The split is a **segment of the mask by image row** — no world-frame calibration — so it transfers
across camera poses. And the two halves must be **ANDed**: a sub-region test alone is not a screen.
`cap_sat <= 0.15` on its own also admitted a bottle-shaped fragment of the **wicker basket**
(`cap_sat 0.00–0.01, cap_val 0.66` — brighter than the ketchup's 0.36) on seeds 52 and 55; only the
complementary whole-object gate `body_red >= 0.35` rejected it.

**Why it works + evidence**: on `libero_object_swap/pick_up_the_ketchup_and_place_it_in_the_basket`
five phrasings all invert the ranking (`ketchup bottle` maroon 0.797 vs ketchup 0.738; `tomato ketchup`
0.361 vs 0.348; `red bottle` 0.492 vs 0.461; `ketchup` 0.586 vs 0.547; `sauce` tied at 0.750), so
`max(score)` would have grasped the maroon bottle on **15/15** seeds. Measured: body_red 0.65 /
cap_sat 0.00–0.01 for the ketchup, against 0.91–0.94 / 1.00 for the maroon bottle and 0.45–0.52 /
0.50–0.56 for the dressing bottle. `BODY_REDMIN = 0.35` has a 0.12 margin against the soup can and
`CAP_SATMAX = 0.15` has 0.49 against the dressing bottle. The selector picked the same object on all 15
development seeds and never fell back; a **negative probe** forcing the maroon bottle scored **0.000**
on seeds 51 and 60, so the rule is load-bearing. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_ketchup_and_place_it_in_the_basket/fix_code.py`
— `appearance`, `find_ketchup`; 2026-09-14.

##### Variant — when the cap *is* the colour, take the cap band's own signed channel difference

The ketchup variant above used the cap's **achromaticity** (a *saturation/valence* statistic). When the
discriminating part is a cap that is **chromatic in its own right** — a green cap among pale and grey
ones — the same region split carries a different statistic: a signed channel difference of the band's
median colour.

```python
def cap_signature(rgb, cand):
    """Signed green difference of the candidate's cap band (top 25% of its mask rows)."""
    mk = cand["mask"] > 0
    ys = np.where(mk.any(axis=1))[0]
    y0, y1 = int(ys.min()), int(ys.max())
    cut = y0 + int(0.25 * (y1 - y0)) + 1          # top band = the cap
    cap = np.zeros_like(mk)
    cap[y0:cut, :] = mk[y0:cut, :]
    cpx = rgb[cap].astype(np.float64)
    if len(cpx) < 30:                             # too few pixels to trust a median
        cand["cap_green"] = -999.0
        return cand
    med = np.median(cpx, axis=0)
    cand["cap_green"] = float(med[1] - max(med[0], med[2]))   # signed, self-normalising
    return cand

green = [c for c in cands if c["cap_green"] >= CAP_GREEN_MIN]   # 12.0 grey levels
best = max(green, key=lambda c: c["cap_green"]) if green \
    else max(cands, key=lambda c: c["score"])                   # explicit fallback
```

Two properties carry it, and both are why it transfers: the descriptor is a **difference of two
channel medians over the candidate's own pixels**, so the scene's absolute illumination cancels and
there is no tuned constant beyond the admission threshold; and the region is selected by **image row
inside the mask**, so it needs no world-frame calibration. Keep the same-class geometry screen (tall,
narrow) as the *outer* gate so a coloured non-bottle cannot win the rank.

**Why it works + evidence**: on `libero_object_swap/pick_up_the_salad_dressing_and_place_it_in_the_basket`
three tall bottles share the scene and no prompt ranks the target first — the target's best score is
**below** a sibling's on **15/15** seeds (0.906–0.949 vs 0.953–0.957). Measured: `cap_green` **+21.0**
for the dressing against **≤ −1.0** for the best sibling, a ≥ 22 grey-level margin with no seed within
20 of flipping. A **negative probe** forcing `max(score)` grasped the sibling at `(0.497, −0.237)` and
placed it *cleanly* in the basket (release tcp `[0.600, 0.259, 0.233]` against a rim of 0.142, program
printed `placed`, no error raised) and still scored **0.000** on seeds 51 and 52 — so the zero is the
goal predicate rejecting the wrong **object**. That is the shape of a genuinely identity-sensitive task,
and the reason the identity rank is load-bearing rather than cosmetic. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_salad_dressing_and_place_it_in_the_basket/fix_code.py`
— `cap_signature`, `find_dressing`; 2026-09-14.

**How to choose between the three region variants.** They are the same idea with different statistics,
and the choice follows from what the cap *is*: ketchup — the cap is **achromatic** and the body carries
the colour, so AND a body-colour gate with a cap-achromaticity test; salad dressing — the cap **is** the
colour and the bodies are near-identical, so rank on the cap band's own signed channel difference.
Split the mask first, measure both halves, and only then pick the statistic. In all three cases the
sub-region test alone is not a screen — pair it with a whole-object gate.

#### Prune candidate groups largest-mask-first with a ~4 cm exclusion radius

**Trigger**: any localization that unions several prompts. SAM3 also returns **partial** masks of the
same object — its cap, its shoulder — whose centroids sit 2–3 cm from the whole object's, while two
distinct objects are ≥ 5 cm apart.

```python
kept = []
for g in sorted(groups, key=lambda d: -int(d["mask"].sum())):     # largest mask first
    if all(float(np.linalg.norm(g["xy"] - k["xy"])) > 0.040 for k in kept):
        kept.append(g)
return kept
```

Sort **largest-first** so the whole object is always the one that survives, and use **~4 cm**, not the
2 cm centroid-merge that a first pass would suggest — on the ketchup scene a 2 cm radius yielded **10
"objects" for 3 real bottles**, because a bottle's cap and shoulder fragments each sit within 2 cm of
it. Pruning largest-first at 0.040 m leaves exactly 3, stable across all 15 development seeds.
Source: `outputs/libero_fix_loop/libero_object_swap/pick_up_the_ketchup_and_place_it_in_the_basket/fix_code.py`
— `bottle_candidates`; 2026-09-14.

#### Keep the geometry screen as the *outer* gate, never inside the colour rank

A colour word alone is not a screen — `blue box` also fires on an orange-juice carton that is genuinely
blue (fraction 0.30). Screen on geometry first, then rank what survives by colour; reversing the order
lets a tall blue object win:

```python
if not (BOX_MIN_SIDE <= dx <= BOX_MAX_SIDE and BOX_MIN_SIDE <= dy <= BOX_MAX_SIDE):
    continue
if dz > BOX_MAX_HEIGHT or zr[1] > BOX_MAX_TOP_Z:      # 0.060, 0.070 m
    continue
```

with `BOX_MIN_SIDE = 0.020, BOX_MAX_SIDE = 0.120`. On the cream-cheese task this took the `blue box`
candidate list from ~200 masks to 2–3, all flat slabs, and the colour rank then had only the true
target and the brown decoy to separate. Each half is insufficient on its own: the screen admits the
brown slab (within 5 mm of the target on every dimension), and the colour word admits the carton.

**Why it works + evidence**: the ranking key was load-bearing, not belt-and-braces. Re-running with the
descriptive prompt removed (`SLAB_PROMPTS = ["box", "carton"]`) on seeds 51 and 60 put the **brown
decoy first on raw score** (`box` 0.680 vs 0.633, and 0.652 vs 0.633); the blue fraction re-ranked the
cream cheese to the top and both seeds still scored 1.0. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_cream_cheese_and_place_it_in_the_basket/fix_code.py`
— `find_slab`; 2026-09-14.

#### Never `break` out of a prompt loop on the first hit when identity comes from a *rank over the pool*

A common idiom when several whole-class prompts are used to *find* candidates,
`for p in PROMPTS: masks = segment(p); ...; if cands: break`, is unsafe for the reason this whole
section is about: **the prompt is a recall device, and identity comes from the rank.** If one prompt
happens to miss the goal while still grounding its sibling, the sibling is the *only* candidate, the
rank dutifully returns it, and **nothing raises** — no exception, no empty list, reward 0 with a
perfect-looking execution. The failure is silent and it points at the wrong object.

```python
cands = []
for prompt in CAN_PROMPTS:                    # NO early break
    for m in segment_sam3_text_prompt(rgb, prompt) or []:
        ...                                   # screen each mask here, then append
merged = []                                   # collapse the same object found under several prompts
for c in sorted(cands, key=lambda k: -k["n"]):     # largest mask first
    if all(np.linalg.norm(c["center"][:2] - m["center"][:2]) > 0.025 for m in merged):
        merged.append(c)
```

Two ordering rules make the wider prompt set safe: **screen before merging**, so a larger but
geometrically invalid mask cannot displace a good one by out-ranking it on point count; and keep the
merge radius small *because* the screen has already run — here 2.5 cm suffices and admits 2.5 cm of
drift, whereas the wider ~4 cm radius recommended for the ketchup scene is unnecessary once cap and
shoulder fragments are already rejected by the height gate. Perception costs no sim steps, so the extra
prompts are free; the only cost of `break`-ing early is the silent failure above.

**Evidence**: on `libero_object_task/pick_up_the_salad_dressing_and_place_it_in_the_basket` the union
was verified a **no-op** — both prompts agree, so the union produced the same 2 groups on all 15
development seeds — and it ships as insurance rather than a repair, because a silent wrong-object pick
costs the whole held-out seed. Source: same `fix_code.py` — `find_can_candidates` lines 141–209
(prompt loop 158–196, merge 198–201); 2026-09-16.

---

### A merged mask is too *tall*, not too big — screen the cloud's *flatness*, not its size

The base-on-the-table gate above rejects masks of **parts** of taller objects. The mirror failure is a
mask that **swallowed a taller neighbour whole**, and no size screen catches it: the merged cloud has a
plausible width and sits at a plausible place, so it survives every extent band. What is wrong with it is
only its **height**.

Measured on `libero_goal_task/put_the_bowl_on_top_of_the_cabinet`, where the payload is a saucer lying
flush on the table and the scene also holds a 0.12 m metal bowl. The prompt `plate` returned a mask with
the bowl merged in: `rim_z` read **0.0199–0.1253** against the plate's true rim top of **0.0074**, and the
next close then aimed 5–8 mm *outside* the plate. On one development seed only **74 of 178** SAM3 masks
passed the screen below, so it is load-bearing rather than cosmetic.

```python
Z_MAX_FLAT = 0.022      # a flat plate / saucer / lid cloud never reaches this high
SPAN_FLAT  = 0.030      # ... and never spans more than this in z
z_hi = float(np.percentile(pts[:, 2], 99))
span = z_hi - float(np.percentile(pts[:, 2], 2))
if z_hi < Z_MAX_FLAT and span < SPAN_FLAT:      # keep
```

Two scalars and no shape model, with thresholds taken from the **object's own** ceiling and thickness
rather than a class prior: a saucer is ~7 mm thick and never higher than 2 cm, so anything tall is either
a different object or a merge.

**Why the continuity gate does not cover this.** `transport.md`'s "gate that measurement by *continuity*,
not by plausibility" catches a merged mask because it **jumps**. A mask that swallowed a standing
neighbour on the *first* observation has no previous sample to jump from, and it passes every static size
gate on the way in. Flatness is the one static property such a merge cannot fake.

**Executed source**: `libero_goal_task/put_the_bowl_on_top_of_the_cabinet` `fix_code.py`, `flat_cloud`,
lines 117–136. Store instance
`localize.reject-a-mask-that-swallowed-a-taller-neighbour-by-flatness`.

**Evidence caveat — read this before reusing it.** That task scores **0/15 on both `initial_code.py` and
`fix_code.py`**; the screen removes the merged masks, but the task's own blocker is geometric (the saucer
cannot be gripped at all — see `grasp.md`, "a planar pad face on a shallow ramp is a wedge, not a clamp"),
and no seed flipped to success. Treat this as evidence that the screen **filters correctly**, not as
evidence that it raises reward.

### The *reference* object has no usable prompt at all — find it geometrically, screened by table level

Some scenes do not present a hard disambiguation; they present a reference object that **cannot be
segmented by any prompt**. On
`libero_spatial_swap/pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate` the
instruction's reference is the **ramekin**, and `ramekin` scores **~0.001 scene-wide** — the colour and
packaging tricks above have nothing to rank. The scene also holds two same-class akita bowls plus a
bowl-sized stove crank that answers `black bowl` at 0.087.

The reference is then found by **shape, size and where it stands**, and the target by its relation to
that reference:

```python
RING_Z_TABLE = 0.02          # a reference standing on the table has its ring near z = 0
cands = bowl_candidates(rgb, d, K, E)              # shape + size + table-level gates
ram, tgt = pick_reference_and_target(cands, world_cloud(d, K, E))
# reference = the SMALLEST on-table bowl-like candidate (the ramekin, not a bowl)
# target    = the akita whose class score is high AND which is NEAREST that reference
```

Two screens do the work. The **table-level ring gate** (`RING_Z_TABLE`) is what rejects the stove
crank — it is bowl-sized and bowl-shaped but does not stand on the table. The **"smallest candidate"**
heuristic is what separates the reference from the target without a prompt: on every development seed
the ramekin is geometrically the smallest bowl-like object, and the relation (`nearest to the
reference`) then picks akita A at 0.133 m over akita B at 0.264 m.

This is the mirror of "The instruction names a *support* — select by its footprint": there the support
*is* segmentable and the object needs the relation; here the reference is *not* segmentable and has to
be identified structurally before the relation can be applied at all.

**Evidence**: the correct reference and target on every development seed; together with the in-air hang
measurement (`grasp.md`) the shipped revision scores 13/15. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_next_to_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— `bowl_candidates` line 131, `black_class_pool` 170, `pick_reference_and_target` 209–246,
`ring_height` 195; 2026-09-15.

---

## Prompt the Packaging Word (or a Colour+Shape Descriptor), Not the Product Word

**Trigger**: a product word (`butter`, `cheese`, `pudding`) returns hundreds of masks with a top score
below ~0.15 and no usable ranking — often ranking a distractor first or second. The object's *packaging*
is a much stronger visual token than the product itself, which is a homogeneous blob when seen from
above.

```python
BUTTER_PROMPTS = ["butter box", "butter", "box", "carton"]
```

Lead the prompt list with the packaging word and keep the product word as a later fallback — the first
prompt that yields any candidate wins, so the list order is the whole intervention. This is a *prompt
registry* fix, not a filter: it changes which candidates exist before any screening happens, and it
pairs with the colour-descriptor ranking above (which then re-orders those candidates).

**Why it works + evidence**: on `libero_object_swap/pick_up_the_butter_and_place_it_in_the_basket` seed 51
the same object scores `butter` 0.067, `butter stick` 0.108, `stick of butter` 0.050, `farm fresh butter`
0.011, **`butter box` 0.354** — a 3–5× jump for the packaging word. Note that a *higher* score is not by
itself sufficient: `butter box` still ranks the chocolate-pudding box at 0.340, which is why the colour
descriptor above is needed on top of it. The generalizable move is the *prompt-shape* rule; the specific
strings belong in the registry. Source: same `fix_code.py` — `BUTTER_PROMPTS`; 2026-09-14.

**Caveat — a high score proves the prompt *grounded*, not that it *identifies*.** These are different
properties and the second is the one you need. The sharpest evidence is the same prompt on two tasks:
`juice box` scores **0.922** on the orange-juice carton (a clean, well-grounded prompt, far above the
0.354 that `butter box` manages on butter) — but on the *milk* task the same string scores
**0.922 / 0.922**, tied exactly on the target and its sibling carton. A grounding prompt can therefore
be a coin flip between two siblings, and the better it grounds the *class*, the more surely it will tie
across instances of that class. Use the packaging word to make candidates *appear*; use a measured
colour descriptor to decide *which* candidate. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_orange_juice_and_place_it_in_the_basket/fix_code.py`
and `.../pick_up_the_milk_and_place_it_in_the_basket/fix_code.py`; 2026-09-14.

**Variant — when the product word returns *nothing* usable, describe the packaging's colour and shape.**
This is the stronger form of the same rule, and it bites hardest on objects whose product name is a
*colour* the object also is. The packaging word may not exist as a token at all, so the fix is to name
what the camera sees:

```python
PUD_PROMPTS = ["<colour> <shape>", "<product name>", "<short name>", "box"]   # here: "brown box" first
MAX_CAND = 3        # evaluate only the top 3 masks per prompt - SAM3 returns ~200
```

On `libero_object_swap/pick_up_the_chocolate_pudding_and_place_it_in_the_basket` the product name is
near-useless — `chocolate pudding` **0.002**, `pudding` 0.006 — while `brown box` scores **0.578** on
exactly the pudding mask on all 15 development seeds. Two cautions that generalize: a bare `box`
prompt scores a healthy 0.426 but fires on *several* objects at once (here the pudding **and** the
orange-juice carton), so a colour+shape descriptor is only usable **together with** the geometric
screen (small, flat, resting on the table) applied to the top few candidates — and capping the
candidate count at 3 is what keeps the search cheap. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_chocolate_pudding_and_place_it_in_the_basket/fix_code.py`
— `find_pudding`; 2026-09-14.

**Corroboration from a `_task` suite — the geometry screen, not the prompt, is what removes the taller
sibling.** On `libero_object_task/pick_up_the_alphabet_soup_and_place_it_in_the_basket` the runtime
instruction said *"Pick the cream cheese and place it in the basket"* while the file name said alphabet
soup, so the goal object was a flat light-blue slab — and the product word did not ground at all:
`cream cheese` **0.040**, `cream cheese box` **0.006**. Two specific readings sharpen the rule:

- **`num_masks` is not the signal — the score is.** Both dead prompts still returned ~200 masks, so any
  screen that keys on mask *count* reads this scene as healthy.
- **A generic shape word grounds a *taller* sibling first.** `box` scored **0.781** on the 13 cm milk
  carton before the target at 0.711, i.e. the highest-scoring candidate was the wrong kind of object
  entirely. The fix is the ordering rule plus the geometric screen from the Variant above, applied to the
  top 3 masks per prompt: reject anything with `top > 0.07`, `top − base > 0.06`, or
  `max(extent) > 0.16`. That single screen drops the milk carton and is what makes a generic `box` prompt
  safe to keep as a late fallback.
- **The colour decision is cheaper as a *channel rank* than as a prompt.** Rather than adding a
  `blue box` prompt, score each surviving mask directly — mean blue minus the larger of mean red and mean
  green — which read **+16** for the target and **−50** for the look-alike butter box on the same seed.
  Packaging-word-first order still led (target 0.719 vs 0.247 for the sibling flat box), so the two
  mechanisms compose: registry order to make candidates appear, geometry screen to cut the wrong *kind*,
  channel rank to choose *which instance*.

Prompts were unchanged across all 15 development seeds (the target always won at prompt index 0). Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_alphabet_soup_and_place_it_in_the_basket/fix_code.py`
— `screen_candidates` lines 85–116, `pick_candidate` 118–124; 2026-09-16. On the runtime-language half of
this, see "In a `_task` suite the relation comes from the RUNTIME LANGUAGE — the task name lies" above:
here it is not the *relation* but the *object identity* that the file name gets wrong.

#### …and the *task identifier's* noun is a fallback you must never take — it is the one word guaranteed wrong

The two paragraphs above say the instruction's product word may not ground. This is the trap that
follows: the **identifier** names a different object, that object is *real and present in the scene*,
and it therefore segments beautifully. Reaching for it when the instruction's noun scores low feels like
recovery and is the single worst fallback available. On
`libero_goal_task/open_the_top_drawer_and_put_the_bowl_inside` the runtime instruction names **cream
cheese** while the identifier says *bowl*: `cream cheese` scored **~0.02** on seed 51, while a bowl in
the same scene grounds strongly and is not the goal. Keep a prompt ladder and pick the first prompt whose
mask is *physically plausible for the goal object*, with the identifier's noun **absent from the list
entirely**:

```python
for p in ("blue box", "cheese box", "cream cheese", "box"):
    mask = segment_sam3_text_prompt(rgb, p)[0]["mask"]
    ...
# never append the identifier's noun to this list, in any position
```

Every passing run logs `box: prompt='blue box' score=0.809`; grounding the bowl instead costs the whole
episode (the wrong object is carried, and the run fails at the placement check rather than at the grasp).
The rule generalizes past this task because of *how* the suites are built: in a `_task` suite the
identifier is a dispatch key, so its noun is the one token with no claim on the scene at all. When the
instruction and the identifier disagree, the instruction is the task and the identifier is a label.
Source: `outputs/libero_fix_loop/libero_goal_task/open_the_top_drawer_and_put_the_bowl_inside/fix_code.py`
— `find_box()`; 2026-09-17.

### Refinement — write the three parts as one per-object registry, and make the descriptor an *admit floor* that degrades

The three mechanisms above are easier to keep straight as a single data structure keyed by the noun the
runtime instruction names, with the descriptor applied as a **floor** rather than as a ranking key:

```python
TARGET_SPEC = {
    "butter": dict(prompts=["butter box", "butter", "box", "carton"],
                   descriptor=warm_fraction, admit=WARM_MIN),
    "cream cheese": dict(prompts=["cream cheese box", "cream cheese", "box", "carton"],
                         descriptor=cool_difference, admit=None),
}
# in the localizer, after the geometric screen:
kept = [k for k in cands if admit_min is None or k["desc"] >= admit_min]
pool = kept if kept else cands        # an unusable descriptor degrades to the score rank
pool.sort(key=lambda k: (-k["desc"], -k["score"]))
```

`admit` is a **floor, never a requirement**: when the descriptor rejects everything, falling back to
the plain score ranking is better than ranking an empty list — the same "degrade, never crash" rule as
the white-content variant above.

**The reason a floor is needed at all is that the prompt score is not merely noisy here — its margin
changes sign between seeds.** On `pick_up_the_milk_and_place_it_in_the_basket` (runtime language "Pick
the *butter*…") the packaging prompt `butter box` ranks the target against the light-blue cream-cheese
slab as **0.174 vs 0.157** on seed 51, **0.195 vs 0.169** on seed 55, and **0.117 vs 0.102** on seed
60 — the decoy leads every time, by a *different* margin. A score threshold tuned on one seed is
therefore meaningless, and `max(masks, key=score)` picks the decoy on all 15 seeds. The warm-pixel
fraction separates the same pair by an order of magnitude on every seed (butter 0.378–0.405 vs cream
cheese 0.000 vs dark box 0.020), so a floor at `WARM_MIN = 0.15` was never approached by a decoy and
never missed by the target (worst margin 0.228). **Rule: when a decoy's score margin flips sign across
seeds, stop tuning the threshold and switch to a descriptor with a gap.** Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_milk_and_place_it_in_the_basket/fix_code.py`
— `warm_fraction` / `cool_difference` / `TARGET_SPEC` lines 52–90, consumed by `find_box` 152–200 and
`instruction_target` 141–151; 15/15 development seeds; 2026-09-16.

**Variant of the registry value: when the runtime noun selects between two *same-geometry* siblings, the
value is an axis *direction*, not a prompt list.** The registry above keys a noun to prompts plus a
descriptor, which works when the noun's object is identifiable by appearance. On a scene where the
sibling pair is geometrically identical and the nouns name two different *labels* on the same package,
the only thing the noun can decide is which end of a colour axis to rank toward:

```python
def target_signature(language):
    """Colour axis of the label identifying the can the instruction names.

    Alphabet soup is the blue-labelled can, tomato sauce the red-labelled one;
    the two share geometry exactly, so the label colour is the only separator.
    """
    return "red" if "tomato" in language.lower() else "blue"
```

Keep it a *function of the runtime string*, never a constant baked per task: on this suite the
identifier's noun is wrong (see the remap tables above), so a constant would be wrong on the same task
it was written for. The signature is then consumed by the rank (`max(c["red"])` vs `max(c["blue"])`), and
the two directions must be checked against the *whole* surviving set — on this scene `max(red)` is only
safe because the geometry screen keeps the warmer bbq-sauce bottle and milk carton out (see "The hazard
can also be a *warmer* non-target" above). Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_salad_dressing_and_place_it_in_the_basket/fix_code.py`
— `target_signature` lines 212–223 (called from `main` line 334), `pick_target_can` lines 225–241; the
runtime instruction reads "Pick the **tomato sauce**…" on 15/15 development seeds while the identifier
says *salad dressing*; 2026-09-16.

---

## Base-Object Anchored Localization

When object A sits **on top of** object B, and SAM3 for A is unreliable, find B first via SAM3
then depth-search above B's image region.

```python
def localize_above_object(rgb, depth, K, E, base_prompts, min_z=0.04, max_z=0.20):
    """Find object sitting on top of base_object by depth-searching above base image mask."""
    depth_img = depth[:, :, 0] if len(depth.shape) == 3 else depth
    for prompt in base_prompts:
        masks = segment_sam3_text_prompt(rgb, prompt)
        if not masks: continue
        best = max(masks, key=lambda d: d["score"])
        base_mask = best["mask"]
        ys, xs = np.where(base_mask)
        if len(ys) == 0: continue
        extended_mask = base_mask.copy()
        for dy in range(1, 31):
            shifted = np.zeros_like(base_mask, dtype=bool)
            shifted[max(0, ys.min()-dy):max(0, ys.max()-dy+1), xs.min():xs.max()+1] = True
            extended_mask = extended_mask | shifted
        pts = mask_to_world_points(extended_mask.astype(np.uint8), depth_img, K, E)
        if pts is None: continue
        elevated = pts[(pts[:,2] > min_z) & (pts[:,2] < max_z)]
        if len(elevated) < 10: continue
        center = elevated.mean(axis=0)
        return center, elevated
    return None, None
```

**Why:** Finding a unique base object first gives a stable anchor when the target object has
unreliable SAM3 segmentation due to similar objects nearby.

---

## Flat-Surface Localization by Densest Upper Z-Plateau

**Trigger**: finding the top face of a boxy support (cabinet, stove, rack) whose SAM3 mask is noisy
and mixes the top face with sloped sides, so `pts[:, 2].max()` lands on a sparse edge/reflection
outlier instead of the real surface.

```python
zs = pts[:, 2]
hist, edges = np.histogram(zs, bins=50)
lo = len(hist) // 3
idx = int(np.argmax(hist[lo:])) + lo        # densest bin in the upper third
z_bin = 0.5 * (edges[idx] + edges[idx + 1])
sel = np.abs(zs - z_bin) < 0.02
if sel.sum() < 20:
    sel = zs >= np.percentile(zs, 90)
top = pts[sel]
z_top = float(np.median(top[:, 2]))
tx = 0.5 * (np.percentile(top[:, 0], 5) + np.percentile(top[:, 0], 95))
ty = 0.5 * (np.percentile(top[:, 1], 5) + np.percentile(top[:, 1], 95))
```

**Why it works + evidence**: on `libero_goal_swap/put_the_bowl_on_top_of_the_cabinet` the cabinet
mask's raw `z_max` is 0.299 with only 24 points above 0.256, while the true top face is a 6275-point
plateau at z≈0.215; `z_max - 0.05` bands pick up almost nothing. The density histogram recovers
5900–8000 in-band points on every development seed and gives a stable `z_top = 0.215–0.216` across
all 15. Feed this `z_top` to the transit-height rule in [transport.md](transport.md). Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_bowl_on_top_of_the_cabinet/fix_code.py` lines
106–123; 2026-09-14.

---

## Never Re-Localize an Object While It Is in the Gripper

**Trigger**: a SAM3 text prompt whose object word is *also true of the robot's own hardware* —
`"metal bowl"`, `"silver …"`, `"steel …"` — applied while that object is held in the gripper.

```python
# WRONG while carrying: the mask also picks up the gripper's metal fingers
#   held = localize(rgb, d, K, E, ["metal bowl"], ref_xy=tcp_xy(), radius=0.12)
#   off  = centroid(held) - tcp_xy()          # under-reads the true offset
# RIGHT: take the measurement from the observation made BEFORE the pinch
#   off = np.clip(np.array([bx - tcp[0], by - tcp[1]]), -0.08, 0.08)
# keep the carried measurement as a diagnostic print only - never gate control on it
```

**Why it works + evidence**: on `libero_goal_swap/put_the_bowl_on_the_stove` the held bowl's
`"metal bowl"` mask has n = 3550 points against 2683 for the same bowl free on the table, and the
extra points are the fingers: the measured centroid offset came out `(-0.016,+0.018)` where the
true offset was `(-0.049,+0.000)` — a 3.3 cm error dragged toward the wrist. Compensating with that
wrong offset moved the whole descent column to x = 0.572 instead of 0.556, straight into a leaning
plank stack, and the bowl was released in mid-air (seeds 59/61, reward 0). Measuring before the
pinch fixes both. Generalizes to any "material word that is also a material the robot is made of"
prompt — verify the mask's point count against a pre-grasp measurement before trusting it. Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_bowl_on_the_stove/fix_code.py` — `bowl_points`
plus the offset block in `attempt()`; 2026-09-14.

**Refinement — the true offset is the measured outer radius.** Confirmed a third time on a third
suite task (`libero_goal_swap/put_the_bowl_on_the_plate`), and the number is stable enough to use as
a sanity check rather than just a warning: for a `metal bowl` radial wall pinch the true
bowl-centre-to-TCP offset is **exactly the measured outer radius** (±0.049 m here, reproduced on
15/15 seeds), whereas the carried-mask centroid under-reads it (seed 51 gave `(+0.033,−0.003)`
against a true `(+0.049,+0.000)` — 1.6 cm toward the wrist). So when a wall pinch is the grasp, you
can *predict* the release compensation from the object's radius and use the pre-pinch measurement
only to confirm the sign and the axis. Source:
`outputs/libero_fix_loop/libero_goal_swap/put_the_bowl_on_the_plate/fix_code.py` — `attempt`;
2026-09-14.

**Generalization — this is not about material words; *no* prompt survives the gripper.** The two cases
above involve prompts whose words are also true of the hardware, which makes the contamination
intuitive. But the effect appears with an ordinary colour+shape prompt too, and it is severe: on
`libero_object_swap/pick_up_the_chocolate_pudding_and_place_it_in_the_basket` the held box's `brown
box` top score collapses from **0.578 to 0.134** because the fingers join the mask, and the post-lift
re-localization returned `held=False` on **15/15** development seeds. Gating a grasp on it would have
aborted every episode. It is also expensive: that check burned **52 of the program's 160 API calls**
(trace steps 60–111), and the task's episode horizon is ~160 calls, so the retry path would have died
with `ValueError: executing action in terminated episode`. Removing it, and reading the **measured
gripper gap** instead (0.0459–0.0461 m holding vs ~0.001–0.005 m empty; see [grasp.md](grasp.md)),
took the program from 160 to 62 calls with 15/15 still at reward 1.000. **Rule: never ask SAM3 about an
object that is inside the gripper — verify with the gap, and if a carried pose is genuinely needed,
take it from the pre-pinch observation.** Source: same `fix_code.py` — `attempt`; 2026-09-14.

**When a held-object pose *is* needed, gate it on physical sanity — not on score.** Centring the
carried object over a target genuinely needs a live measurement, and the segmenter may answer with a
**phantom mask at the object's previous resting place** — plausible shape, mediocre but not obviously
wrong score. On
`libero_spatial_swap/pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_cabinet_and_place_it_on_the_plate`
the phantom measured `score = 0.85–0.86` for a mask **4 cm off in z** from where the bowl was actually
being held, so no score threshold separates it.

Test the mask against the **grip geometry** instead:

```python
def is_trustworthy(cd, expect_z=None):
    # cd has keys "z_lo", "z_hi", "score" from the screened candidate.
    if not (0.004 <= cd["z_lo"] <= 0.42
            and 0.025 <= (cd["z_hi"] - cd["z_lo"]) <= 0.090):
        return False
    if expect_z is not None:
        # The object is in the fingers: its underside must be where the grip
        # geometry puts it (tcp_z - bottom_gap).
        return abs(cd["z_lo"] - expect_z) <= 0.035
    return cd["score"] >= 0.30
```

Called as `bowl_near(place_xy, max_d=0.20, trusted=True,
expect_z=float(tcp()[2]) - grip["bottom_gap"])`.

**The asymmetry is the load-bearing part: apply the depth check *only* while the object is held, and
leave the score-only path as the default for free-space measurements.** A legitimate in-drawer or
pre-grasp measurement can fall outside the expected-depth band — the band is derived from the grip, so
free space has no such expectation. Applying the gate to the free-space measurement *regressed* seed 52
(offset `[0.039,0.006] → [-0.008,0.024]`, carry to x = 0.728 wedged the descent). Applied where it
belongs, it rejected the phantom masks on seeds 51 and 56 (`c=(0.680,-0.028) z_lo=0.009 score=0.86
REJECT`, `c=(0.679,-0.028) z_lo=0.005 score=0.08 REJECT`), converting two silent 4 cm throws into
honest misses while leaving the 12 passing seeds unchanged. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_in_the_top_drawer_of_the_wooden_cabinet_and_place_it_on_the_plate/fix_code.py`
— `is_trustworthy` lines 109–128, called from `bowl_near` line 137 and the centring loop lines
291–292; 2026-09-15.

**Generalization — the *carried object* corrupts the container's mask too, so measure the container
first.** The rule above is stated for the held object. It applies just as hard to the **placement
target**, because the arm and the object it is carrying occlude whatever you are about to put it into.
Measure the container **once, at the start, with the arm at home**, and pass that xy into the release:

```python
basket_xy, _ = find_basket()      # arm at home, view clear   -> (0.664, 0.265)
can = pick_target(find_cans())
grasp(can, quat)                  # only now does the arm occlude the basket
place(basket_xy, quat)            # reuse the pre-grasp xy; never re-segment inside
```

The magnitude is not marginal: on
`libero_object_swap/pick_up_the_alphabet_soup_and_place_it_in_the_basket` re-running
`segment_sam3_text_prompt(rgb, "basket")` while carrying moved the basket mask centroid from
`(0.664, 0.265)` to `(0.751, 0.258)` — an **8.7 cm** error in x, most of the container's half-width and
larger than the goal predicate's ±9 cm site-local y tolerance. The seed-51 release column missed the
basket entirely and scored 0.000; reusing the pre-grasp measurement put all 15 seeds within 2.2 cm and
scored 1.000. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_alphabet_soup_and_place_it_in_the_basket/fix_code.py`
— `find_basket_clear`, `run`, `place`; 2026-09-14.

**Generalization — re-localize everything *movable* at the top of every attempt.** The
"measure the container once" rule above is about a **static** target and does not extend to objects
the robot itself can displace. Inside a retry loop, a partially successful attempt moves the object,
so candidates captured before that attempt aim at where the object *used to be*:

```python
for n in range(MAX_ITERS):
    # Re-observe and re-localize on EVERY attempt: after a failed release the object has
    # moved (or tipped), and frozen candidates would send the next pinch to its OLD pose.
    rgb, d, K, E = observe()
    cs = bowl_candidates(rgb, d, K, E)
    ...
    goal, _ = pick_goal_bowl(bowls, plate, ramekin)   # fresh each iteration
```

The two rules reconcile cleanly: the **container** is measured once (it does not move, and measuring
it early also avoids the occlusion problem above), while every **movable** object — the target, its
look-alikes, any reference object the relation uses — is re-measured each iteration. That keeps a
spatial relation like "between the plate and the ramekin" stable while letting the target's own pose
track reality.

**Why it works + evidence**: on
`libero_spatial_swap/pick_up_the_black_bowl_between_the_plate_and_the_ramekin_and_place_it_on_the_plate`
the initial program measured the bowls once and then re-ran its goal-bowl choice against those frozen
objects. Seed 57 printed a **byte-identical** bowl position `(0.580, 0.217)` on all five attempts
even though the bowl had been carried to `(0.688, 0.037)` — so attempts 1–4 all pinched empty space
and the run burned 4 of its 5 attempts. Those `air grasp` results were an artefact of the stale
candidates, **not** evidence about those pinches. After the fix, seed 58 shows the recovery the
refresh enables: attempt 0 released at `miss=0.0003` but the bowl scattered, and attempt 1
re-localized it at `(0.611, 0.138)` and placed it at 0.011 m. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_between_the_plate_and_the_ramekin_and_place_it_on_the_plate/fix_code.py`
— `run`; 2026-09-15.

**The diagnostic signature of a stale-pose retry: an *identical* air gap on every attempt.** This is
worth recognising on sight, because it is easy to misread as "the grasp parameters are wrong" and tune
blindly. Confirmed independently on
`libero_spatial_swap/pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate`: **every** v1
fallback pinch logged `air (gap=0.0012)` no matter how it was parameterised, while a real hold on that
bowl reads `gap = 0.0074–0.0083`. A gap pinned to the closed-on-air value (≈0.001) across attempts that
*differ in their parameters* cannot be telling you about the parameters — the fingers are not arriving
where the object is. Re-localise and match by proximity to the remembered pose before each attempt;
after the fix every retry held. The diagnostic generalises: **when a tuning change produces no change
in the measured signal, the input to that signal is stale.** Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate/fix_code.py`
— `pick_target`, `near_bowl`, and the retry loop in `run`; 2026-09-15.

**The carried mask has a shape asymmetry: its *base* is not a measurement, its *xy* is.** The failure
above is about the mask containing the *wrong extra* points (the fingers). This one is the opposite —
the mask is a **truncated subset** of the object, typically only its visible top face or lid, so
`z_lo` is a property of what the segmenter could see rather than of the object.

```python
# WRONG: the hang taken from the carried mask
#   hang = mask_z_lo - tcp_z            # one frame's top face, mistaken for the base
# RIGHT: both terms in the COMMANDED frame, both taken BEFORE the lift
#   hang = pinch_z_cmd - target_zlo     # target_zlo from the pre-pinch object cloud
# ...and use the carried mask for its xy ONLY, identity-gated and clamped
off = np.clip(np.array([obj[0] - cur[0], obj[1] - cur[1]]), -0.05, 0.05)
```

**Evidence**: on `libero_object_task/pick_up_the_butter_and_place_it_in_the_basket` seed 51 the carried
carton's mask reported `z_lo = 0.205` against a true base of 0.131 (independent colour+depth
localisation) — **0.074 m too high** — while on seeds 54/55 the same prompt on the same object returned
the full carton and agreed with the pre-lift estimate to 4 mm. Same prompt, same object, different
seeds: this is a per-frame failure mode, not a constant to calibrate. Taking the hang from that mask
drove the payload into the table. The *lateral* term survives the truncation because a top face shares
the body's xy: seed 51's truncated mask gave `(0.499, 0.057)` against an independent colour+depth centre
of `(0.500, 0.063)` — **6 mm** — and it is the mask's xy that the placement loop above uses.

This is the same defect the `is_trustworthy` depth gate catches, approached from the other end: that
gate *rejects* a carried mask whose `z_lo` is 7.4 cm from the grip-derived expectation, whereas here the
program never asks for the base at all and therefore has nothing to reject. Prefer not to ask. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_butter_and_place_it_in_the_basket/fix_code.py`
— the hang estimate and offset gate at lines 358–392, `find_carried`'s docstring at lines 232–238;
2026-09-16.

---

## Track a Moved Object by Position Continuity, Not by Class Prompt

**Trigger**: re-localizing an object *after* you have moved it. Once it comes to rest beside the
goal object its mask merges with the goal's and it drops out of the class prompt's top-k — so a
candidate-list lookup hands back an untouched look-alike twin, and a search window anchored at the
object's **original** position finds nothing at all. Both failure modes are silent: one returns a
confident wrong pose, the other reports the object missing from a scene it is plainly visible in.

```python
def find_tracked_bowl(rgb, d, K, E, anchor_xy):
    """Re-find the object being worked on by *position continuity*: widen a window around the
    last-seen anchor.  The class-prompt candidate list is deliberately NOT used here -- once the
    object sits next to the goal its mask merges with the goal and drops out, so the list would
    hand back an untouched twin instead."""
    anchor_xy = np.asarray(anchor_xy, dtype=float).reshape(-1)[:2]
    for radius in (0.10, 0.20, 0.35):                # widen only as far as needed
        pts = bowl_points_near(rgb, d, K, E, anchor_xy, radius=radius)
        if pts is None or len(pts) < 40:
            continue
        bx, by, b_lo, b_hi, pts = bowl_geometry(pts)
        if math.hypot(bx - anchor_xy[0], by - anchor_xy[1]) > radius:
            continue                                 # a hit outside the window is a different object
        return {"c": np.array([bx, by, 0.5 * (b_lo + b_hi)]), "pts": pts}
    return None
```

The second half of the pattern is the anchor update: after every release, set the anchor to where
the object **actually landed**, not to where it was released. That measured landing can also be fed
back as a closed-loop correction — take the residual out of the next release:

```python
lpts = bowl_points_near(rgb3, d3, K3, E3, release_xy, radius=0.20)   # measure, in a window around
if lpts is not None and len(lpts) >= 40:                              # the release point -- never
    lx, ly, _, _, _ = bowl_geometry(lpts)                             # via the class-prompt list
    if np.hypot(lx - release_xy[0], ly - release_xy[1]) < 0.20:
        landed = np.array([lx, ly])
if landed is not None:
    shift = shift - (np.asarray(landed) - np.asarray(place)[:2])
    anchor = np.asarray(landed)                  # move the tracking anchor forward
```

**Why it works + evidence**: on
`libero_spatial_swap/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate` the carried
bowl is set down 0.28 m from where it started; a fixed window around the original spot printed
`BOWL LOST` on **every** post-move localization and the run aborted, and a class-prompt re-lookup
returned the untouched twin at `(0.493, 0.307)`, producing a bogus landing error of `(-0.229,
+0.288)` whose correction derailed the rest of the episode. With position continuity the anchor
follows the bowl and all 15 development seeds scored 1.0 (the closed-loop term was never needed to
rescue a run on those seeds, but it keeps the release honest). Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate/fix_code.py`
— `find_tracked_bowl`, `bowl_points_near`, `main`; 2026-09-15. Companion rule while the object is
*still held*: "Never Re-Localize an Object While It Is in the Gripper" above.

### Verify a *lift* by the target's identity — re-running the class prompt silently returns the sibling

**Trigger**: verifying a grasp after the lift, on a scene holding a same-class sibling. The class prompt is
re-run to ask "where is my object now?" — but the target has been carried away, so the **only** surviving
candidate is the sibling, and the check reads the sibling's geometry as if it were the target's. The
result is a check that reports "unchanged" on every seed while being structurally incapable of reporting
anything else.

```python
def same_object(c, ref, sig):
    """Same physical object: matching colour signature and close to the remembered position."""
    return (abs(float(c[sig]) - float(ref[sig])) < 6.0
            and float(np.linalg.norm(c["center"][:2] - ref["center"][:2])) < 0.08)
```

Two properties make this work where the class prompt cannot: it is **anchored to the identity measured
before the carry** (the descriptor) *and* to the position it was measured at, so a sibling that matches
neither is correctly matched by nothing — rather than being mistaken for the target.

**Why it works + evidence**: on `libero_object_task/pick_up_the_cream_cheese_and_place_it_in_the_basket`
the initial program re-ran the whole-class `can` prompt after the lift and took `max(blue)` over the
result; with the target carried, the sibling's `blue` read −17.4 against the target's +0.5, so the check
always concluded "unchanged". After the identity gate every seed logs honestly —
`post-release: target still on table = False`. Note this is the *verification* companion to the
*localization* rule in "Track a Moved Object by Position Continuity" above: both refuse the class-prompt
candidate list after your own action has moved things, one for finding and one for checking. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_cream_cheese_and_place_it_in_the_basket/fix_code.py`
— `same_object` lines 201–207, `target_left_table` lines 254–260; 2026-09-16.

### The relation is invalidated by your OWN action — lock identity to the last measured position

The two subsections under "Disambiguation" above use the language relation to *select* among
look-alikes. That is correct for the **first** pick and wrong for every pick after it. When the task
names one of several identical objects by a spatial relation — "the bowl next to the cookie box" — a
failed attempt *carries the target away*, and the relation then points at a **different object**: the
look-alike it left behind is now the nearest one.

The symptom is distinctive and easy to misread as a placement bug: **the retry grasps the look-alike,
places it perfectly, and still scores 0.** Seed 55's log after attempt 0 reads
`container[0] xy=(0.698,0.196) dist_to_box=0.171` — the look-alike, while the real target sat on the
plate at `(0.470,-0.144) dist_to_box=0.329`. Seed 51 did exactly this: attempt 1 grasped the other
bowl, placed it well, reward 0.

Resolve identity by **proximity to the last measured position**, and demote the relation to a seed and
a fallback:

```python
def select_target(rgb, d, K, E, anchor=None):
    cands = find_candidates(rgb, d, K, E)
    if not cands:
        return None, None
    if anchor is not None:                      # identity lock wins over the relation
        cands.sort(key=lambda c: math.hypot(c[1][0] - anchor[0], c[1][1] - anchor[1]))
        d0 = math.hypot(cands[0][1][0] - anchor[0], cands[0][1][1] - anchor[1])
        if d0 < 0.30:                           # ~3x the inter-instance spacing
            return cands[0], None
        # else: anchor lost -> fall back to the language relation
    anchor_obj = find_anchor_object(rgb, d, K, E)   # the box, the plate, ...
    cands.sort(key=lambda c: math.hypot(c[1][0] - anchor_obj[0], c[1][1] - anchor_obj[1]))
    return cands[0], anchor_obj
```

The lock is only as good as its update, and the update belongs to the **attempt function**: it must
*return* the measured landing position (or the old position if the object never moved) so the caller
threads it into the next call. A one-shot anchor set before the loop does not survive the first carry.

Pick the tolerance from the scene's inter-instance spacing — `0.30 m` here is roughly 3× the gap
between the two bowls, which is slack enough to absorb a landing error yet far too tight to jump to a
twin. **Evidence**: with the lock all 15 development seeds succeeded, each on its **first** attempt.
Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_next_to_the_cookie_box_and_place_it_on_the_plate/fix_code.py`
— `select_target` lines 595–625, anchor seeded at 657 and returned by `attempt`; 2026-09-15.

**Guard the lock with the class pool — a raw proximity lock can capture a DIFFERENT object.** The
snippet above sorts the *whole* candidate list by anchor distance, which is only safe while the target
is still the nearest thing to the anchor. Once the target has been carried away, the nearest candidate
is whatever it was resting on. On
`libero_spatial_task/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate` seed 51 the
lock matched the **ramekin** at `(0.466, 0.201)` — `0.112 m` from the anchor, well inside the `0.30 m`
tolerance — and the loop picked it up. Re-derive the class pool first and use the anchor only to break
ties *inside* it:

```python
ramekin, derived = pick_ramekin_and_target(cands, akitas)   # class first, then the relation
near = [c for c in akitas if float(np.linalg.norm(c["c"] - anchor)) < 0.35]
if near:
    return ramekin, min(near, key=lambda c: float(np.linalg.norm(c["c"] - anchor)))
return ramekin, derived        # no pool member within tolerance -> anchor is stale, re-derive
```

**Why**: the lock's job is to keep you on the *same instance*, never to promote a different class into
the role of target. A different-class object is not a near-miss of the identity lock; it is a wrong
object. **Evidence**: with the pool-confined lock the wrong-object carry is removed and the shipped
revision scores **15/15** on dev seeds 51–65. Source:
`outputs/libero_fix_loop/libero_spatial_task/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate/fix_code.py`
— `choose_target` lines 295–306; 2026-09-16.

#### Calibrate the continuity tolerance against your OWN commanded motion, not the scene

The two tolerances above (0.30 m for the anchor lock, 0.030 m for the held-object jump gate) are both
*scene* constants — 3× the inter-instance spacing, and the perception noise floor. A third site
supplies a third basis, and it generalises further because it needs no scene knowledge at all:

> **Object motion is bounded by the motion you commanded plus a slip margin.** An apparent
> displacement larger than that is not a fast object, it is a different object.

```python
cands = [c for c in screened if c is not None]      # candidates that passed the GEOMETRY screen
if cands and last_c is not None:
    cands.sort(key=lambda c: float(np.linalg.norm(np.asarray(c["c"])[:2] - last_c)))
    best = cands[0]
    if float(np.linalg.norm(np.asarray(best["c"])[:2] - last_c)) > commanded_travel + 0.05:
        print("  localiser jumped %.4f on a %.4f push -> rejected"
              % (float(np.linalg.norm(np.asarray(best["c"])[:2] - last_c)), commanded_travel))
        best = None                                  # do not drive the paddle at it
```

**Evidence**: on `libero_goal_task/push_the_plate_to_the_front_of_the_stove` (identifier says *plate*,
runtime language "Push the cream cheese to the front of the stove") dev seed 60's localiser returned
the **plate** at `(0.7010, −0.0338)` after a 0.110 m sweep — an apparent **0.1931 m** move, which is
simply impossible and is the whole tell. The run recovered and still scored 1.0, but the plan had been
driving the paddle at the wrong object for several moves and burned **25 moves instead of 9**. With
candidates filtered by the geometry screen and then ranked by distance to the last known centre, all
15 dev seeds pass and seed 60 holds the object continuously (`dy` collapsing 0.0856 → 0.0008). Source:
`outputs/libero_fix_loop/libero_goal_task/push_the_plate_to_the_front_of_the_stove/fix_code.py` —
`_locate` / `_loc_obj`; `logs/sweep_60.log`; 2026-09-17. Companion rules:
`localize.anchor-a-relational-targets-identity-to-its-last-position` (same lock, look-alike site) and
`transport.gate-a-held-estimate-by-positional-continuity-not-by-plausibility` (same idea, held-object
site, where the response is to *hold* rather than to *select*).

---

## Screen SAM3 Candidates by Geometry, Not by Score

**Trigger**: text-prompted segmentation of an object that shares colour or texture with a fixture in
the scene (a metal bowl inside a dark drawer, a plate on a table). `max(masks, key=score)` returns
the fixture.

```python
for m in sorted(masks, key=lambda mm: -mm["score"])[:12]:
    pts = mask_to_world_points(np.asarray(m["mask"]).astype(np.uint8), depth, K, E)
    if pts is None or len(pts) < 40:
        continue
    c = np.median(pts, axis=0)
    keep = pts[np.linalg.norm(pts[:, :2] - c[:2], axis=1) < 0.075]   # trim to a cylinder
    z_hi = np.percentile(keep[:, 2], [2, 98])
    if z_hi[1] > 0.13 or (z_hi[1] - z_hi[0]) < 0.030:   # not low enough / not tall enough
        continue                                         # reject: it is not the object
    break
```

Two geometric filters do the work: a **cylinder trim** around the mask's own median (drops sparse
stragglers that stretch the cloud), and a **height band** that the real object must sit inside. Tune
`0.13` / `0.030` per scene from the object's known height — they are the whole discriminator.

**Why it works + evidence**: on `libero_goal_swap/open_the_top_drawer_and_put_the_bowl_inside` the
top-scoring mask reported `rim 0.129` where the true bowl rim is `0.039`, and grasps aimed from it
closed on air (`gap = 0.0010`). After screening, the same seed grasped on the first depth
(`gap = 0.0066`, lift `0.0059`). Source:
`outputs/libero_fix_loop/libero_goal_swap/open_the_top_drawer_and_put_the_bowl_inside/fix_code.py` —
`bowl_cloud`; 2026-09-14.

**A *base-height* gate is what rejects partial masks — a size screen cannot.** A class prompt
(`can`, `box`, `bottle`) also returns **fragments of larger objects**: a carton's top face, a bottle's
upper half. Their extents are centimetres-small, so they sit *inside* the target's size band and pass
any width/depth/height screen built from object dimensions. What distinguishes them is not their size
but **where they start**: a fragment of a taller object begins well above the table, so its cloud's low
percentile is not the table surface.

```python
lo = np.percentile(pts, 2, axis=0); hi = np.percentile(pts, 98, axis=0)
width, depth, height = hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]
if not (0.045 <= width <= 0.090 and 0.045 <= depth <= 0.090):
    continue
if not (0.045 <= height <= 0.110):                 # squat: a can, not a carton or a bottle
    continue
if min(width, depth) / max(width, depth) < 0.70:   # roughly circular footprint
    continue
if height > 1.9 * max(width, depth):               # barrel aspect
    continue
if float(lo[2]) > 0.035:                           # resting on the table, not a fragment
    continue
```

The three added ratios matter as much as the base gate, and each is measured from the observation
alone — no world-frame calibration. **Why it works + evidence**: on
`libero_object_swap/pick_up_the_tomato_sauce_and_place_it_in_the_basket` the naive screen from the
sibling task left **the orange-juice carton as the largest candidate** (n=2883) together with its own
top-face mask (base z 0.087), a milk-carton top fragment (base z 0.091), a bottle with a 0.57 footprint
ratio and two neutral grey fragments — 5–8 candidates for one real object. With the three added gates
the candidate set is **exactly 1 on all 15 development seeds**. This is load-bearing at *reward* level,
not just cleanliness: substituting the naive screen back in selected the carton, grasped it and placed
it — **reward 0.000** on seed 51. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_tomato_sauce_and_place_it_in_the_basket/fix_code.py`
— `find_cans`; 2026-09-14.

#### Pick the gates by *physical feasibility*, and never fall back to ranking by score or point count

The sections above screen candidates to *reject* decoys. This is the case where screening must also
choose the winner — and the score ranking is actively wrong. On
`libero_spatial_swap/pick_up_the_black_bowl_next_to_the_cookie_box_and_place_it_on_the_plate` the
object the language names, the cookie box, scored **0.05–0.12** — below the plate (0.70) and both
bowls (0.94) — so `max(masks, key=score)` could never return it.

The fix is not a better score threshold but a **conjunction of hard gates whose margins sit between
the competing objects**, with **first-pass-wins** as the selection rule:

```python
# find the RED box: the FIRST mask that passes wins, with hard colour MARGINS, not score
for prompt in BOX_PROMPTS:
    for m in sorted(segment_sam3_text_prompt(rgb, prompt), key=lambda x: -x["score"])[:4]:
        pts = mask_to_world_points(m["mask"].astype(np.uint8), d, K, E)
        if pts is None or not (100 <= len(pts) <= 20000):
            continue
        zlo, zhi = np.percentile(pts[:, 2], [2, 98])
        if zhi - zlo > 0.035 or zhi > 0.10:            # flat, on the table
            continue
        sx, sy = extent_xy(pts)
        if max(sx, sy) > 0.11 or min(sx, sy) < 0.025:  # box 0.078 vs plate 0.135
            continue
        col = median_rgb(rgb, m["mask"])
        if col[0] < 60 or (col[0] - col[2]) < 35 or (col[0] - col[1]) < 18:
            continue                                   # box R-B 53 vs plate R-B 20
        return (float(np.median(pts[:, 0])), float(np.median(pts[:, 1])))
```

Three rules generalise:

1. **Choose margins that sit *between* the two objects, not at one of them.** The plate is a *white*
   disc with thin red rings, so a permissive `R-B >= 20` red screen admits it alongside the box
   (`R-B 53`). The gate must be `R-B >= 35` and `R-G >= 18` — numbers picked so the plate fails twice
   over. A threshold that merely *admits* the target is not a discriminator.
2. **Add a footprint window, not just a footprint cap.** `0.078` (box) vs `0.135` m (plate) separates
   them, but only if the screen also has a *lower* bound; a cap alone still admits fragments.
3. **Ranking by point count is the same mistake as ranking by score.** The plate carries more points
   than the box, so any "most points wins" tiebreak returns the plate — and here it returned
   literally the wrong *object*: a plate finder written as "largest cloud" returned a **bowl**
   (4470 points vs the plate's 2421). It was replaced by flatness (`z-extent` 0.024 plate vs 0.044
   bowl) plus a warm colour cast, again first-pass-wins.

**Evidence**: seeds 61/62/65 localised the "box" at the plate's own position — `(0.399,-0.144)`,
`(0.396,-0.124)`, `(0.386,-0.128)`, extent `(0.13,0.12)`, rgb `[128,110,108]` — before the margin
change, and at the true box `(0.73–0.75, 0.01–0.04)`, extent `(0.078,0.058)`, rgb `[95,67,42]` after.
Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_next_to_the_cookie_box_and_place_it_on_the_plate/fix_code.py`
— `find_box` lines 213–255, `find_plate` 258–289; 2026-09-15.

### …and when you *do* keep score as a filter, use a *relative* margin, not an absolute floor

**Trigger**: a prompt returns a large pool — here **200 masks per prompt** — in which the real objects
score in one band and off-object clutter scores in another, with the bands close enough to overlap a
fixed threshold.

```python
top = max(s for s, _ in scored)
keep = [m for s, m in scored if s >= max(min_score, top - REL_SCORE_MARGIN)]   # 0.15
```

**An absolute floor admits the clutter.** Measured on
`libero_goal_task/open_the_middle_drawer_of_the_cabinet`: on seed 63 the three real cabinet handle bars
scored **0.76–0.80** while two table-clutter masks scored **0.45–0.51** — and that clutter is *large*
(two masks with a 1.65 m x-extent) yet survives a shape screen after percentile trimming. A `min_score`
of 0.40 admitted them, and the pre-fix program targeted the clutter and **never touched the cabinet**.
With the relative margin the same seed finds all three bars and pins the middle drawer (aperture 0.0136,
pulled 0.161 m). The margin is active on **14/15** development seeds of the shipped revision.

**Why relative is the right normalisation**: SAM3 scores are not comparable across prompts or scenes, so
the *gap* between the best mask and the next is the stable quantity, while any absolute cutoff is
calibrated to one scene. Keep a low `min_score` as a floor only to exclude the obviously ungrounded.

**Executed source**: `libero_goal_task/open_the_middle_drawer_of_the_cabinet` `fix_code.py`, `_scan`,
`REL_SCORE_MARGIN = 0.15`. Diagnostic evidence only — that task is **0/15** on both programs because the
named drawer is outside the arm's workspace (see `manipulation.md`, "after a stalled pull, release and
probe under no load"), so this records that the filter selects correctly, not that it raises reward.

---

## Take an Object's Centre From Its Visible Top Face, Not From the Whole Mask

**Trigger**: a small boxy object whose mask covers a *front* face as well as the top. The perspective
bias drags the whole-cloud median toward the camera, and on a 5 cm-wide object that error is most of the
grasp tolerance.

```python
zhi = float(np.percentile(pts[:, 2], 98))
top = pts[pts[:, 2] > zhi - 0.012]          # the flat upper face only
c, tsp = span_of(top)                       # midpoint of the top face's percentile box

def span_of(pts, lo=3.0, hi=97.0):
    """Midpoint and size of the percentile box of a cloud's xy projection."""
    p = np.percentile(pts[:, :2], [lo, hi], axis=0)
    return 0.5 * (p[0] + p[1]), (p[1] - p[0])
```

Use the **midpoint of a percentile box**, not the mean: a lumpy or ragged mask edge cannot drag a
percentile the way it drags a mean. Return the size too — it is the object's footprint and doubles as the
gate for `size`-based screens.

**Why it works + evidence**: on `libero_object_swap/pick_up_the_chocolate_pudding_and_place_it_in_the_basket`
seed 51 the whole-cloud median gave `cx = 0.7176` while the top face's percentile-box midpoint gave
`0.7025` — a **1.5 cm** difference, and the top-face centre is what all 15 development seeds grasped from.
Source: `outputs/libero_fix_loop/libero_object_swap/pick_up_the_chocolate_pudding_and_place_it_in_the_basket/fix_code.py`
— `span_of`, `find_pudding`; 2026-09-14.

**Third confirmation, and a free correctness check on the yaw.** On
`libero_object_swap/pick_up_the_cream_cheese_and_place_it_in_the_basket` the whole-cloud median gave
`(0.492, −0.235)` against a top-face midpoint of `(0.478, −0.236)` — 1.4 cm apart. The top-face cloud
must also be what feeds the **short-axis yaw** derivation: the visible front face adds in-plane spread
and rotates the eigenvector, so a yaw taken from the whole mask is wrong. The resulting yaw measured
177.6–179.7° on all 15 seeds, and the pinch gap that followed (0.0420–0.0422 m) matched the slab's
4.0 cm short side — so the measured grip gap doubles as an independent check that the yaw was right.
Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_cream_cheese_and_place_it_in_the_basket/fix_code.py`
— `span_of`, `slab_yaw`, `find_slab`; 2026-09-14.

**Corollary — when the grasp height is *below* the top face, use the whole mask's percentile box, not
its median.** The rule above says to prefer the top face; that is right when the pinch is near the
top. When the pinch is at mid-height the top face is the wrong plane, and the choice is then between
the whole cloud's **median** and its **percentile box** — and the median is biased toward the camera by
roughly half the object's camera-facing extent, because a single view sees only the near faces.

```python
xr = np.percentile(pts[:, 0], [2, 98])       # percentile BOX, not mean and not median:
yr = np.percentile(pts[:, 1], [2, 98])       # a ragged mask edge cannot drag a percentile
cx = float(0.5 * (xr[0] + xr[1]))
cy = float(0.5 * (yr[0] + yr[1]))
fx, fy = float(xr[1] - xr[0]), float(yr[1] - yr[0])   # doubles as the footprint gate
```

The error scales with the object's own depth, so it is negligible on a wide slab and fatal on a
**thin** one: on a 2.7 cm-deep carton the 1.3 cm median bias is **half the object's width**, and the
pads then close *beside* it.

**The diagnostic signature is that this failure looks like a perception success.** The pads descend to
a perfectly plausible `meas_z` (0.069–0.110 against a carton spanning z 0.003–0.139) and the *only*
anomalous reading is the aperture: `gap = 0.0012–0.0070`, i.e. the fingers met nothing. So treat an
air gap at a *sensible* depth as evidence about the **xy**, not about the depth — and read the grip gap
back against the object's measured width as the check (a close straddling a 5.0 cm carton must read
≈0.052).

**Evidence**: on `libero_object_task/pick_up_the_ketchup_and_place_it_in_the_basket` seed 51 the
whole-cloud median gave `cx = 0.428` against a percentile-box midpoint of `0.415` — 1.3 cm on a 2.7 cm
object. A six-candidate probe sweep closing at the median xy returned an air gap on **every** candidate
at `meas_z` 0.069–0.110; the identical descent at the midpoint returned `gap = 0.0525` at
`meas_z = 0.0977`. After the change all 15 development seeds gripped on attempt 0 with
`gap = 0.0519–0.0535`. Source: same `fix_code.py` — `standing_candidates` lines 163–232 (percentile
block at 213–229), consumed by `grasp` lines 297–334; 2026-09-16.

---

### Separate a *bowl* from a *plate* by the candidate's own z-extent — walls, not score

**Trigger**: the container prompt (`bowl`) returns the true container **and** a plate, and both are
plausible. Geometry is the separator: **a bowl has walls and a plate does not**, so the candidate's own
cloud z-extent, read against its own mouth span, separates them without any prompt or score comparison.

```python
zl = float(np.percentile(pts[:, 2], 2))
zh = float(np.percentile(pts[:, 2], 98))
xlo, xhi = np.percentile(pts[:, 0], [2, 98])
ylo, yhi = np.percentile(pts[:, 1], [2, 98])
span = 0.5 * ((xhi - xlo) + (yhi - ylo))
if zh - zl < 0.030 or not (0.06 <= span <= 0.18):   # a plate is wide and shallow; this rejects it
    continue
# then take the mouth from the top rim ring (section below)
```

The **payload** screen is the same argument on the other side of the pair — a bottle is tall *and*
narrow, so its constants are different and must not be swapped in:

```python
if zh - zl < 0.090 or max(xhi - xlo, yhi - ylo) > 0.090:   # bottle: tall AND narrow
    continue
```

**Why it works + evidence**: on `libero_goal_task/put_the_cream_cheese_in_the_bowl` — whose runtime
instruction is *"put the wine bottle in the bowl"* — the `bowl` prompt returns both the metal bowl and a
plate, and **score does not separate them**: 0.910 for the bowl against **0.447** for the plate, which
survives any absolute score floor. The two differ in the *shape of the cloud*:

| candidate | z-extent | rim (98th-pct z) | footprint | prompt score |
|---|---|---|---|---|
| metal bowl | **0.044** | **0.0391** | 0.102 × 0.099 | 0.910 |
| plate | **0.012** | **0.0070** | wider, flat | 0.447 |

Measured on **two independent workers** on this same scene, which split on *which* row of the table they
gate on — worth knowing, because the two are not equally robust. One gates on the **z-extent floor**
(`0.030`; the plate's 0.012 fails it outright) and admits the bowl on all 15 development seeds with mouth
span 0.1021–0.1027 m, stable to 0.6 mm. The other sets a floor of only `0.010`, which the plate's 0.012
**passes**, and separates the pair by **taking the highest 98th-percentile z** instead (0.039 vs 0.007);
it also reports the bowl at `zext=0.044`, `rim=0.0391`, footprint `0.102 × 0.099` — the same cloud. So
both agree on the measurement, but the z-extent floor is the one to copy: a plate with a raised rim or a
stacked pair would clear a `0.010` floor, and every downstream z (mouth centre, release height) is
derived from the rim, so taking the wrong candidate is a silent ~3 cm error in release height rather
than an obvious miss. This is the same *shape* of argument as the flatness screen above ("A merged mask
is too *tall*"): both gate on the candidate's own measured z and neither trusts the prompt or the score.
Prefer the geometric gate whenever the confusable pair differs in *shape*, and keep the score only as a
tie-break on a relative margin.

**The mirror image — screening a *payload* prompt that fires on a container.** The same geometry
argument runs in the other direction, and the ring test is the cheap part of it: when prompting for a
flat payload, require `250 ≤ n ≤ 3500`, `zhi − zlo ≤ 0.055`, `0.015 ≤ min(e) ≤ 0.085` (a bowl or plate
**ring** has `min(e) ≈ 0.13` because its span is hollow), `max(e) ≤ 0.120`, and `score ≥ 0.08`. On
`libero_goal_task/put_the_wine_bottle_on_the_rack` the `cream cheese` prompt returned the bowl at
**score 0.00** with ~2.8 k points and the plate with ~5 k until these gates were added — so a low score
alone does not reject the ring; the `min(e)` test is what does. Source:
`outputs/libero_fix_loop/libero_goal_task/put_the_wine_bottle_on_the_rack/fix_code.py` — block 0
`find_payload()`; `probe13.log` / `probe14.log`; 2026-09-17.

**Executed source**: `libero_goal_task/put_the_cream_cheese_in_the_bowl` `fix_code.py` — container screen
`find_bowl` lines **139–160** (`zl`/`zh`/`span` computed 148–153, gate 154), mouth read from
`bowl_geometry` lines 112–136; payload screen `find_bottle` lines **163–179**, gate at 175. Both ran on
15/15 development seeds. Corroborating source, same scene, independent run:
`outputs/libero_fix_loop/libero_goal_task/put_the_wine_bottle_on_top_of_the_cabinet/findings.md`
(`find_container` 140–168, screen 161–164, rim pick 168); 2026-09-17.

---

## Take a Container's Mouth Centre From Its Top Rim, Not From the Cloud Median

**Trigger**: localizing the opening of an open-topped container (basket, bin, crate) by SAM3 where the
*near* wall is far more visible than the far wall. Point density is then biased toward the camera, so the
cloud median sits outside the mouth.

```python
zhi = float(np.percentile(pts[:, 2], 98))
rim = pts[pts[:, 2] > zhi - 0.030]              # the container's OWN top rim ring
(cx, cy), _ = span_of(rim)                      # midpoint of the rim's percentile box
```

The rim ring is the only part of a container whose geometry is both visible and *about the opening*, so
select it by height first and take its percentile-box midpoint. Pair with the release rule in
[transport.md](transport.md) — "Release Below the Rim of a Tall Container Whose Floor Cannot Be Measured"
when the floor is unmeasurable, or the kinematic-floor release when the floor is unreachable.

**Why it works + evidence**: on `libero_object_swap/pick_up_the_chocolate_pudding_and_place_it_in_the_basket`
seed 51 the whole-cloud median xy was `(0.664, 0.264)` while the rim midpoint is `(0.599, 0.263)` — **6.5 cm**
apart. An independent top-down raster of the basket cloud showed the interior opening spanning `x ∈ [0.54,
0.65], y ∈ [0.21, 0.31]`, whose centre `(0.595, 0.26)` matches the rim midpoint and *not* the median. All
15 development seeds released at the rim midpoint and scored 1.0. Source: same `fix_code.py` —
`find_basket`; 2026-09-14.

**Independently replicated in a `_task` suite, where the offset was the same size.** On
`libero_object_task/pick_up_the_alphabet_soup_and_place_it_in_the_basket` the whole-cloud median sat at
`(0.658–0.684, 0.245–0.271)` against a rim midpoint of `(0.592–0.618, 0.244–0.271)` — a **6–7 cm** offset,
matching the 6.5 cm above from a different suite. Note that the `_swap` task's three baseline passes had
released at the *median* and still scored 1.0, so this bias is a live risk rather than a guaranteed
failure: it costs you whenever the object is narrow relative to the mouth. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_alphabet_soup_and_place_it_in_the_basket/fix_code.py`
— `main`, lines 220–226; 2026-09-16.

**A third instance, and the one that shows the bias is not a fixed size — measure it, don't assume
6 cm.** On `libero_object_task/pick_up_the_butter_and_place_it_in_the_basket` seed 51 the rim point
**median** reads x = 0.621 against a 2/98 range midpoint of x = 0.599: **2.1 cm** against a 0.151 m
mouth, where the two cases above were 6–7 cm. The bias scales with how lopsided the rim's visibility
is, so it is a direction to be robust against rather than a magnitude to subtract.

Two implementation details worth copying, both from `find_basket`:

- Define the rim band as a **fraction of the container's own z-extent** (here the top 15%) rather than
  as an absolute offset below the top. An absolute band (the `zhi − 0.030` in the snippet above) takes
  a different ring on a tall container than on a shallow one, which is the case that matters when the
  same helper is reused across a family of containers.
- Take the **total span** as the placement tolerance, not just the centre: it read 0.151 × 0.165 m,
  stable to 1 mm across all 15 development seeds, and it is what tells you whether the mouth is wide
  enough for the intended release (see [transport.md](transport.md) — "Release *Above* the Mouth When
  the Payload Is as Tall as the Container Is Deep"). Source: same `fix_code.py` — `find_basket` lines
  204–228; 2026-09-16.

**A third detail: when one prompt returns *two* geometry-passing masks on the same container, select by
the highest z-top.** A `basket` prompt typically returns both the outer/rim shell and the interior
floor/liner as separate masks. Select on the rim, explicitly:

```python
if best is None or cand["rim"] > best["rim"]:      # rim = the cloud's 98th-percentile z
    best = cand
```

Measured on `libero_object_task/pick_up_the_tomato_sauce_and_place_it_in_the_basket`, dev seed 51: the
top-1 `basket` mask reads `n = 11934`, `zhi = 0.142`, mouth `(0.599, 0.264)`; the second mask reads
`n = 5702`, `zhi = 0.111`, mouth `(0.615, 0.265)`. **The interior mask's rim is 3.1 cm low**, and every
z downstream is derived from it — on this task the release sits 4.0 cm below the rim, so a rim read off
the liner would move the release nearly twice as deep as intended and change the descent path entirely.

Honest scope: on this scene the three plausible selection rules — highest z-top, largest `n`, highest
score — all pick the same mask, so the measurement does not *discriminate* between them. What it does
establish is the size of the error if you take the other mask, and that "highest z-top" is the one rule
that is right *for a reason*: the rim is by definition the container's top, whereas "largest" and
"highest score" are proxies that happen to agree here. Prefer the criterion you can state. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_tomato_sauce_and_place_it_in_the_basket/fix_code.py`
— `find_basket` lines 207–240 (selection at 238–239); 2026-09-16.

**Confirm the mouth centre by *hovering the wrist camera over it*, not by argument.** The rim-box rule is
easy to state and easy to get subtly wrong, and the two candidate centres here differ by 6.5 cm — enough
that a mis-argument costs every seed. A cheap, decisive check: drive the arm to `(x, y, 0.32)` at each
candidate and read the wrist image. On seed 55 the hover over the rim box `(0.614, 0.244)` puts the basket
mouth **dead-centre in frame**, while the hover over the cloud median `(0.679, 0.245)` leaves it well left
of centre. This costs perception only, no sim steps (see "Perception Costs No Sim Steps" below), and it
converts a geometric claim into an observation — worth doing once per new container type, since the rim
band's percentiles are the part most likely to be mis-set. Source:
`outputs/libero_fix_loop/libero_object_task/pick_up_the_cream_cheese_and_place_it_in_the_basket/fix_code.py`
— `find_basket` lines 209–236; 2026-09-16.

**Variant — a *closed-walled* open container has no rim ring to select; use the extent midpoint.**
For a solid bowl or cup the height-selected band is one annulus whose far side is hidden, so it
carries the same near-wall bias as the whole cloud. There the robust centre is the
**2/98-percentile extent midpoint** of the whole cloud, after a median trim for gross outliers:

```python
def bowl_geometry(pts):
    """Robust centre: 2/98-percentile *extent midpoint*, not the median."""
    c = np.median(pts, axis=0)                      # trim gross outliers only
    m = (np.abs(pts[:, 0] - c[0]) < 0.075) & (np.abs(pts[:, 1] - c[1]) < 0.075)
    if m.sum() >= 40:
        pts = pts[m]
    xlo, xhi = np.percentile(pts[:, 0], [2, 98])
    ylo, yhi = np.percentile(pts[:, 1], [2, 98])
    return (float(0.5 * (xlo + xhi)), float(0.5 * (ylo + yhi)),
            float(np.percentile(pts[:, 2], 2)), float(np.percentile(pts[:, 2], 98)), pts)
```

This matters most when the centre feeds a **radial wall pinch** (see [grasp.md](grasp.md)): the
pinch is commanded at `centre + Rw`, so a centre that is 2 cm toward the camera puts the finger
*inside* the mouth, where closing shoves the object sideways instead of gripping it. On
`libero_spatial_swap/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate` seed 51 the
whole-cloud median read x=0.640 against an extent midpoint of 0.659 and a true centre of 0.663 — a
systematic ~2 cm near-wall bias from the bowl's far inner wall. The median-based pinch failed; the
extent-midpoint pinch held, and all 15 development seeds then rested within 0.007 m of the commanded
point with a symmetric `z=[0.003, 0.048]` (a clean rest, not a tilt). Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_next_to_the_plate_and_place_it_on_the_plate/fix_code.py`
— `bowl_geometry`; 2026-09-15.

#### Prefer the *oriented bounding box* centre over any cloud statistic — and re-derive it *after* the clip

Every fix to the median above replaces one cloud statistic with a better cloud statistic. There is a
cheaper and more robust option available in the API: the centre of the object's **oriented bounding box**.

```python
obb      = get_oriented_bounding_box_from_3d_points(pts)
_, _, _, _, _, _ = obb                              # geometry fields as returned by the library
centre   = obb[:3, 3] if obb.shape == (4, 4) else np.mean(obb, axis=0)
obb_center_xy = (float(centre[0]), float(centre[1]))
```

An OBB fits the *extent* of the visible surface along its own axes, so the near-wall density bias that
moves a median cannot move it — the OBB of a half-visible bowl is still centred near the bowl's axis,
whereas the median is pulled toward the dense near wall by construction. Measured on
`libero_spatial_swap/pick_up_the_black_bowl_on_the_cookie_box_and_place_it_on_the_plate` seed 51:
whole-cloud median `x = 0.721`, OBB centre `x = 0.744` — **23 mm apart** on a 5 cm-wide target, and the
OBB centre is the one the pinch held from. Source:
`outputs/libero_fix_loop/libero_spatial_swap/pick_up_the_black_bowl_on_the_cookie_box_and_place_it_on_the_plate/fix_code.py`
— `obb_center_xy`, `bowl_points`; 2026-09-15.

**Order matters: clip first, then fit the OBB.** Fitting the OBB to the raw mask reads a *composite*
box — for a bowl standing on a cookie box the mask bleeds through the support (see the section above,
"A *stacked* object's mask bleeds through its support"), so the raw OBB centre sits between the bowl and
the box. Call `get_oriented_bounding_box_from_3d_points` on the cloud *after* the support clip, never
before; the two rules compose in that order and only in that order.

---

## Fit a Circular Object's Rim — the Radius Is a Free Self-Check, and It Reads the Clearance

**Trigger**: you need a *round* object's xy to better than ~1 cm (bowl, plate, ramekin, cup, can), your
estimate is a point-mean or median of its SAM3 mask, and the tolerance you are fighting is the same
order as the error you are chasing. Also use it to answer "does A fit inside/on B?" — a question no
single-object measurement can answer.

A point-mean of a mask is weighted by pixel density, so for a bowl seen at ~45° the visible near wall
dominates and the centre is pulled toward it. That bias is **1–2.5 cm and changes sign with the camera
pose**, which is indistinguishable from scatter if you only ever compare *means* — which is exactly how
an aim bias survives a whole sweep unnoticed. Fitting the **top band** of the cloud to a circle removes
it, because the rim is a geometric locus, not a density:

```python
def fit_circle(x, y):                      # algebraic (Kasa) least-squares circle
    A = np.stack([x, y, np.ones_like(x)], axis=1)
    sol, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    cx, cy = sol[0] / 2, sol[1] / 2
    return np.array([cx, cy]), float(np.sqrt(sol[2] + cx * cx + cy * cy))

# rim = top band only; RANSAC-lite over 3-point fits keeps an occluded or partial rim from
# dragging the circle.  0.02 < r < 0.16 is the sanity band for tabletop objects.
```

**The fitted radius is the self-check.** Because the rim of a given object is a fixed size, a plausible
radius proves the fit locked the real rim rather than a fragment — measured **plate r = 0.065–0.067 m**
and **bowl r = 0.054 m**, identical across seeds 57/60/64. Print it; a fit that returns a wandering
radius is not a fit. Two objects' radii difference *is* the placement margin (0.065 − 0.054 = **1.1 cm**
of slack before the bowl's rim rides the plate's), which is the number that explains why a 2 cm landing
offset is fatal on that task and a 5 mm one is not.

**Do not replace the OBB with it.** On the same frames the point-mean and the circle centre differ by
**1.2–2.4 cm**, but `get_oriented_bounding_box_from_3d_points` already agrees with the circle centre to
~2 mm (seed 57 `(0.711,0.210)` vs `(0.710,0.212)`; 60 `(0.720,0.189)` vs `(0.719,0.191)`; 64
`(0.723,0.195)` vs `(0.723,0.197)`) — the OBB is the estimator, the circle fit is the *audit*. Use the
fit when you need an independent check of the centre or a clearance; keep taking the centre from the OBB.

**Executed source**: `scripts/libero/rim_circle_fit.py` (offline probe over saved keyframes; SAM3 over
HTTP + numpy, no simulator API) — `fit_circle` lines 30–36, `rim_cloud` 38–63. Copied verbatim
(md5 `fe4b7bc4883aa01eac5830120387c4e5`) from the task's debug root, where it produced the numbers
above; 2026-09-16.

### Refinement — fit the **outer sliver**, and gate the fit; a top band alone can lock an inner ring

"The rim is the top band" is not sufficient on a **flared or ramped** rim, whose cross-section rises
monotonically inward: the top band then contains several concentric circles of similar height and the fit
settles on one *inside* the true outer edge. Measured on
`libero_goal_task/put_the_bowl_on_top_of_the_cabinet`, a saucer whose outer 15 mm flares at ~21°: an
ungated fit on the top band returned **r = 0.0654** against a true **0.0700**, and every close aimed
5 mm inside the rim and read air.

Restrict the fit to the outermost sliver and accept it only if it is *round and where the object's own
extent says it should be*:

```python
sliver = pts[pts[:, 2] > 0.965 * np.percentile(pts[:, 2], 99.5)]   # outer sliver only
(r, c), resid = fit_circle(sliver[:, 0], sliver[:, 1])
if resid < 0.004 and 0.95 * r99_5 < r < 1.05 * r99_5 and np.linalg.norm(c - c_prev) < 0.008:
    use(c, r)                     # else keep the previous aim
```

The same discipline applies to any **re-fit**: gate it against the first accepted fit
(`|Δr| ≤ 5 mm`, `|Δcentre| ≤ 15 mm`) rather than accepting each new one. On that task every re-aim on
seeds 55–65 was **rejected**, which is the gate working — the segmentation drifted `r_out 0.0676 → 0.0760`
(8 mm) within one episode with the centre moving 15–26 mm, and tracking the drift made every later
attempt worse than holding the first, best mask.

**Executed source**: same `fix_code.py`, fit + gate lines 160–178 and the re-fit gate at `relocalize`
(line 321). Diagnostic evidence only — that task is 0/15 on both programs for a geometric reason (see
`grasp.md`, "a planar pad face on a shallow ramp is a wedge"), so this records that the gate **rejects
correctly**, not that it raises reward.

---

## Correct a Cylinder's Axis for the Single-View Half-Cylinder Bias

**Trigger**: estimating the grasp axis of a bottle or other round-bodied object from **one** camera's
depth cloud. What the camera sees of a cylinder is a *half* cylinder, so the visible-surface centroid
sits roughly `0.64 r` toward the camera from the true axis. On a 2–4 cm body that is a large fraction of
the grasp tolerance, and a pinch aimed at the raw centroid closes on air or skates off the side.

```python
slab = pts[np.abs(pts[:, 2] - gz) < 0.020]        # thin z slab at the intended grasp height
u, v, w = E[:3, 0], E[:3, 1], E[:3, 2]            # camera axes expressed in world
r = 0.5 * max(float((slab @ u).max() - (slab @ u).min()),
              float((slab @ v).max() - (slab @ v).min()))
r = float(np.clip(r, 0.012, 0.045))
axis = slab.mean(axis=0) - 0.64 * r * (-w)        # push back, away from the camera
```

Take `r` from the **lateral silhouette extents**: the width of the slab perpendicular to the view
direction is unbiased, whereas any measure taken along the view ray is not. Then displace the centroid by
`0.64 r` along `-w` — away from the camera, since `w` points from the camera into the scene.

**Why it works + evidence**: on `libero_object_swap/pick_up_the_bbq_sauce_and_place_it_in_the_basket`
grasping at the uncorrected centroid missed; at the bias-corrected axis the gripper closed at TCP
z = 0.074 with a measured gap of 0.0361–0.0365 m on **all 15 development seeds**. Source:
`outputs/libero_fix_loop/libero_object_swap/pick_up_the_bbq_sauce_and_place_it_in_the_basket/fix_code.py`
— `bottle_axis`; 2026-09-14.

**Variant — the coefficient is not universal, and the form above says `0.64` while a second task
measures `1/√2`.** A clearance-audited form on `libero_goal_task/put_the_bowl_on_the_plate` reads the
same effect off the *near silhouette edge* and lands on `0.707 r`, not `0.64 r`:

```python
d  = E[:3, 2]; dh = normalize(d[:2])       # camera -> object, xy only
u  = -dh                                   # object -> camera, xy only
p  = np.array([-u[1], u[0]])               # perpendicular to the view
proj = band[:, :2] @ p
R   = 0.5 * float(np.percentile(proj, 98) - np.percentile(proj, 2))   # TRUE radius
med = np.median(band[:, :2], axis=0)
axis = med - 0.707 * R * u                 # undo the half-cylinder bias
if not (0.004 < R < 0.06):                 # not cylinder-like -> OBB fallback
    axis = np.asarray(get_oriented_bounding_box_from_3d_points(band)["center"])[:2]
```

Three differences from the form above, all deliberate: the radius comes from the **98th−2nd percentile
range perpendicular to the view** rather than the min/max extent (robust to the single stray point that
sets a min or max); the band is taken at the **intended grasp height** (`|z − z_pinch| < 0.012`) rather
than at a fraction of the object's own height, so the radius is measured where the fingers will close;
and there is an explicit **cylinder-likeness gate with an OBB fallback**, so a non-round object does not
get a cylinder correction applied to it. Verified to **0.3–1 mm** against the cloud's own near-silhouette
edge on three seeds, and the resulting pinch gap (0.0148 m) matched the independently measured neck
diameter (0.0136–0.0156 m), i.e. the fingers closed on the neck rather than on air. Source:
`outputs/libero_fix_loop/libero_goal_task/put_the_bowl_on_the_plate/fix_code.py` — `cylinder_axis`,
lines 151–183; 2026-09-17.

**Do not average the two constants.** They were calibrated on different bodies with different band
definitions, and the honest statement is that the coefficient is between 0.64 and 0.71 with the exact
value set by how the band and the radius are measured. The transferable part is the *structure* — take
the radius from the view-perpendicular extent, then displace the centroid along the view ray by a
fraction of it — plus a check against an independent edge. Whichever coefficient you use, verify it
against the object's own silhouette before trusting the pinch.

Companion to "Take an Object's Centre From Its Visible Top Face, Not From the Whole Mask" above: that one
removes the bias **vertically** (top face rather than whole mask), this one removes it **laterally** (view
ray rather than silhouette). Both are the same rule — the visible surface is not the object.

---

## Lift the Height Screen When Verifying an Object That Moved to a New Height

**Trigger**: verifying a placement where the object's final height differs from its initial height —
table → drawer, table → shelf, table → raised platform. A localization screen tuned to the *pick*
height rejects the object at its new height.

```python
pts = bowl_cloud(get_observation(), z_top=0.32)    # NOT the table-top screen (z_top=0.13)
c = pts.mean(axis=0)
return bool(c[1] < drawer_face - 0.02 and c[2] > 0.08)
```

**Why it works + evidence**: on `libero_goal_swap/open_the_top_drawer_and_put_the_bowl_inside` the
`z_top=0.13` screen rejected the bowl sitting correctly in the drawer (its cloud is at z 0.20–0.25)
and instead accepted a spurious mask at `[0.258, 0.205, 0.021]` — costing a second attempt and then
the episode horizon. The lifted screen accepts the true placement. Source: same `fix_code.py` —
`bowl_inside_drawer`; 2026-09-14.

**Related — the segmented cloud's height is a clean post-placement success detector.** For a
container whose rim sits below the surrounding fixture, the 98th-percentile z of the object's cloud
separated outcomes cleanly: ≤ 0.254 m on all successes vs ≥ 0.267 m on all failures (13/13 dev
replays). NOTE: this test was validated **offline** and is not in the shipped program, and using it
as a *retry* trigger is dangerous on a placement task — a successful placement is exactly the case
with episode budget left over, so a false negative spends it re-grasping an object that is already
in place. Use it as a readout, not as a control gate.

---

## Perception Costs No Sim Steps — Re-Localise Freely Inside a Control Loop

**Trigger**: a closed-loop push, drag, or approach whose contact collapses over a long move, under a
tight episode horizon. The instinct is to avoid re-observing because "perception is expensive" — in
this harness it is *free*.

```python
def object_now():                      # costs 0 sim steps
    rgb, d, K, E = observe()
    pts, _, _ = find(rgb, d, K, E, PROMPTS)
    c = np.median(pts, axis=0)
    r = float(np.percentile(np.linalg.norm(pts[:, :2] - c[:2], axis=1), 98))
    return c, r                        # 98th percentile, NOT the 90th

for k in range(12):
    c, r = object_now()
    if c[1] + r >= TARGET_YMIN + 0.010:
        break
    slide(...)
```

`get_observation`, `segment_sam3_text_prompt`, `segment_sam3_point_prompt` and
`mask_to_world_points` do **not** advance the sim clock — only `move_to_joints` / `goto_pose` /
`close_gripper` do. So a 12-iteration re-localisation loop costs 12 arm commands, not 12 episodes, and
closing the loop is almost always cheaper than planning open-loop and being wrong. This pairs with
the episode-horizon budget in [manipulation.md](manipulation.md).

**Why it works + evidence**: on `libero_goal_swap/push_the_plate_to_the_front_of_the_stove` seed 51 a
12-iteration closed-loop drag kept a valid object estimate for all 12 iterations (re-measured at
0.450–0.472, −0.072 … −0.067) while the open-loop version ran out of horizon. Note the footing: that
task reached **0/15 development seeds** — the loop held its estimate, the task still did not solve.
Source: `outputs/libero_fix_loop/libero_goal_swap/push_the_plate_to_the_front_of_the_stove/fix_code.py`
— `plate_now`, lines 98–114; 2026-09-14.

---

## Key Signals

- `num_masks = 0` → prompt not recognized — try a more specific or different description
- `score < 0.5` → low confidence — try alternative prompt before accepting
- `len(pts) < 10` → mask too small or object occluded — try different prompt
- Usually pick `max(masks, key=lambda d: d["score"])` — highest confidence mask
- **Exception: size disambiguation** — when two similar objects exist, use bbox pixel area `(box[2]-box[0])*(box[3]-box[1])` to select by size, not score. The `box` field in each mask dict gives `[x1,y1,x2,y2]` in pixels.
- **Exception: geometry filtering** — when a taller/larger object gets a higher SAM3 score than the target, filter by 3D Z-height first, then pick highest score among geometry-matching candidates.

---

## Prompting Strategy

1. **Be specific first** — include color + shape + material: `"blue rectangular box"`
2. **Fall back to generic** — shorter, simpler descriptions
3. **For targets (bowls, plates, racks)** — material descriptor helps: `"silver bowl"` > `"bowl"`
4. **Always confirm with `env.handle.task_language`** — authoritative instruction regardless of suite
5. **Detect target BEFORE grasping** — post-lift re-observation is corrupted by the robot arm blocking the camera; detect both object and target while the arm is at home position and view is clean
6. **ARM OCCLUSION PATTERN** — If the target object is in the CENTER of the table, it may be hidden behind the robot arm at home position. Move arm to an observation position (e.g., `solve_ik([0.55, 0.30, 0.40], TOP_DOWN)`) before observing. Symptom: SAM3 finds cans/flat objects but not the target, scores are low (<0.2) for the intended object.

---

## Placement Z Notes

SAM3 mask centroid Z reflects the **camera-facing surface**, not the true top.
For targets with vertical extent (bowls, raised platforms), adjust placement Z from observed trace data.

| Target | Z formula | Notes |
|---|---|---|
