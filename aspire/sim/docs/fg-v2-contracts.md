# Dynamic FG v2 contracts

`dynamic-v2` is opt-in. When disabled, the legacy code-generation path is unchanged.
An enabled trial accepts exactly one JSON `AgentTurn` envelope per model response.
Invalid turns commit no plan, target, action, observation, or completion state.

The public chain is `task → plan/spec → event → sensor evidence → observed
observation → public verdict → prompt projection`. Audit observations and comparisons
live in a separate private store. They never alter the public verdict in
`observed_only` or `held_out_audit`.

When image or video differencing is enabled, the VDM is an observation provider for
the Actor-authored specification, not an author of completion semantics. Each event
sends the active requested targets and event-aligned before/after images or turn video
to the VDM. The VDM returns one observed value, direct visual evidence, confidence,
and an optional probe recommendation per target, plus a separate objective scene
change description. Target IDs must match the request exactly. Missing views,
unresolved identity, low confidence, type mismatch, or disagreement between the
reported value and the VDM's provisional verdict fails closed to `unknown`.

The harness recomputes every final verdict from the Actor's immutable
`operator`/`expected` pair; VDM prose and provisional verdicts cannot change the FG
standard. With visible feedback, the next Actor prompt presents the VDM execution
description and the Agent-defined FG verification as separate sections.

Targets have one of three temporal roles: `milestone`, `terminal`, or `invariant`.
A milestone must have been satisfied at least once; a terminal target must have a
fresh satisfied verdict at finish; an invariant must have complete tick coverage for
its requested window. Missing samples produce `unknown`, never an inferred success.

Target patches are append-only. `replace` and `retire` require a reason and a parent
target. A required target cannot be removed, made optional, rebound to another entity,
given a weaker threshold, or assigned a shorter temporal window without a new task
coverage review.

`feedback=shadow` still parses AgentTurn v2 and records the full public FG chain, but
its verdict does not gate an Agent finish request and no FG projection is returned to
the Actor. `feedback=visible` requires every later control turn to bind the latest
public snapshot hash and applies the required-target finish gate.

Private audit modes execute generated Python in a fresh macOS sandbox process. The
worker has no environment or audit object, cannot access the configured private root,
cannot write files or use the network, and can invoke robot operations only through
the parent harness's named JSON RPC facade. Startup fails when this OS boundary is not
available. Static Python checks remain an admission layer rather than the isolation
mechanism.

The trial records execution success, the Agent's finish request, the FG finish verdict,
and simulator task completion separately. Dynamic-v2 success requires both an Agent
finish request and an admitted FG finish verdict; a zero sandbox return code is not
task success.
