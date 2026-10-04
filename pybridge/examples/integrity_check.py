"""Snapshot a module's text section hash before and after a run to catch runtime patches.

    py integrity_check.py C:\\path\\target.exe --timeout 30

The target is paused at its entry point, the main module's full range (base ->
base+size) is read and SHA-256'd, then the target runs for --timeout seconds
and the hash is recomputed from a fresh read. A different hash means the module
patched itself at runtime -- typical of self-decrypting or self-modifying code.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from _common import base_parser, launch, run_to_entry
from x64dbg_bridge import Debugger


def hash_module(dbg: Debugger, module: str) -> tuple[str, int, int]:
    base = dbg.eval(f"mod.base({module})")
    size = dbg.eval(f"mod.size({module})")
    data = dbg.read(base, size)
    return hashlib.sha256(data).hexdigest(), base, size


def main() -> int:
    parser = base_parser(__doc__)
    parser.add_argument("target")
    parser.add_argument("--timeout", type=float, default=30.0, help="let the target run this long between snapshots")
    args = parser.parse_args()

    module = Path(args.target).name
    with launch(args) as dbg:
        run_to_entry(dbg, args.target)

        h0, base, size = hash_module(dbg, module)
        print(f"[integrity] {module} @ {base:#x} ({size} bytes)")
        print(f"[integrity]   entry sha256: {h0}")

        print(f"[integrity] running for {args.timeout:.0f}s before second snapshot...")
        deadline = time.monotonic() + args.timeout
        dbg.run()
        while time.monotonic() < deadline and dbg.state()["debugging"]:
            time.sleep(0.2)
        dbg.pause()

        h1, _, _ = hash_module(dbg, module)
        print(f"[integrity]   runtime sha256: {h1}")
        print(f"[integrity]   {'UNCHANGED' if h0 == h1 else 'MODIFIED AT RUNTIME'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
