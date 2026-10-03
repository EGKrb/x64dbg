"""Single-step a program and print every instruction with the registers it changed.

    py step_log.py C:\\path\\target.exe --count 50
"""

from __future__ import annotations

from _common import base_parser, launch, run_to_entry


def main() -> int:
    parser = base_parser(__doc__)
    parser.add_argument("target")
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--over", action="store_true", help="step over calls")
    args = parser.parse_args()

    with launch(args) as dbg:
        run_to_entry(dbg, args.target)
        regs = dbg.regs()
        ip = "rip" if dbg.arch == "x64" else "eip"
        for _ in range(args.count):
            instruction = dbg.disasm(regs[ip])[0]
            if not (dbg.step_over() if args.over else dbg.step_into()):
                print("the program is no longer paused (exited?)")
                break
            new_regs = dbg.regs()
            changes = ", ".join(f"{name}={value:X}" for name, value in new_regs.items() if value != regs[name] and name != ip)
            print(f"{instruction['address']:016X}  {instruction['text']:<40}  {changes}")
            regs = new_regs
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
