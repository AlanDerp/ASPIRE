# LIBERO Shared Robot Skills

These files contain reusable, observation-only robot-control knowledge shared across LIBERO experiments. Pipeline orchestration belongs in experiment directories; measurement procedures belong in [../analysis/](../analysis/).

| Skill | Purpose |
|---|---|
| [grasp.md](grasp.md) | Grasp selection, orientations, gripper evidence, and pick/place skeletons |
| [localize.md](localize.md) | SAM3 prompting, disambiguation, and 3D localization helpers |
| [transport.md](transport.md) | Waypoints, collision-free transit, and placement approaches |
| [manipulation.md](manipulation.md) | Drawers, knobs, switches, pushing, and other contact tasks |

Promoted findings should include provenance: source suite/task, development seeds, held-out result when available, source code path, and date. Avoid universal claims from one scene or seed.

## Reading trial artifacts (provenance rules learned the hard way)

**The replay harness may rewrite the code it executes.** `replay_trial.py` splits the program on
`^# Code block \d+`, runs each block, and prints `reward=`/`terminated` after **every** block, so a file
with no markers is one block. When the source has no such marker, the copy it saves to the run directory
(`…/run/trial_<N>_sandboxrc_<K>_*/code.py`) carries a prepended `# Code block 0` header and its md5 will
**not** equal the source file's even when the source is otherwise byte-identical.

Do **not** reach for a normalised hash first — it cuts both ways. `cmp` the raw bytes, and only normalise
if that fails:

```bash
cmp source.py run/trial_N_*/code.py && echo IDENTICAL        # the authoritative check
grep -v '^# Code block [0-9]*$' code.py | md5sum             # only if the raw bytes differ
```

Two traps, both of which have produced a false alarm in practice:

- **Normalising when you did not need to.** Some shipped programs open with their *own* `# Code block 0`
  line. For those the harness prepends nothing, the trial copy is byte-identical, and the raw md5s match —
  but stripping the marker from *one* side (or from both) yields a third, meaningless value that looks
  like a revision mismatch. Always strip **both** sides or **neither**.
- **Concluding "mismatch" from a raw comparison on a markerless file**, which reports a mismatch on
  *every* trial. That is worse than no check at all — a false-positive generator that sends a correct
  worker back for nothing.

**A sweep that replays a file *in place* is silently invalidated by any later edit.** The logs record the
file's content at *run time* only, so an edit after the sweep orphans the whole table. Every sweep must
print the md5 **before and after**, and archive the executed bytes next to it:

```bash
md5sum "$TASK_DIR/fix_code.py"        # before
# ... run all seeds against that exact file ...
md5sum "$TASK_DIR/fix_code.py"        # after  - if these differ, the table is not evidence
```

Two cheap checks that catch the same class of error: the worker's **stated line count** against
`wc -l` on the file it shipped, and a glance at its **sweep script** — a loop restarted at a *higher*
index than the one it replaced means the earlier indices kept stale logs.

**`sandbox_rc != 0` does not mean the reward is invalid, and it does not identify the cause.** In this
harness the dominant non-zero rc is a single exception:

```
ValueError: executing action in terminated episode
   ... robosuite/environments/base.py, in step
```

It means the program issued one more `step` after the episode had already ended. That happens on **both**
sides of the outcome, so the rc alone tells you nothing. Read the two flags at the bottom of
`summary.txt` instead — they are decisive:

| Flags | Meaning | Status of the crash |
|---|---|---|
| `Terminated: True` | the goal was reached; the reward was **latched at 1.0 before** the extra step | **benign** — a post-success crash, not a failure |
| `Terminated: False, Truncated: True` | the episode hit the horizon and was truncated | **post-failure** — the horizon caused the loss, not the crash |

Measured on `libero_goal_task/open_the_top_drawer_and_put_the_bowl_inside`: dev seed 54 failed with
`Truncated: True` and this crash — i.e. the class is visible in development evidence — while on the same
program four *passing* trials also carried `sandbox_rc_1` with `Terminated: True`. Diagnosing from the rc
would have both discarded four valid trials and misattributed a horizon loss to a code crash. When the
failure is real, count the program's own moves against the episode horizon (see
`manipulation.count-your-own-motion-against-the-episode-horizon`).
