"""Quant sandbox: every number in a report is computed here, never by the LLM.

Code runs in a separate interpreter with a timeout, isolated mode (-I) and an empty working
directory. mode="docker" adds real isolation (no network, read-only FS, memory cap) and is
what deployment uses; "subprocess" is for laptops and CI.
The code must assign a dict named `result`; it is returned as JSON.
"""
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass

PRELUDE = "import json, math, statistics\n"
EPILOGUE = "\nprint('__RESULT__' + json.dumps(result, default=float))\n"
DOCKER_IMAGE = "python:3.12-slim"


@dataclass
class QuantResult:
    ok: bool
    result: dict
    error: str = ""


def run(code: str, inputs: dict | None = None, timeout: float = 10.0,
        mode: str = "subprocess") -> QuantResult:
    src = PRELUDE + f"inputs = json.loads({json.dumps(json.dumps(inputs or {}))})\n" + code \
        + EPILOGUE
    with tempfile.TemporaryDirectory() as tmp:
        if mode == "docker":
            cmd = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only",
                   "--memory", "256m", "--cpus", "0.5", DOCKER_IMAGE, "python", "-I", "-"]
        else:
            cmd = [sys.executable, "-I", "-"]
        try:
            p = subprocess.run(cmd, input=src, capture_output=True, text=True, timeout=timeout,
                               cwd=tmp, check=False)
        except subprocess.TimeoutExpired:
            return QuantResult(False, {}, f"timeout after {timeout}s")
    marker = next((ln for ln in p.stdout.splitlines() if ln.startswith("__RESULT__")), None)
    if p.returncode != 0 or marker is None:
        return QuantResult(False, {}, (p.stderr or p.stdout)[-2000:])
    return QuantResult(True, json.loads(marker[len("__RESULT__"):]))
