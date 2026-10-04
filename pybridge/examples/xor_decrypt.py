"""XOR-decrypt (or XOR-brute-force) a memory range from the debuggee.

Three modes:

    # 1) Known single-byte key
    py xor_decrypt.py C:\\path\\target.exe --addr "0x108F0000" --size 0x1000 --key 0x42 --out plain.bin

    # 2) Multi-byte key (repeated)
    py xor_decrypt.py --pid 1234 --addr "mod.base(target.exe)+0x1000" --size 0x400 --key AABBCCDD --out plain.bin

    # 3) Single-byte key brute force (prints the top candidates ranked by text-likeness)
    py xor_decrypt.py C:\\path\\target.exe --addr "0x108F0000" --size 0x200 --brute

Writes the decrypted bytes to --out when a key is known; in --brute mode just
prints a ranked table. The ciphertext is read live from the debuggee via
pybridge, so you can set a breakpoint before, let the code decrypt its tables,
and then peek at them without actually running the decrypt routine yourself.
"""

from __future__ import annotations

from itertools import cycle
from pathlib import Path

from _common import base_parser, launch
from x64dbg_bridge import BridgeError


def xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ k for b, k in zip(data, cycle(key)))


def printable_score(data: bytes) -> float:
    """Fraction of bytes in printable ASCII range [0x20..0x7E] + \\t\\n\\r."""
    if not data:
        return 0.0
    good = sum(1 for b in data if 0x20 <= b <= 0x7E or b in (9, 10, 13))
    return good / len(data)


def main() -> int:
    parser = base_parser(__doc__)
    parser.add_argument("target", nargs="?")
    parser.add_argument("--pid", type=int, help="attach to a running process instead of init")
    parser.add_argument("--addr", required=True, help="ciphertext address (int or x64dbg expression)")
    parser.add_argument("--size", type=lambda s: int(s, 0), required=True, help="ciphertext length in bytes")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--key", help="XOR key as hex (e.g. 42 or AABBCCDD)")
    group.add_argument("--brute", action="store_true", help="try every single-byte key, print the top 10 by printable-score")
    parser.add_argument("--out", help="write decrypted bytes to this file (requires --key)")
    args = parser.parse_args()
    if not args.target and not args.pid:
        parser.error("give a target .exe path or --pid")
    if not args.key and not args.brute:
        parser.error("give --key or --brute")

    with launch(args) as dbg:
        if args.pid:
            dbg.attach(args.pid)
        else:
            dbg.init(args.target)
        address = dbg.eval(args.addr) if isinstance(args.addr, str) else args.addr
        print(f"[xor] reading 0x{args.size:X} bytes at 0x{address:X}")
        cipher = dbg.read(address, args.size)

    if args.brute:
        results = []
        for k in range(256):
            plain = xor_bytes(cipher, bytes([k]))
            score = printable_score(plain)
            # include a short preview for ranking by eye
            preview = plain[:48].replace(b"\0", b".")
            try:
                preview_text = preview.decode("latin-1", errors="replace")
            except Exception:
                preview_text = ""
            results.append((score, k, preview_text))
        results.sort(reverse=True)
        print(f"[xor] top 10 candidates for 1-byte key (score = printable fraction):")
        print(f"{'score':>6}  key  preview")
        for score, k, preview in results[:10]:
            print(f"{score:>6.3f}  0x{k:02X}  {preview!r}")
        return 0

    key_bytes = bytes.fromhex(args.key)
    if not key_bytes:
        raise SystemExit("empty --key")
    plain = xor_bytes(cipher, key_bytes)
    print(f"[xor] key={args.key} ({len(key_bytes)} bytes), printable score of result: {printable_score(plain):.3f}")
    print(f"[xor] first 64 bytes: {plain[:64]!r}")
    if args.out:
        Path(args.out).write_bytes(plain)
        print(f"[xor] wrote {len(plain)} bytes to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
