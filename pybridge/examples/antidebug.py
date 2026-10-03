"""Run a target with the debugger masked and the API probes logged.

    py antidebug.py C:\\path\\target.exe --timeout 30
    py antidebug.py C:\\path\\target.exe --scyllahide-ini "C:\\...\\scylla_hide.ini" --profile Basic

The PEB is patched via x64dbg's built-in `hide` command (BeingDebugged = 0,
NtGlobalFlag &= ~0x70, heap flags normalized). With --scyllahide-ini, the
ScyllaHide plugin's current profile is set before launch -- the plugin itself
must be present in the x64dbg `plugins` folder (download from the ScyllaHide
release, then put HookLibrary*.dll + scylla_hide.ini + the .dp* plugin in place).
"""

from __future__ import annotations

import time
from pathlib import Path

from _common import base_parser, launch
from x64dbg_bridge import BridgeError, Debugger

# Common anti-debug probe APIs: logged, never paused on
PROBES = [
    "kernelbase.IsDebuggerPresent",
    "kernelbase.CheckRemoteDebuggerPresent",
    "ntdll.NtQueryInformationProcess",
    "kernelbase.OutputDebugStringA",
    "kernelbase.OutputDebugStringW",
    "kernelbase.GetTickCount",
    "ntdll.NtClose",
]


def main() -> int:
    parser = base_parser(__doc__)
    parser.add_argument("target")
    parser.add_argument("--timeout", type=float, default=60.0, help="let the target run this long before stopping it")
    parser.add_argument("--scyllahide-ini", help="path to ScyllaHide's scylla_hide.ini")
    parser.add_argument("--profile", default="Basic", help="ScyllaHide profile to activate (requires --scyllahide-ini)")
    parser.add_argument("--list-profiles", action="store_true", help="print profiles from --scyllahide-ini and exit")
    args = parser.parse_args()

    if args.list_profiles:
        if not args.scyllahide_ini:
            parser.error("--list-profiles requires --scyllahide-ini")
        for p in Debugger.scyllahide_profiles(args.scyllahide_ini):
            print(p)
        return 0

    if args.scyllahide_ini:
        Debugger.scyllahide_set_profile(args.scyllahide_ini, args.profile)
        print(f"[antidebug] ScyllaHide profile set to {args.profile!r}")

    with launch(args) as dbg:
        dbg.init(args.target)
        dbg.hide_debugger()
        print(f"[antidebug] PEB patched; arch={dbg.arch}")

        for api in PROBES:
            try:
                dbg.hook_api(api, log=f"[antidebug] {api.split('.')[-1]} #{{d:$breakpointcounter}} from {{a:[csp]}}")
            except BridgeError as exc:
                print(f"[antidebug] skip {api}: {exc}")

        deadline = time.monotonic() + args.timeout
        print(f"[antidebug] running for up to {args.timeout:.0f}s...")
        while time.monotonic() < deadline and dbg.state()["debugging"]:
            if dbg.state()["running"]:
                time.sleep(0.2)
                continue
            # Paused (unexpected breakpoint, exception, ...): resume
            if not dbg.run(wait=True, timeout=1.0):
                time.sleep(0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
