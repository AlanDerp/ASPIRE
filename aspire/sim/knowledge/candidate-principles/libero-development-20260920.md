# LIBERO development candidate principles

LLM-generated candidate guidance from the 2026-09-20 LIBERO development review. These
principles are unvalidated development evidence. Use them as hypotheses and inspect
observations; do not treat them as canonical knowledge or as proof of task success.

1. **Use runtime language first.** In `_task` suites, parse `env.task_language`; task
   IDs and filenames can be dispatch keys whose object or relation is remapped.
2. **Filter semantic candidates before relations.** Remove low-score, tiny, partial,
   and support-surface masks before spatial ranking; thresholds are class-specific.
3. **Disambiguate same-class objects with relation anchors and geometry.** Combine the
   named relation, measured support, height, shape, and consistency across views.
4. **Gate point clouds by shape and height.** Reject masks whose geometry or table-level
   extent is inconsistent with the requested object before planning motion.
5. **Confirm grasps with closure and payload motion.** A closing gap alone can be an
   air grasp; require a plausible hold and measured lift or payload displacement.
6. **IK success is not physical reachability.** Re-read TCP state after commands and
   use measured kinematic-floor and position-dependent reach limits.
7. **Use small Cartesian hops with progress checks.** Ladder long moves, re-read the
   TCP after each hop, and stop or adapt when measured progress stalls.
8. **Budget retries by carry count and episode cost.** Spend attempts where a carry is
   likely to pay off; avoid treating failed air grasps as successful carries.
9. **Do not return home while holding or positioned.** Move directly to the next phase
   after a confirmed hold; use home only when no payload is being carried.
10. **Measure TCP/payload offset with one sign convention.** Compute release columns
    from measured offset, especially for wall or radial pinches.
11. **Derive release height from support and grasp offset.** Use measured support,
    payload base, hang, and fingertip offset rather than reusing command heights.
12. **For safe containers, descend until contact or stall can center the payload.**
    Check mouth, payload, rim, and reachable-floor geometry before going below the rim.
13. **Verify placement after settling with XY footprint and resting height.** Re-segment
    the payload and require both conditions; a single center or height check can lie.
14. **On slopes, target a reachable downhill lip with measured reach clamp.** Flatness
    alone can select an unsupported gap or an unreachable point.
15. **Rotate articulated controls in place in a fixed world direction.** Pinch an upper
    band, keep XYZ fixed, and sweep wrist yaw; use task semantics for direction and retry.

Known evidence examples include `outputs/libero_fix_loop/libero_goal_swap/put_the_bowl_on_the_plate/findings.md`.
