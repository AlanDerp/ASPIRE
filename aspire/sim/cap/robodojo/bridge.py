# SPDX-License-Identifier: Apache-2.0
"""Turn blocking ASPIRE controls into one-action XPolicyLab chunks."""
import copy
import math
import threading


class EpisodeClosed(RuntimeError):
    pass


class RolloutBridge:
    def __init__(self, spec, timeout=120.):
        self.spec = spec
        self.timeout = float(timeout)
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        self.condition = threading.Condition()
        self.observation = None
        self.pending = None
        self.in_flight = False
        self.closed = False
        self.finished = False
        self.error = None
        self.tick = 0
        self.env_idx = None

    def update(self, obs):
        with self.condition:
            self._check()
            index = obs.get("env_idx", 0)
            if self.env_idx is not None and index != self.env_idx:
                raise ValueError("environment index changed without reset")
            if self.observation is not None and not self.in_flight:
                raise RuntimeError("update_obs requires a preceding get_action; reset before a new episode")
            self.env_idx = index
            self.observation = copy.deepcopy(obs)
            if self.in_flight:
                self.tick += 1
                self.in_flight = False
            self.condition.notify_all()

    def observe(self):
        with self.condition:
            self._check()
            if self.observation is None:
                raise RuntimeError("update_obs must precede skill execution")
            return copy.deepcopy(self.observation)

    def _check(self):
        if self.closed:
            raise EpisodeClosed("episode closed or reset")

    def send(self, action):
        action = self.spec.validate_action(action)
        with self.condition:
            self._check()
            if self.pending is not None or self.in_flight:
                raise RuntimeError("only one action may be outstanding")
            tick = self.tick
            self.pending = action
            self.condition.notify_all()
            if not self.condition.wait_for(lambda: self.tick > tick or self.closed, self.timeout):
                self.closed = True
                self.pending = None
                self.condition.notify_all()
                raise TimeoutError("action not acknowledged by a new observation")
            self._check()
            return copy.deepcopy(self.observation)

    def action(self):
        with self.condition:
            self._check()
            if self.in_flight:
                raise RuntimeError("get_action called twice without update_obs")
            if not self.condition.wait_for(lambda: self.pending is not None or self.finished or self.closed, self.timeout):
                self.close()
                raise TimeoutError("skill produced no action before timeout")
            self._check()
            if self.error is not None:
                raise RuntimeError(f"ASPIRE skill failed: {self.error}")
            # Finished programs hold measured state; only the official evaluator
            # decides success/termination. Do not fabricate a success reward.
            action = self.pending if self.pending is not None else self.spec.hold_action(self.observation["state"])
            self.pending = None
            self.in_flight = True
            return [copy.deepcopy(action)]

    def finish(self, error=None):
        with self.condition:
            self.error = error
            self.finished = True
            self.condition.notify_all()

    def close(self):
        with self.condition:
            self.closed = True
            self.pending = None
            self.condition.notify_all()
