"""Sandbox entry point: runs one generated plugin over cached filings, in its own interpreter.

    python -I -m research_desk.examiner.plugin_runner plugin.py filings_root cases.json out.json

This trusted harness reads the filings and writes the output; the plugin itself only receives a
string and returns a dict, with restricted builtins (see plugins.load). A plugin exception on
one filing yields empty features for that filing rather than aborting the run.
"""
import json
import math
import sys
from pathlib import Path

from .filings import load as load_sections
from .plugins import filing_text, load


def main() -> None:
    plugin, root, cases, out = sys.argv[1:5]
    fn = load(Path(plugin).read_text(encoding="utf-8"))
    result = {}
    for cid in json.loads(Path(cases).read_text(encoding="utf-8")):
        try:
            v = fn(filing_text(load_sections(Path(root), cid)))
        except Exception:  # noqa: BLE001 - a bad filing must not kill the run
            v = {}
        # keep only finite numbers; the parent picks the feature keys and clips values
        result[cid] = {k: float(x) for k, x in (v.items() if isinstance(v, dict) else ())
                       if isinstance(k, str) and isinstance(x, int | float)
                       and not isinstance(x, bool) and math.isfinite(x)}
    Path(out).write_text(json.dumps(result, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
