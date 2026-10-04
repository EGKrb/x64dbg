"""Flatten GetTickCount / RtlGetTickCount return values to defeat timing-based anti-debug.

    py rdtsc_hook.py C:\\path\\target.exe --timeout 30

Many protectors sample `GetTickCount` (or its ntdll equivalent) before and after
a potentially-stolen region, then bail out if the delta is too large. This script
installs non-breaking breakpoints on those APIs that force the return value in
eax/edx back to 0 and return immediately. Combine with `antidebug.py` for the
PEB + ScyllaHide side.
"""

from __future__ import annotations

import time

from _common import base_parser, launch
from x64dbg_bridge import BridgeError, Debugger

APIS = [
    "kernelbase.GetTickCount",
    "kernelbase.GetTickCount64",
    "ntdll.RtlGetTickCount",
    "ntdll.NtQueryPerformanceCounter",
]


def install_rdtsc_hooks(dbg: Debugger) -> None:
    for api in APIS:
        try:
            addr = dbg.eval(api)
        except BridgeError as exc:
            print(f"[rdtsc] skip {api}: {exc}")
            continue
        dbg.set_breakpoint(
            addr,
            command="mov eax,0; mov edx,0; ret",
            log=f"[rdtsc] {api.split('.')[-1]} zeroed",
            break_=False,
        )
        print(f"[rdtsc] hooked {api} @ {addr:#x}")


def main() -> int:
    parser = base_parser(__doc__)
    parser.add_argument("target")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    with launch(args) as dbg:
        dbg.init(args.target)
        dbg.hide_debugger()
        install_rdtsc_hooks(dbg)

        deadline = time.monotonic() + args.timeout
        print(f"[rdtsc] running for up to {args.timeout:.0f}s...")
        while time.monotonic() < deadline and dbg.state()["debugging"]:
            if dbg.state()["running"]:
                time.sleep(0.2)
                continue
            if not dbg.run(wait=True, timeout=1.0):
                time.sleep(0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
