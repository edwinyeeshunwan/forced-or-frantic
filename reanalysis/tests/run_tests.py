"""Minimal test runner (works without pytest; `pytest` also discovers these files)."""
import importlib
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))


def main(report=None):
    mods = sorted(p.stem for p in HERE.glob("test_*.py"))
    results = []
    for m in mods:
        mod = importlib.import_module(m)
        for name in sorted(n for n in dir(mod) if n.startswith("test_")):
            t = time.time()
            try:
                getattr(mod, name)()
                results.append((m, name, "PASS", time.time() - t, ""))
            except Exception:  # noqa: BLE001
                results.append((m, name, "FAIL", time.time() - t, traceback.format_exc()))
    lines = [f"{s}  {m}::{n}  ({dt:.1f}s)" + (f"\n{tb}" if tb else "") for m, n, s, dt, tb in results]
    n_fail = sum(r[2] == "FAIL" for r in results)
    lines.append(f"\n{len(results) - n_fail} passed, {n_fail} failed")
    text = "\n".join(lines)
    print(text)
    if report:
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        Path(report).write_text(text + "\n")
    return n_fail


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1] if len(sys.argv) > 1 else None) else 0)
