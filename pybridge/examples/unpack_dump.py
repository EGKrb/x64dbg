"""Dump a memory region each time it is flipped to an executable protection.

Breaks on `kernelbase.VirtualProtect`, filters hits where the new protection
contains any PAGE_EXECUTE* flag (0x10 / 0x20 / 0x40 / 0x80), then dumps the
`[lpAddress, lpAddress + dwSize)` range to a timestamped file in --out-dir.
Typical use: catch the moment a packer makes a decrypted buffer runnable.

    py unpack_dump.py C:\\samples\\packed.exe --out-dir .\\dumps --max-hits 10
    py unpack_dump.py C:\\samples\\packed.exe --api kernelbase.VirtualProtectEx

Addresses in the file name are the lpAddress reported by the hit.
"""

from __future__ import annotations

import time
from pathlib import Path

from _common import arg_register, base_parser, launch, run_to_entry

PAGE_EXECUTE_MASK = 0xF0  # covers PAGE_EXECUTE, _READ, _READWRITE, _WRITECOPY
DEFAULT_API = "kernelbase.VirtualProtect"


def protect_name(flags: int) -> str:
    names = {0x10: "EXECUTE", 0x20: "EXECUTE_READ", 0x40: "EXECUTE_READWRITE", 0x80: "EXECUTE_WRITECOPY"}
    base = names.get(flags & 0xF0, f"0x{flags & 0xF0:X}")
    extra = []
    if flags & 0x100:
        extra.append("GUARD")
    if flags & 0x200:
        extra.append("NOCACHE")
    if flags & 0x400:
        extra.append("WRITECOMBINE")
    return "|".join([base, *extra])


def main() -> int:
    parser = base_parser(__doc__)
    parser.add_argument("target")
    parser.add_argument("--out-dir", default="dumps")
    parser.add_argument("--api", default=DEFAULT_API, help=f"API to break on (default: {DEFAULT_API})")
    parser.add_argument("--max-hits", type=int, default=20, help="stop after this many executable transitions")
    parser.add_argument("--min-size", type=int, default=0x100, help="skip regions smaller than this many bytes")
    parser.add_argument("--timeout", type=float, default=120.0, help="give up if no hit for this many seconds")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    with launch(args) as dbg:
        run_to_entry(dbg, args.target)

        # arg.get(N) matches the Windows calling convention regardless of arch.
        condition = "(arg.get(2) & 0x%X) != 0" % PAGE_EXECUTE_MASK
        dbg.set_breakpoint(args.api, condition=condition, break_=True)
        api_addr = dbg.eval(args.api)
        print(f"watching {args.api} @ 0x{api_addr:X} (filter: new protect has PAGE_EXECUTE*)")

        addr_reg = arg_register(dbg, 0)
        size_reg = arg_register(dbg, 1)
        prot_reg = arg_register(dbg, 2)

        hits = 0
        dbg.run()
        deadline = time.monotonic() + args.timeout
        while hits < args.max_hits and time.monotonic() < deadline:
            if not dbg.wait(timeout=min(5.0, deadline - time.monotonic())):
                continue
            state = dbg.state()
            if not state["debugging"]:
                print("target exited")
                break
            if state["running"]:
                continue  # paused for another reason, keep polling
            if state["cip"] != api_addr:
                # paused on something else (exception, DLL load…): resume
                dbg.run(pass_exceptions=True)
                continue

            # arg_register returns "rcx"/"rdx"/... on x64 and "[esp+N]" on x32 —
            # eval handles both: a register name or a dereferenceable expression.
            lp_address = dbg.eval(addr_reg)
            dw_size = dbg.eval(size_reg)
            protect = dbg.eval(prot_reg)

            if dw_size < args.min_size:
                print(f"skip hit#{hits + 1}: size 0x{dw_size:X} < min 0x{args.min_size:X}")
                dbg.run()
                continue

            hits += 1
            stamp = time.strftime("%H%M%S")
            name = f"vprotect-{stamp}-{lp_address:016X}-{dw_size:X}-{protect_name(protect)}.bin"
            out = out_dir / name
            written = dbg.dump_memory(lp_address, dw_size, out)
            print(f"[{hits}/{args.max_hits}] {args.api}(0x{lp_address:X}, 0x{dw_size:X}, "
                  f"{protect_name(protect)}) -> {out.name} ({written} bytes)")
            dbg.run()
            deadline = time.monotonic() + args.timeout
        else:
            if hits >= args.max_hits:
                print(f"max-hits reached ({args.max_hits})")
            else:
                print(f"timeout after {args.timeout:.0f}s with {hits} dump(s)")
        print(f"done, {hits} region(s) dumped to {out_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
