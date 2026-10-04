"""Scan loaded memory for custom-VM bytecode handler prologue patterns.

    py find_bytecode.py C:\\path\\target.exe --pause-at-entry

Custom VMs rarely flip a large buffer to PAGE_EXECUTE_* at once (so `unpack_dump`
misses them). They instead jump into tables of tiny handlers glued by `mov reg,
[rip+disp]; test reg, reg; jz short`. This script searches for those prologues
once the target is paused somewhere stable (entry point by default), and prints
every address matching any of the hard-coded x64 patterns.
"""

from __future__ import annotations

from _common import base_parser, launch, run_to_entry
from x64dbg_bridge import Debugger

PATTERNS = [
    "48 8B 05 ?? ?? ?? ?? 48 85 C0 74 ?? 48 8B C8",  # mov rax,[rip+disp32]; test rax,rax; jz short
    "48 8B 0D ?? ?? ?? ?? 48 85 C9 74 ?? 48 8B C1",  # mov rcx,[rip+disp32]; test rcx,rcx; jz short
    "48 8B 15 ?? ?? ?? ?? 48 85 D2 74 ??",            # mov rdx,[rip+disp32]; test rdx,rdx; jz short
]


def find_pattern(dbg: Debugger, pattern: str) -> list[int]:
    dbg.cmd(f'findallmem 0, "{pattern}"')
    count = dbg.eval("ref.count()")
    hits: list[int] = []
    for i in range(count):
        hits.append(dbg.eval(f"ref.addr({i})"))
    return hits


def main() -> int:
    parser = base_parser(__doc__)
    parser.add_argument("target")
    parser.add_argument("--pause-at-entry", action="store_true", help="run to the EP before scanning")
    args = parser.parse_args()

    with launch(args) as dbg:
        if args.pause_at_entry:
            run_to_entry(dbg, args.target)
        else:
            dbg.init(args.target)

        for pattern in PATTERNS:
            hits = find_pattern(dbg, pattern)
            print(f"[bytecode] pattern {pattern!r}: {len(hits)} hit(s)")
            for addr in hits[:20]:
                print(f"           {addr:#x}")
            if len(hits) > 20:
                print(f"           ... ({len(hits) - 20} more)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
