from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the files written by the TraceExport command.")
    parser.add_argument("--log", required=True)
    parser.add_argument("--userdir", required=True)
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--artifacts-dir", required=True)
    return parser.parse_args()


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def main() -> int:
    args = parse_args()
    runtime_dir = Path(args.runtime_dir)

    try:
        document = json.loads((runtime_dir / "trace.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return fail(f"trace.json is not valid JSON: {exc}")

    instructions = document.get("instructions")
    if not instructions:
        return fail("trace.json has no instructions")
    ip = "rip" if document.get("arch") == "x64" else "eip"
    for expected_index, instruction in enumerate(instructions):
        if instruction.get("index") != expected_index:
            return fail(f"unexpected index at position {expected_index}")
        if not instruction.get("disasm") or not instruction.get("bytes"):
            return fail(f"instruction {expected_index} has no disassembly")
        if instruction["regs"].get(ip) != instruction["address"]:
            return fail(f"instruction {expected_index}: {ip} does not match address")

    with open(runtime_dir / "trace.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != len(instructions):
        return fail(f"csv has {len(rows)} rows, json has {len(instructions)} instructions")
    for row, instruction in zip(rows, instructions):
        if row["address"] != instruction["address"] or row["disasm"] != instruction["disasm"]:
            return fail(f"csv row {row['index']} does not match json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
