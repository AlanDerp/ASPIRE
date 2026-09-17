"""Child runtime for generated code; communicates only through JSON RPC."""

from __future__ import annotations

import contextlib
import io
import json
import math
import sys
import traceback
from typing import Any

import numpy as np


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return _json_ready(tolist())
    raise TypeError(f"value is not JSON transferable: {type(value).__name__}")


def _send(value: dict[str, Any]) -> None:
    sys.__stdout__.write(
        json.dumps(_json_ready(value), ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    sys.__stdout__.flush()


def _receive() -> dict[str, Any]:
    value = json.loads(sys.__stdin__.readline())
    if not isinstance(value, dict):
        raise ValueError("worker message must be an object")
    return value


def _proxy(name: str):
    def call(*args: Any, **kwargs: Any) -> Any:
        _send({"type": "call", "name": name, "args": args, "kwargs": kwargs})
        response = _receive()
        if response.get("type") != "return":
            raise RuntimeError("invalid parent RPC response")
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error_type", "public API error")))
        return response.get("value")

    return call


def main() -> None:
    request = _receive()
    safe_builtins = {
        "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
        "enumerate": enumerate, "Exception": Exception, "float": float,
        "int": int, "len": len, "list": list, "max": max, "min": min,
        "print": print, "range": range, "reversed": reversed, "round": round,
        "set": set, "sorted": sorted, "str": str, "sum": sum, "tuple": tuple,
        "zip": zip,
    }
    namespace: dict[str, Any] = {
        "__builtins__": safe_builtins, "__name__": "__main__",
        "obs": request.get("observation", {}),
        "INPUTS": request.get("observation", {}), "RESULT": None,
        "np": np, "numpy": np, "math": math,
    }
    for name in request.get("api_names", ()):
        namespace[str(name)] = _proxy(str(name))
    stdout, stderr = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exec(compile(str(request["code"]), "<agent-turn-v2>", "exec"), namespace, namespace)
        _send({
            "type": "done", "ok": True, "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(), "result": namespace.get("RESULT"),
        })
    except BaseException:
        traceback.print_exc(file=stderr)
        _send({
            "type": "done", "ok": False, "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(), "result": None,
        })


if __name__ == "__main__":
    main()
