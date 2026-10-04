"""Analyze the PE sections of a running target and dump the high-entropy ones.

    py pe_entropy.py C:\\path\\target.exe --threshold 7.5 --out out

Entropy is a byte-level Shannon measure in [0, 8]. A section above ~7.5 is
usually compressed/encrypted (packer sections, .rsrc with embedded payload,
...). Each flagged section is dumped as a .bin file for offline analysis.

The parsing is minimal (pure stdlib), so no `pefile` dependency.
"""

from __future__ import annotations

import math
import struct
from collections import Counter
from pathlib import Path

from _common import base_parser, launch, run_to_entry
from x64dbg_bridge import BridgeError, Debugger


def shannon_entropy(data: bytes) -> float:
    """Byte-level Shannon entropy in [0, 8]. 0 = uniform, 8 = fully random."""
    if not data:
        return 0.0
    n = len(data)
    counts = Counter(data).values()
    return -sum((c / n) * math.log2(c / n) for c in counts)


def parse_sections(headers: bytes, image_base: int) -> list[dict]:
    """Return a list of {name, va, raw_size, virtual_size, characteristics}."""
    # DOS header -> PE offset
    e_lfanew = struct.unpack_from("<I", headers, 0x3C)[0]
    # PE signature + COFF header
    if headers[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        raise ValueError("not a PE image at the given base")
    num_sections = struct.unpack_from("<H", headers, e_lfanew + 6)[0]
    opt_header_size = struct.unpack_from("<H", headers, e_lfanew + 20)[0]
    sections_offset = e_lfanew + 24 + opt_header_size

    sections = []
    for i in range(num_sections):
        off = sections_offset + i * 40
        name = headers[off:off + 8].rstrip(b"\0").decode("latin-1", errors="replace")
        virtual_size = struct.unpack_from("<I", headers, off + 8)[0]
        virtual_addr = struct.unpack_from("<I", headers, off + 12)[0]
        raw_size = struct.unpack_from("<I", headers, off + 16)[0]
        characteristics = struct.unpack_from("<I", headers, off + 36)[0]
        sections.append({
            "name": name,
            "va": image_base + virtual_addr,
            "raw_size": raw_size,
            "virtual_size": virtual_size,
            "characteristics": characteristics,
        })
    return sections


def main() -> int:
    parser = base_parser(__doc__)
    parser.add_argument("target")
    parser.add_argument("--threshold", type=float, default=7.5, help="entropy threshold to flag a section (default 7.5)")
    parser.add_argument("--out", default="out", help="directory for the dumped sections")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with launch(args) as dbg:
        run_to_entry(dbg, args.target)
        module = Path(args.target).name
        base = dbg.eval(f"mod.base({module})")
        size = dbg.eval(f"mod.size({module})")
        if not base:
            raise BridgeError(f"cannot resolve the base of {module}")
        print(f"[pe] module {module} base=0x{base:X} size=0x{size:X}")

        # First page is enough to cover DOS + PE + section table on nearly all binaries
        headers = dbg.read(base, min(0x1000, size))
        sections = parse_sections(headers, base)
        suspicious = []
        for s in sections:
            take = min(s["virtual_size"] or s["raw_size"], 0x200000)  # cap at 2 MB per section
            if not take:
                print(f"[pe] {s['name']:<10} 0x{s['va']:X}  size=0  SKIP (empty)")
                continue
            try:
                data = dbg.read(s["va"], take)
            except BridgeError as exc:
                print(f"[pe] {s['name']:<10} 0x{s['va']:X}  unreadable: {exc}")
                continue
            e = shannon_entropy(data)
            marker = "  <-- HIGH ENTROPY" if e >= args.threshold else ""
            print(f"[pe] {s['name']:<10} 0x{s['va']:X}  size={len(data):>8}  entropy={e:5.3f}{marker}")
            if e >= args.threshold:
                safe_name = s["name"] or f"anon_{s['va']:X}"
                dst = out / f"section_{safe_name}.bin"
                dst.write_bytes(data)
                suspicious.append((s["name"], dst))

        if suspicious:
            print(f"\n[pe] {len(suspicious)} high-entropy section(s) dumped to {out}:")
            for name, dst in suspicious:
                print(f"    {dst}  ({name})")
        else:
            print(f"\n[pe] no section above entropy {args.threshold}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
