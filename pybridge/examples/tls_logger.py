"""List TLS callbacks of the main module and log each hit.

    py tls_logger.py C:\\path\\target.exe --timeout 30

Many protectors run their first anti-debug checks from TLS callbacks (before
`main`). This script enumerates them via x64dbg's `tlscallback` built-in and
installs a non-breaking logging breakpoint on each one, so the stream of hits
shows up in the x64dbg log as the target starts.
"""

from __future__ import annotations

import time
from pathlib import Path

from _common import base_parser, launch
from x64dbg_bridge import BridgeError, Debugger


def list_tls_callbacks(dbg: Debugger, module: str) -> list[int]:
    """Read TLS callbacks for `module` using mod.tlscallbackcount / mod.tlscallback(i)."""
    try:
        count = dbg.eval(f"mod.tlscallbackcount({module})")
    except BridgeError as exc:
        print(f"[tls] mod.tlscallbackcount failed: {exc}")
        return []
    return [dbg.eval(f"mod.tlscallback({module}, {i})") for i in range(count)]


def main() -> int:
    parser = base_parser(__doc__)
    parser.add_argument("target")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    module = Path(args.target).name
    with launch(args) as dbg:
        dbg.init(args.target)
        callbacks = list_tls_callbacks(dbg, module)
        print(f"[tls] {module}: {len(callbacks)} TLS callback(s)")
        for cb in callbacks:
            print(f"[tls]   {cb:#x}")
            dbg.set_breakpoint(cb, log=f"[tls] callback {cb:#x} hit (cip={{a:cip}})", break_=False)

        deadline = time.monotonic() + args.timeout
        print(f"[tls] running for up to {args.timeout:.0f}s...")
        while time.monotonic() < deadline and dbg.state()["debugging"]:
            if dbg.state()["running"]:
                time.sleep(0.2)
                continue
            if not dbg.run(wait=True, timeout=1.0):
                time.sleep(0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
