"""Code the system writes for itself: feature plugins, checked, sandboxed, and judged.

The loop can ask an LLM to write a new feature function

    def features(text: str) -> dict[str, float]

aimed at the topics the champion misses. Before that code can influence anything:
1. validate(): a static check of the syntax tree. Only `re` and `math` may be imported; no
   file, network, process or reflection access (open, eval, exec, getattr, dunder attributes...).
2. extract(): it runs in a separate, isolated interpreter (python -I, empty working directory,
   no environment secrets, wall-clock timeout) over every filing. A smoke run on a sample must
   return the same finite numbers twice (deterministic) before the full run starts.
3. The features join the model through Recipe.plugin, and the sealed judge decides, exactly as
   for any other change. Rejected code is kept on disk and in the audit log, never served.
Only a promoted plugin is executed at serving time, and then with the same restricted builtins.
"""
import ast
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

MAX_CODE = 6000          # characters
MAX_FEATURES = 16
TEXT_CAP = 400_000       # characters of each filing the plugin sees
ALLOWED_IMPORTS = {"re", "math"}
BANNED_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr",
    "setattr", "delattr", "input", "breakpoint", "exit", "quit", "help", "memoryview", "type",
    "object", "super", "dir", "id", "hash", "classmethod", "staticmethod", "property",
    "os", "sys", "subprocess", "socket", "shutil", "pathlib", "importlib", "builtins",
}
# module attributes a plugin may use (a public attribute can still lead elsewhere, e.g. re.enum.sys)
MODULE_ATTRS = {
    "re": {"compile", "search", "match", "fullmatch", "findall", "finditer", "sub", "subn",
           "split", "escape", "I", "IGNORECASE", "M", "MULTILINE", "S", "DOTALL", "X", "VERBOSE"},
    "math": {"log", "log1p", "log10", "log2", "sqrt", "exp", "floor", "ceil", "tanh", "fabs",
             "isfinite", "inf", "pi", "e"},
}
# attributes that lead to reflection or string-format escapes, on any object
BANNED_ATTRS = {"format", "format_map", "mro", "modules", "f_globals", "f_locals", "f_back",
                "gi_frame", "cr_frame", "tb_frame", "func_globals", "sys", "os", "enum"}
SAFE_BUILTINS = {n: __builtins__[n] if isinstance(__builtins__, dict) else getattr(__builtins__, n)
                 for n in ("len", "min", "max", "sum", "abs", "round", "float", "int", "str",
                           "bool", "list", "dict", "set", "tuple", "range", "enumerate", "zip",
                           "sorted", "reversed", "any", "all", "isinstance", "map", "filter",
                           "ValueError", "ZeroDivisionError", "Exception")}


def _restricted_import(name, *args, **kwargs):
    if name not in ALLOWED_IMPORTS:
        raise ImportError(f"import of {name!r} is not allowed")
    return {"re": re, "math": math}[name]


class UnsafeCode(ValueError):
    pass


def validate(code: str) -> None:
    """Raise UnsafeCode unless the code is one plain `features(text)` function using re/math."""
    if len(code) > MAX_CODE:
        raise UnsafeCode(f"code is over {MAX_CODE} characters")
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise UnsafeCode(f"syntax error: {e.msg} (line {e.lineno})") from e
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if [f.name for f in funcs].count("features") != 1:
        raise UnsafeCode("must define exactly one function named `features`")
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef | ast.Import | ast.Assign | ast.Expr):
            raise UnsafeCode(f"top-level {type(node).__name__} is not allowed")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            raise UnsafeCode("`from ... import` is not allowed")
        if isinstance(node, ast.Import):
            bad = [a.name for a in node.names if a.name not in ALLOWED_IMPORTS]
            if bad:
                raise UnsafeCode(f"import of {', '.join(bad)} is not allowed")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr in BANNED_ATTRS:
                raise UnsafeCode(f"access to attribute {node.attr!r} is not allowed")
            if isinstance(node.value, ast.Name) and node.value.id in MODULE_ATTRS                     and node.attr not in MODULE_ATTRS[node.value.id]:
                raise UnsafeCode(f"{node.value.id}.{node.attr} is not allowed")
        if isinstance(node, ast.Name) and (node.id in BANNED_NAMES or node.id.startswith("__")):
            raise UnsafeCode(f"use of {node.id!r} is not allowed")
        if isinstance(node, ast.Global | ast.Nonlocal | ast.ClassDef | ast.AsyncFunctionDef |
                      ast.Await | ast.Yield | ast.YieldFrom | ast.With | ast.AsyncWith):
            raise UnsafeCode(f"{type(node).__name__} is not allowed")
    f = next(f for f in funcs if f.name == "features")
    if len(f.args.args) != 1:
        raise UnsafeCode("`features` must take exactly one argument (the filing text)")


