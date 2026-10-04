"""Environment-side development entry point: one attempted episode per process.

Copy into XPolicyLab/policy/ASPIRE/deploy.py for a development trial. Policy
exceptions exit the process, because the pinned evaluator otherwise retries
failed calls without counting an episode. No task predicate or reward changes.
"""
_ATTEMPTED = False


def eval_one_episode(TASK_ENV, model_client):
    global _ATTEMPTED
    if _ATTEMPTED:
        raise SystemExit("ASPIRE development runner permits one attempted episode")
    _ATTEMPTED = True
    try:
        model_client.call(func_name="reset")
        print("ASPIRE single attempted episode started", flush=True)
        while not TASK_ENV.is_episode_end():
            obs = TASK_ENV.get_obs()
            model_client.call(func_name="update_obs", obs=obs)
            actions = model_client.call(func_name="get_action")
            if len(actions) != 1:
                raise ValueError("ASPIRE development trial requires one action per chunk")
            TASK_ENV.take_action(actions[0])
    except Exception as exc:
        print("ASPIRE single attempt failed: " + type(exc).__name__ + ": " + str(exc), flush=True)
        raise SystemExit(1) from exc
    finally:
        model_client.call(func_name="close")
