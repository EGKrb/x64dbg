"""Dump a memory region of a process to a file.

    py dump_memory.py --target C:\\path\\target.exe --addr "mod.base(target.exe)" --size "mod.size(target.exe)" --out target.bin
    py dump_memory.py --pid 1234 --addr 7FF6A0000000 --size 1000 --out region.bin

--addr, --size and --at are x64dbg expressions (numbers are hexadecimal).
"""

from __future__ import annotations

from pathlib import Path

from _common import base_parser, launch, run_to_entry

CHUNK = 0x10000


def main() -> int:
    parser = base_parser(__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--target", help="executable to start")
    source.add_argument("--pid", type=int, help="process id to attach to (decimal)")
    parser.add_argument("--at", help="run until this address/expression before dumping (breakpoint)")
    parser.add_argument("--addr", required=True)
    parser.add_argument("--size", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with launch(args) as dbg:
        if args.target:
            run_to_entry(dbg, args.target)
        else:
            dbg.attach(args.pid)
        if args.at:
            dbg.set_breakpoint(args.at, singleshot=True)
            if not dbg.run(wait=True, timeout=120):
                raise SystemExit(f"{args.at} was not reached")

        address = dbg.eval(args.addr)
        size = dbg.eval(args.size)
        unreadable = 0
        with open(args.out, "wb") as f:
            for offset in range(0, size, CHUNK):
                length = min(CHUNK, size - offset)
                try:
                    f.write(dbg.read(address + offset, length))
                except Exception:
                    # Keep offsets intact: fill unreadable chunks with zeros
                    f.write(b"\0" * length)
                    unreadable += length
        print(f"dumped 0x{size:X} bytes from 0x{address:X} to {Path(args.out).resolve()}")
        if unreadable:
            print(f"warning: 0x{unreadable:X} unreadable bytes were filled with zeros")
        if args.pid:
            dbg.cmd("detach", check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