def load(code: str):
    """Compile validated code with restricted builtins; return the `features` callable."""
    validate(code)
    env = {"__builtins__": {**SAFE_BUILTINS, "__import__": _restricted_import}}
    exec(compile(code, "<plugin>", "exec"), env)  # noqa: S102 - validated, restricted builtins
    return env["features"]


_FNS: dict[str, object] = {}


def fn_for(code: str):
    """Compiled `features` for promoted code, cached by hash (models store code, not functions)."""
    key = plugin_id(code)
    if key not in _FNS:
        _FNS[key] = load(code)
    return _FNS[key]


def clean(out, keys: list[str] | None = None) -> dict[str, float]:
    """Coerce a plugin's output to at most MAX_FEATURES finite floats."""
    if not isinstance(out, dict):
        raise UnsafeCode("`features` must return a dict")
    vals = {}
    for k, v in out.items():
        if not isinstance(k, str) or isinstance(v, bool) or not isinstance(v, int | float):
            continue
        v = float(v)
        vals[k] = max(-1e6, min(1e6, v)) if math.isfinite(v) else 0.0
    if keys is not None:
        return {k: vals.get(k, 0.0) for k in keys}
    return dict(sorted(vals.items())[:MAX_FEATURES])


def filing_text(sections: dict | None) -> str:
    return "\n".join(v for k, v in (sections or {}).items()
                     if not k.startswith("__") and isinstance(v, str)).lower()[:TEXT_CAP]


def plugin_id(code: str) -> str:
    return "p" + hashlib.sha256(code.encode()).hexdigest()[:10]


def vector(fn, keys: list[str], sections: dict | None) -> np.ndarray:
    """In-process feature vector for serving (promoted, validated code only)."""
    try:
        out = clean(fn(filing_text(sections)), keys)
    except Exception:  # noqa: BLE001 - a failing plugin contributes nothing, never crashes
        return np.zeros(len(keys), np.float32)
    return np.array([out[k] for k in keys], np.float32)


def _sandbox(code: str, filings_root: Path, case_ids: list[str], timeout: float) -> dict:
    """Run the plugin over filings in an isolated interpreter; return {case_id: {k: v}}."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "plugin.py").write_text(code, encoding="utf-8")
        (t / "cases.json").write_text(json.dumps(case_ids), encoding="utf-8")
        env = {k: os.environ[k] for k in ("SYSTEMROOT", "PATH", "TEMP", "TMP") if k in os.environ}
        cmd = [sys.executable, "-I", "-m", "research_desk.examiner.plugin_runner",
               str(t / "plugin.py"), str(filings_root.resolve()), str(t / "cases.json"),
               str(t / "out.json")]
        try:
            p = subprocess.run(cmd, cwd=tmp, env=env, capture_output=True, text=True,
                               timeout=timeout, check=False)
        except subprocess.TimeoutExpired as e:
            raise UnsafeCode(f"timed out after {timeout:.0f}s") from e
        if p.returncode != 0 or not (t / "out.json").exists():
            raise UnsafeCode(f"sandbox run failed: {(p.stderr or p.stdout)[-400:]}")
        return json.loads((t / "out.json").read_text(encoding="utf-8"))


def extract(code: str, filings_root: Path, case_ids: list[str], out_dir: Path,
            log=print) -> tuple[str, list[str]]:
    """Validate, smoke-test, then compute features for every filing. Cached by code hash."""
    validate(code)
    pid = plugin_id(code)
    d = out_dir / pid
    if (d / "features.json").exists():
        return pid, json.loads((d / "keys.json").read_text(encoding="utf-8"))
    d.mkdir(parents=True, exist_ok=True)
    (d / "code.py").write_text(code, encoding="utf-8")
    sample = case_ids[:20]
    a = _sandbox(code, filings_root, sample, timeout=180)
    b = _sandbox(code, filings_root, sample, timeout=180)
    if a != b:
        raise UnsafeCode("features are not deterministic (two runs differ)")
    keys = sorted({k for v in a.values() for k in clean(v)})[:MAX_FEATURES]
    if not keys:
        raise UnsafeCode("features returned no numeric values on the sample")
    log(f"{pid}: smoke test passed, {len(keys)} features; running on {len(case_ids)} filings")
    full = _sandbox(code, filings_root, case_ids, timeout=2400)
    feats = {cid: [clean(v, keys)[k] for k in keys] for cid, v in full.items()}
    (d / "keys.json").write_text(json.dumps(keys), encoding="utf-8")
    (d / "features.json").write_text(json.dumps(feats), encoding="utf-8")
    return pid, keys


def cached(out_dir: Path, pid: str) -> tuple[str, list[str], dict[str, list[float]]]:
    d = out_dir / pid
    return ((d / "code.py").read_text(encoding="utf-8"),
            json.loads((d / "keys.json").read_text(encoding="utf-8")),
            json.loads((d / "features.json").read_text(encoding="utf-8")))
