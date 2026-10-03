"""Log Windows API calls made by a program, without pausing it.

    py api_monitor.py C:\\path\\target.exe --timeout 30
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from _common import arg_register, base_parser, launch, run_to_entry
from x64dbg_bridge import BridgeError

# API -> list of (argument index, format type) to print
APIS = {
    "kernelbase.CreateFileW": [(0, "utf16")],
    "kernelbase.DeleteFileW": [(0, "utf16")],
    "kernelbase.CreateProcessW": [(0, "utf16"), (1, "utf16")],
    "kernelbase.LoadLibraryW": [(0, "utf16")],
    "kernelbase.LoadLibraryExW": [(0, "utf16")],
    "kernelbase.VirtualAlloc": [(0, "p"), (1, "x"), (3, "x")],
    "kernelbase.VirtualProtect": [(0, "p"), (1, "x"), (2, "x")],
    "kernelbase.WriteProcessMemory": [(1, "p"), (3, "x")],
}
MARKER = "[api]"


def log_text(dbg, api: str, arguments: list[tuple[int, str]]) -> str:
    parts = []
    for index, kind in arguments:
        register = arg_register(dbg, index)
        parts.append(f"{{{kind}@{register}}}" if kind in ("utf16", "utf8", "ascii") else f"{{{kind}:{register}}}")
    return f"{MARKER} {api.split('.')[-1]}({', '.join(parts)}) from {{a:[csp]}}"


def main() -> int:
    parser = base_parser(__doc__)
    parser.add_argument("target")
    parser.add_argument("--timeout", type=float, default=60.0, help="stop the target after this many seconds")
    args = parser.parse_args()
    args.log = args.log or str(Path(tempfile.gettempdir()) / "x64dbg_api_monitor.log")

    with launch(args) as dbg:
        run_to_entry(dbg, args.target)
        for api, arguments in APIS.items():
            try:
                dbg.set_breakpoint(api, break_=False, log=log_text(dbg, api, arguments))
            except BridgeError as exc:
                print(f"skipped {api}: {exc}")

        dbg.run()
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            state = dbg.state()
            if not state["debugging"]:
                break
            if not state["running"]:
                dbg.run(pass_exceptions=True)  # paused by an exception: let the program handle it
            time.sleep(0.2)
        else:
            print("timeout, stopping the target")

    for line in Path(args.log).read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(MARKER):
            print(line[len(MARKER):].strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
