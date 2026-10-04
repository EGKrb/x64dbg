"""Pass-through common anti-debug exceptions (int3, int2d, privileged instructions).

    py exception_handler.py C:\\path\\target.exe --timeout 30

Protectors raise `int3` / `int2d` / `cli` and watch the SEH chain to see if a
debugger swallowed them. This script sets x64dbg's exception filter to
"pass to debuggee, do not pause" for the usual suspects:

    0xC0000005  STATUS_ACCESS_VIOLATION       (optional, often triggers probes)
    0xC000001D  STATUS_ILLEGAL_INSTRUCTION
    0xC0000035  STATUS_BREAKPOINT             (int3)
    0xC0000096  STATUS_PRIVILEGED_INSTRUCTION (cli, rdmsr, ...)
    0x4000001F  STATUS_WX86_BREAKPOINT        (WOW64 int3)
"""

from __future__ import annotations

import time

from _common import base_parser, launch
from x64dbg_bridge import Debugger

# code, label, pass-through?
FILTERS = [
    (0xC000001D, "STATUS_ILLEGAL_INSTRUCTION",     True),
    (0xC0000035, "STATUS_BREAKPOINT",              True),
    (0xC0000096, "STATUS_PRIVILEGED_INSTRUCTION",  True),
    (0x4000001F, "STATUS_WX86_BREAKPOINT",         True),
]


def install_filters(dbg: Debugger) -> None:
    for code, label, passthrough in FILTERS:
        # SetExceptionBreakOnFirstChance <code>, 0 (do not break)
        dbg.cmd(f"SetExceptionBreakOnFirstChance {code:#x}, 0")
        dbg.cmd(f"SetExceptionBreakOnSecondChance {code:#x}, 0")
        if passthrough:
            # Hand it to the debuggee's own SEH handler
            dbg.cmd(f"SetExceptionHandledBy {code:#x}, 1")
        print(f"[exc] {label} ({code:#x}): pause=no, pass-through={passthrough}")


def main() -> int:
    parser = base_parser(__doc__)
    parser.add_argument("target")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    with launch(args) as dbg:
        dbg.init(args.target)
        dbg.hide_debugger()
        install_filters(dbg)

        deadline = time.monotonic() + args.timeout
        print(f"[exc] running for up to {args.timeout:.0f}s (exceptions pass through)...")
        while time.monotonic() < deadline and dbg.state()["debugging"]:
            if dbg.state()["running"]:
                time.sleep(0.2)
                continue
            if not dbg.run(wait=True, timeout=1.0, pass_exceptions=True):
                time.sleep(0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
