"""Deployment checks for a generated-code worker boundary.

The Python object-capability boundary is always used by dynamic-v2. Private audit
modes additionally require a deployment that declares an isolated worker and
places private artifacts outside the public trial root.
"""

from __future__ import annotations

from pathlib import Path
import json
import os
import selectors
import shutil
import subprocess
import sys
import time
from typing import Any, Callable


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


def worker_isolation_available() -> bool:
    return sys.platform == "darwin" and shutil.which("sandbox-exec") is not None


def validate_worker_isolation(public_root: Path, private_root: Path, *, isolated_worker: bool) -> None:
    if not isolated_worker:
        raise ValueError("private audit modes require an isolated generated-code worker")
    public = public_root.resolve()
    private = private_root.resolve()
    if public == private or public in private.parents or private in public.parents:
        raise ValueError("public and private artifact roots must be disjoint")
    if not worker_isolation_available():
        raise RuntimeError("no supported OS sandbox is available for private audit mode")


def execute_isolated_python(
    code: str,
    observation: dict[str, Any],
    helpers: dict[str, Callable[..., Any]],
    *,
    private_root: Path,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Run code in a fresh macOS sandbox and proxy only named public helpers."""
    if not worker_isolation_available():
        raise RuntimeError("no supported OS sandbox is available")
    private = str(private_root.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    profile = (
        '(version 1)(allow default)(deny network*)(deny file-write*)'
        f'(deny file-read* (subpath "{private}"))'
    )
    command = [
        "sandbox-exec", "-p", profile, sys.executable, "-m",
        "aspire.sim.cap.envs.generated_worker_runtime",
    ]
    # Do not inherit credentials or experiment-control variables. The worker only
    # needs interpreter/import settings; robot access is exclusively JSON RPC.
    environment = {
        key: os.environ[key]
        for key in ("PATH", "PYTHONPATH", "DYLD_LIBRARY_PATH", "LANG", "LC_ALL")
        if key in os.environ
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1, env=environment,
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps(_json_ready({
        "code": code, "observation": observation,
        "api_names": sorted(helpers),
    }), ensure_ascii=False) + "\n")
    process.stdin.flush()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("generated worker timed out")
            if not selector.select(remaining):
                raise TimeoutError("generated worker timed out")
            line = process.stdout.readline()
            if not line:
                stderr = process.stderr.read() if process.stderr else ""
                raise RuntimeError(f"generated worker exited without result: {stderr}")
            message = json.loads(line)
            if message.get("type") == "call":
                name = str(message.get("name"))
                if name not in helpers:
                    response = {"type": "return", "ok": False, "error_type": "unregistered-api"}
                else:
                    try:
                        value = helpers[name](*message.get("args", ()), **message.get("kwargs", {}))
                        response = {"type": "return", "ok": True, "value": _json_ready(value)}
                    except BaseException as error:
                        response = {"type": "return", "ok": False, "error_type": type(error).__name__}
                process.stdin.write(json.dumps(response, ensure_ascii=False) + "\n")
                process.stdin.flush()
                continue
            if message.get("type") == "done":
                process.wait(timeout=5)
                return {
                    "ok": bool(message.get("ok")),
                    "stdout": str(message.get("stdout", "")),
                    "stderr": str(message.get("stderr", "")),
                    "result": message.get("result"),
                }
            raise RuntimeError("generated worker emitted an invalid protocol message")
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
