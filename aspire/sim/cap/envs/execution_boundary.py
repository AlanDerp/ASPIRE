"""Static admission check for dynamic-v2 generated Python.

This blocks direct names and known private APIs before the object-capability
execution path. It supplements, but does not replace, deployment isolation.
"""

from aspire.sim.cap.agent_protocol.safety import validate_public_python

__all__ = ["validate_public_python"]
