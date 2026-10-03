"""Shared setup for the examples: import path and default x64dbg location."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from x64dbg_bridge import BridgeError, Debugger  # noqa: E402

# x64dbg "release" folder (contains x64\ and x32\). Override with --x64dbg or X64DBG_DIR.
DEFAULT_X64DBG_DIR = os.environ.get(
    "X64DBG_DIR",
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages/x64dbg.x64dbg_Microsoft.Winget.Source_8wekyb3d8bbwe/release"),
)


def base_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--x64dbg", default=DEFAULT_X64DBG_DIR, help="x64dbg release folder (default: %(default)s)")
    parser.add_argument("--arch", choices=("x64", "x32"), default="x64")
    parser.add_argument("--gui", action="store_true", help="use x64dbg.exe instead of headless.exe")
    parser.add_argument("--port", type=int, default=27041)
    parser.add_argument("--log", help="write the x64dbg log to this file")
    return parser


def launch(args: argparse.Namespace) -> Debugger:
    return Debugger.launch(args.x64dbg, arch=args.arch, gui=args.gui, port=args.port, log_file=args.log)


def run_to_entry(dbg: Debugger, target: str) -> int:
    """Start the target and pause at its entry point. Returns the entry address."""
    dbg.init(target)
    module = Path(target).name
    entry = dbg.eval(f"mod.entry({module})")
    if dbg.state()["cip"] != entry:
        try:
            dbg.set_breakpoint(entry, singleshot=True)
        except BridgeError:
            pass  # x64dbg already has its own entry breakpoint
        if not dbg.run(wait=True, timeout=30):
            raise RuntimeError("the target did not reach its entry point")
    return entry


def arg_register(dbg: Debugger, index: int) -> str:
    """Expression for the index-th integer argument at a function entry (Windows calling conventions)."""
    if dbg.arch == "x64":
        return ("rcx", "rdx", "r8", "r9")[index] if index < 4 else f"[rsp+{(index + 1) * 8:X}]"
    return f"[esp+{(index + 1) * 4:X}]"
