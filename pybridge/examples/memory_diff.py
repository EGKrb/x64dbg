"""Snapshot a memory range before and after a delay, then diff the two.

    py memory_diff.py C:\\path\\target.exe --addr "mod.base(target.exe)" --size 0x200000 --delay 10
    py memory_diff.py --pid 1234 --addr "0x7FF600000000" --size 0x100000 --delay 5 --out diff.bin

Useful to find where a packer/decryptor materializes its payload: snapshot the
module (or the whole process heap) before and after the unpacker runs, and the
diff pinpoints the exact bytes that changed. Output: a human-readable summary
plus optional before/after/diff dumps.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from _common import base_parser, launch
from x64dbg_bridge import BridgeError


def runs(diff: bytes, chunk_size: int = 16):
    """Yield (start, length) of contiguous non-zero runs in diff (chunked)."""
    i = 0
    n = len(diff)
    while i < n:
        if diff[i]:
            j = i
            while j < n and diff[j]:
                j += 1
            yield i, j - i
            i = j
        else:
            i += 1


def main() -> int:
    parser = base_parser(__doc__)
    parser.add_argument("target", nargs="?", help="target .exe (omit if using --pid)")
    parser.add_argument("--pid", type=int, help="attach to an already-running PID instead of init")
    parser.add_argument("--addr", required=True, help="start address (int or x64dbg expression)")
    parser.add_argument("--size", type=lambda s: int(s, 0), required=True, help="bytes to snapshot (e.g. 0x100000)")
    parser.add_argument("--delay", type=float, default=10.0, help="seconds between the two snapshots (default 10)")
    parser.add_argument("--out", default="diff", help="prefix for before.bin / after.bin / diff.bin")
    args = parser.parse_args()
    if not args.target and not args.pid:
        parser.error("give a target .exe path or --pid")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with launch(args) as dbg:
        if args.pid:
            dbg.attach(args.pid)
        else:
            dbg.init(args.target)
        address = dbg.eval(args.addr) if isinstance(args.addr, str) else args.addr

        print(f"[diff] before snapshot: 0x{address:X} +{args.size:#x}")
        before = dbg.read(address, args.size)
        Path(f"{out}.before.bin").write_bytes(before)

        print(f"[diff] running for {args.delay:.1f}s...")
        dbg.run(wait=False)
        time.sleep(args.delay)
        dbg.pause()

        print(f"[diff] after snapshot: 0x{address:X} +{args.size:#x}")
        after = dbg.read(address, args.size)
        Path(f"{out}.after.bin").write_bytes(after)

        if len(before) != len(after):
            print(f"[diff] WARNING: length changed ({len(before)} -> {len(after)}), truncating to min")
        n = min(len(before), len(after))
        diff = bytes(a ^ b for a, b in zip(before[:n], after[:n]))
        changed = sum(1 for b in diff if b)
        Path(f"{out}.diff.bin").write_bytes(diff)

        print(f"[diff] {changed} / {n} bytes changed ({100 * changed / max(n, 1):.2f}%)")
        hits = list(runs(diff))
        print(f"[diff] {len(hits)} contiguous changed region(s); first 20:")
        for start, length in hits[:20]:
            print(f"    0x{address + start:X} .. +{length:#x}")
        if len(hits) > 20:
            print(f"    ... (+ {len(hits) - 20} more; full XOR delta in {out}.diff.bin)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
