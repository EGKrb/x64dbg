"""Record an execution trace from the entry point and export it to JSON and CSV.

Needs an x64dbg build with the TraceExport command.

    py trace_to_json.py C:\\path\\target.exe --steps 20000 --out C:\\traces
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

from _common import base_parser, launch, run_to_entry


def main() -> int:
    parser = base_parser(__doc__)
    parser.add_argument("target")
    parser.add_argument("--steps", type=int, default=10000, help="maximum number of traced instructions")
    parser.add_argument("--start", help="expression where tracing starts (default: entry point)")
    parser.add_argument("--stop", default="0", help="x64dbg condition that ends the trace, e.g. \"cip == kernel32.ExitProcess\"")
    parser.add_argument("--step-over", action="store_true", help="do not trace into calls")
    parser.add_argument("--out", default=".", help="output folder")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    trace_file = out / f"trace.trace{'64' if args.arch == 'x64' else '32'}"
    trace_file.unlink(missing_ok=True)  # recording appends to an existing file

    with launch(args) as dbg:
        run_to_entry(dbg, args.target)
        if args.start:
            dbg.set_breakpoint(args.start, singleshot=True)
            if not dbg.run(wait=True, timeout=60):
                raise SystemExit(f"{args.start} was not reached")

        traced = dbg.trace(trace_file, condition=args.stop, max_steps=args.steps, step_over=args.step_over)
        print(f"traced {traced} instructions")
        count = dbg.export_trace(trace_file, out / "trace.json")
        dbg.export_trace(trace_file, out / "trace.csv")
        print(f"exported {count} instructions to {out / 'trace.json'} and {out / 'trace.csv'}")

    instructions = json.loads((out / "trace.json").read_text(encoding="utf-8"))["instructions"]
    hits = collections.Counter((i["address"], i["disasm"]) for i in instructions)
    modules = collections.Counter(i.get("module", "?") for i in instructions)
    writes = sum(1 for i in instructions for m in i["mem"] if m["old"] != m["new"])
    print("\ninstructions per module:")
    for module, n in modules.most_common():
        print(f"  {n:8}  {module}")
    print(f"\nmemory writes: {writes}")
    print("\nmost executed instructions:")
    for (address, disasm), n in hits.most_common(10):
        print(f"  {n:8}  {address:>18}  {disasm}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
