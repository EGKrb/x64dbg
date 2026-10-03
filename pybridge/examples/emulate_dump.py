"""Emulated single-stepping from a minidump (.dmp), with Unicorn.

A .dmp is a frozen snapshot, not a running process: it cannot be debugged,
only replayed. This loads the captured memory and the thread's registers into
a CPU emulator and steps the code forward.

    py emulate_dump.py crash.dmp --count 200
    py emulate_dump.py crash.dmp --thread 1 --from "rip" --count 50
    py emulate_dump.py crash.dmp --count 5000 --keep-going --trace trace.json
    py emulate_dump.py crash.dmp --serve            # drive it from x64dbg_bridge.Debugger

Faithful mode (default) stops at the edge of the snapshot: the first page the
code reads that the dump did not capture, or the first system call. That edge
is physical -- a snapshot has no kernel behind it.

--keep-going removes that stop: missing pages are mapped on demand as zeros and
syscalls/interrupts are skipped, so execution runs on. Past the first missing
byte the trace is SPECULATIVE -- it is what the CPU would do if the absent data
were zero, not what the real process did. Use it to see where code is heading,
not as ground truth.

Only the standard library is required to parse the dump. Emulation needs
Unicorn (`pip install unicorn`); Capstone (`pip install capstone`) is optional
and only improves the disassembly text.
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

# ----------------------------------------------------------------- minidump parsing

# Stream types (minidumpapiset.h / MINIDUMP_STREAM_TYPE)
THREAD_LIST_STREAM = 3
MODULE_LIST_STREAM = 4
MEMORY_LIST_STREAM = 5
SYSTEM_INFO_STREAM = 7
MEMORY64_LIST_STREAM = 9

ARCH_X86 = 0
ARCH_AMD64 = 9


@dataclass
class Region:
    """One captured memory range: `data` lives at `start` in the target's address space."""
    start: int
    data: bytes

    @property
    def end(self) -> int:
        return self.start + len(self.data)


@dataclass
class Thread:
    tid: int
    teb: int
    context_rva: int
    context_size: int
    regs: dict[str, int] = field(default_factory=dict)


@dataclass
class Module:
    base: int
    size: int
    name: str


class MiniDump:
    """A parsed minidump: architecture, memory regions, threads and modules."""

    def __init__(self, raw: bytes):
        self.raw = raw
        signature, _version, nstreams, dir_rva = struct.unpack_from("<4sIII", raw, 0)
        if signature != b"MDMP":
            raise ValueError("not a minidump (bad MDMP signature)")
        self.arch = ARCH_AMD64
        self.regions: list[Region] = []
        self.threads: list[Thread] = []
        self.modules: list[Module] = []
        streams = {}
        for i in range(nstreams):
            stype, size, rva = struct.unpack_from("<III", raw, dir_rva + i * 12)
            streams[stype] = (size, rva)

        if SYSTEM_INFO_STREAM in streams:
            self.arch = struct.unpack_from("<H", raw, streams[SYSTEM_INFO_STREAM][1])[0]
        if MEMORY64_LIST_STREAM in streams:
            self._parse_memory64(*streams[MEMORY64_LIST_STREAM])
        if MEMORY_LIST_STREAM in streams:
            self._parse_memory(*streams[MEMORY_LIST_STREAM])
        if MODULE_LIST_STREAM in streams:
            self._parse_modules(*streams[MODULE_LIST_STREAM])
        if THREAD_LIST_STREAM in streams:
            self._parse_threads(*streams[THREAD_LIST_STREAM])
        self.regions.sort(key=lambda r: r.start)

    @property
    def bits(self) -> int:
        return 32 if self.arch == ARCH_X86 else 64

    # MINIDUMP_MEMORY_LIST: NumberOfMemoryRanges u32, then MINIDUMP_MEMORY_DESCRIPTOR[]
    # descriptor: StartOfMemoryRange u64, LocationDescriptor{DataSize u32, Rva u32}
    def _parse_memory(self, _size: int, rva: int) -> None:
        count = struct.unpack_from("<I", self.raw, rva)[0]
        off = rva + 4
        for _ in range(count):
            start, data_size, data_rva = struct.unpack_from("<QII", self.raw, off)
            off += 16
            self.regions.append(Region(start, self.raw[data_rva:data_rva + data_size]))

    # MINIDUMP_MEMORY64_LIST: NumberOfRanges u64, BaseRva u64, then MINIDUMP_MEMORY_DESCRIPTOR64[]
    # descriptor64: StartOfMemoryRange u64, DataSize u64 -- data stored back-to-back from BaseRva
    def _parse_memory64(self, _size: int, rva: int) -> None:
        count, base_rva = struct.unpack_from("<QQ", self.raw, rva)
        off = rva + 16
        data_off = base_rva
        for _ in range(count):
            start, data_size = struct.unpack_from("<QQ", self.raw, off)
            off += 16
            self.regions.append(Region(start, self.raw[data_off:data_off + data_size]))
            data_off += data_size

    # MINIDUMP_THREAD_LIST: NumberOfThreads u32, then MINIDUMP_THREAD[] (48 bytes each)
    # thread: ThreadId u32, SuspendCount u32, PriorityClass u32, Priority u32, Teb u64,
    #         Stack{StartOfMemoryRange u64, DataSize u32, Rva u32}, ThreadContext{DataSize u32, Rva u32}
    def _parse_threads(self, _size: int, rva: int) -> None:
        count = struct.unpack_from("<I", self.raw, rva)[0]
        off = rva + 4
        for _ in range(count):
            tid, _susp, _pc, _prio, teb = struct.unpack_from("<IIIIQ", self.raw, off)
            ctx_size, ctx_rva = struct.unpack_from("<II", self.raw, off + 24 + 16)
            off += 48
            thread = Thread(tid, teb, ctx_rva, ctx_size)
            thread.regs = self._parse_context(ctx_rva)
            self.threads.append(thread)

    # MINIDUMP_MODULE_LIST: NumberOfModules u32, then MINIDUMP_MODULE[] (108 bytes each)
    def _parse_modules(self, _size: int, rva: int) -> None:
        count = struct.unpack_from("<I", self.raw, rva)[0]
        off = rva + 4
        for _ in range(count):
            base, size, _cv, _ts, name_rva = struct.unpack_from("<QIIII", self.raw, off)
            off += 108
            nlen = struct.unpack_from("<I", self.raw, name_rva)[0]  # MINIDUMP_STRING: Length u32 + UTF-16LE
            name = self.raw[name_rva + 4:name_rva + 4 + nlen].decode("utf-16-le", "replace")
            self.modules.append(Module(base, size, name))

    def _parse_context(self, rva: int) -> dict[str, int]:
        return self._context_amd64(rva) if self.arch == ARCH_AMD64 else self._context_x86(rva)

    # CONTEXT (AMD64), winnt.h offsets
    def _context_amd64(self, rva: int) -> dict[str, int]:
        b = self.raw
        regs = {
            "eflags": struct.unpack_from("<I", b, rva + 0x44)[0],
            "cs": struct.unpack_from("<H", b, rva + 0x38)[0],
            "ss": struct.unpack_from("<H", b, rva + 0x42)[0],
        }
        order = ["rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi",
                 "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15", "rip"]
        for i, name in enumerate(order):
            regs[name] = struct.unpack_from("<Q", b, rva + 0x78 + i * 8)[0]
        return regs

    # CONTEXT (x86), winnt.h offsets (FLOATING_SAVE_AREA is 112 bytes at 0x1c)
    def _context_x86(self, rva: int) -> dict[str, int]:
        b = self.raw
        names = {
            "edi": 0x9C, "esi": 0xA0, "ebx": 0xA4, "edx": 0xA8, "ecx": 0xAC,
            "eax": 0xB0, "ebp": 0xB4, "eip": 0xB8, "eflags": 0xC0, "esp": 0xC4,
        }
        return {name: struct.unpack_from("<I", b, rva + off)[0] for name, off in names.items()}

    def readable(self, address: int) -> bool:
        return any(r.start <= address < r.end for r in self.regions)

    def module_at(self, address: int) -> Module | None:
        for m in self.modules:
            if m.base <= address < m.base + m.size:
                return m
        return None


# ----------------------------------------------------------------- emulation

PAGE = 0x1000


def _align_down(x: int) -> int:
    return x & ~(PAGE - 1)


def _align_up(x: int) -> int:
    return (x + PAGE - 1) & ~(PAGE - 1)


def eval_expr(text: str, regs: dict[str, int], bits: int) -> int:
    """Tiny address expression: a register name, a 0x/decimal literal, or `reg +/- 0xNN`.

    Literals must be explicit (0x for hex) -- unlike x64dbg, bare numbers here are decimal.
    """
    mask = (1 << bits) - 1
    text = text.strip()
    try:
        return int(text, 0) & mask
    except ValueError:
        pass
    try:
        return int(eval(text, {"__builtins__": {}}, dict(regs))) & mask
    except Exception as exc:
        raise ValueError(f"cannot evaluate {text!r}: {exc}") from exc


class Emulator:
    """A dump loaded into Unicorn, stepped one instruction at a time."""

    def __init__(self, dump: MiniDump, thread: Thread, start_at: str | None = None, keep_going: bool = False):
        try:
            from unicorn import (Uc, UC_ARCH_X86, UC_MODE_32, UC_MODE_64, UC_PROT_ALL,
                                 UC_HOOK_MEM_UNMAPPED, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE,
                                 UC_HOOK_INSN, UC_HOOK_INTR, UC_ERR_INSN_INVALID, UcError)
            from unicorn import x86_const as x86
        except ImportError:
            raise SystemExit("Unicorn is required: pip install unicorn")
        self._UcError = UcError
        self._UC_ERR_INSN_INVALID = UC_ERR_INSN_INVALID
        self.skipped = 0
        self.dump = dump
        self.thread = thread
        self.keep_going = keep_going
        self.bits = dump.bits
        self.index = 0
        self.stop_reason: str | None = None
        self.stop_addr: int | None = None
        self.synthetic_pages = 0
        self._x86 = x86
        self._decode = _make_disassembler(self.bits)

        uc = Uc(UC_ARCH_X86, UC_MODE_64 if self.bits == 64 else UC_MODE_32)
        self.uc = uc

        # Map every captured region, page-aligned; overlapping aligned spans are merged.
        spans: list[list[int]] = []
        for r in dump.regions:
            if not r.data:
                continue
            lo, hi = _align_down(r.start), _align_up(r.end)
            if spans and lo <= spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], hi)
            else:
                spans.append([lo, hi])
        self.mapped_pages = 0
        for lo, hi in spans:
            uc.mem_map(lo, hi - lo, UC_PROT_ALL)
            self.mapped_pages += (hi - lo) // PAGE
        for r in dump.regions:
            if r.data:
                uc.mem_write(r.start, r.data)

        # Registers.
        self._reg_map = {
            "rax": x86.UC_X86_REG_RAX, "rbx": x86.UC_X86_REG_RBX, "rcx": x86.UC_X86_REG_RCX,
            "rdx": x86.UC_X86_REG_RDX, "rsi": x86.UC_X86_REG_RSI, "rdi": x86.UC_X86_REG_RDI,
            "rbp": x86.UC_X86_REG_RBP, "rsp": x86.UC_X86_REG_RSP, "rip": x86.UC_X86_REG_RIP,
            "r8": x86.UC_X86_REG_R8, "r9": x86.UC_X86_REG_R9, "r10": x86.UC_X86_REG_R10,
            "r11": x86.UC_X86_REG_R11, "r12": x86.UC_X86_REG_R12, "r13": x86.UC_X86_REG_R13,
            "r14": x86.UC_X86_REG_R14, "r15": x86.UC_X86_REG_R15,
            "eax": x86.UC_X86_REG_EAX, "ebx": x86.UC_X86_REG_EBX, "ecx": x86.UC_X86_REG_ECX,
            "edx": x86.UC_X86_REG_EDX, "esi": x86.UC_X86_REG_ESI, "edi": x86.UC_X86_REG_EDI,
            "ebp": x86.UC_X86_REG_EBP, "esp": x86.UC_X86_REG_ESP, "eip": x86.UC_X86_REG_EIP,
            "eflags": x86.UC_X86_REG_EFLAGS,
        }
        if self.bits == 64:
            self._live_regs = [r for r in self._reg_map if not r.startswith("e") or r == "eflags"]
        else:
            self._live_regs = [r for r in self._reg_map if not r.startswith("r")]
        for name, value in thread.regs.items():
            if name in self._reg_map:
                uc.reg_write(self._reg_map[name], value)

        # Point the segment base at the captured TEB so gs:[..]/fs:[..] resolve (if that page was dumped).
        if thread.teb:
            uc.reg_write(x86.UC_X86_REG_GS_BASE if self.bits == 64 else x86.UC_X86_REG_FS_BASE, thread.teb)

        self.ip_name = "rip" if self.bits == 64 else "eip"
        self.ip_reg = self._reg_map[self.ip_name]
        start = eval_expr(start_at, thread.regs, self.bits) if start_at else thread.regs.get(self.ip_name, 0)
        uc.reg_write(self.ip_reg, start)

        # Per-instruction memory accesses, captured for the trace (like TraceExport's memory column).
        self._mem_events: list[tuple[int, int, int, bool]] = []
        uc.hook_add(UC_HOOK_MEM_READ, self._on_mem_read)
        uc.hook_add(UC_HOOK_MEM_WRITE, self._on_mem_write)

        # Hooks. In faithful mode on_unmapped records the edge and stops; keep-going fills and skips.
        uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._on_unmapped)
        if keep_going:
            if self.bits == 64:
                uc.hook_add(UC_HOOK_INSN, self._on_syscall, None, 1, 0, x86.UC_X86_INS_SYSCALL)
            uc.hook_add(UC_HOOK_INTR, self._on_interrupt)

    # ----- hooks

    def _on_unmapped(self, uc, _access, address, size, _value, _user):
        if self.keep_going:
            lo = _align_down(address)
            span = _align_up(address + max(size, 1)) - lo
            try:
                uc.mem_map(lo, span)
                self.synthetic_pages += span // PAGE
            except self._UcError:
                pass  # already mapped by a racing fault; retry anyway
            return True  # retry the access against the fresh zero page
        self.stop_reason = "unmapped memory"
        self.stop_addr = address
        return False

    def _on_syscall(self, uc, _user):
        # Skip the syscall: advance past 0f05 and return 0 (STATUS_SUCCESS). Speculative.
        rip = uc.reg_read(self._x86.UC_X86_REG_RIP)
        uc.reg_write(self._x86.UC_X86_REG_RIP, rip + 2)
        uc.reg_write(self._x86.UC_X86_REG_RAX, 0)

    def _on_mem_read(self, uc, _access, address, size, _value, _user):
        if len(self._mem_events) < 32:
            val = int.from_bytes(self._safe_read(address, size) or b"\0" * size, "little")
            self._mem_events.append((address, val, val, False))

    def _on_mem_write(self, uc, _access, address, size, value, _user):
        if len(self._mem_events) < 32:
            old = int.from_bytes(self._safe_read(address, size) or b"\0" * size, "little")
            self._mem_events.append((address, old, value & ((1 << (size * 8)) - 1), True))

    def _on_interrupt(self, uc, _intno, _user):
        # Skip software interrupts (int 2e, sysenter paths): step over the instruction.
        ip = uc.reg_read(self.ip_reg)
        _text, size = self._decode(bytes(self._safe_read(ip, 16)), ip)
        uc.reg_write(self.ip_reg, ip + (size or 2))

    # ----- primitives

    def _safe_read(self, address: int, size: int) -> bytes:
        try:
            return bytes(self.uc.mem_read(address, size))
        except self._UcError:
            return b""

    def regs(self) -> dict[str, int]:
        return {name: self.uc.reg_read(self._reg_map[name]) for name in self._live_regs}

    def reg(self, name: str) -> int:
        return self.uc.reg_read(self._reg_map[name.lower()])

    def set_reg(self, name: str, value: int) -> None:
        self.uc.reg_write(self._reg_map[name.lower()], value & ((1 << self.bits) - 1))

    def read(self, address: int, size: int) -> bytes:
        return bytes(self.uc.mem_read(address, size))

    def write(self, address: int, data: bytes) -> None:
        self.uc.mem_write(address, data)

    def valid(self, address: int) -> bool:
        return len(self._safe_read(address, 1)) == 1

    def evaluate(self, text: str) -> int:
        return eval_expr(text, self.regs(), self.bits)

    def disasm(self, address: int, count: int = 1) -> list[dict]:
        out = []
        buf = self._safe_read(address, 16 * count)
        offset = 0
        for _ in range(count):
            text, size = self._decode(buf[offset:offset + 16], address + offset)
            size = size or 1
            out.append({
                "address": address + offset,
                "size": size,
                "text": text,
                "bytes": buf[offset:offset + size].hex(),
            })
            offset += size
            if offset >= len(buf):
                break
        return out

    @property
    def ip(self) -> int:
        return self.uc.reg_read(self.ip_reg)

    @property
    def stopped(self) -> bool:
        return self.stop_reason is not None

    def step(self) -> dict | None:
        """Execute one instruction. Returns a trace record, or None once stopped."""
        if self.stopped:
            return None
        ip = self.ip
        if not self.keep_going and not self.dump.readable(ip):
            self.stop_reason = "instruction pointer left the dump"
            self.stop_addr = ip
            return None
        text, size = self._decode(self._safe_read(ip, 16), ip)
        before = self.regs()
        self._mem_events = []
        try:
            self.uc.emu_start(ip, 0, count=1)
        except self._UcError as exc:
            # keep-going also steps over instructions Unicorn itself cannot decode (ISA gaps).
            if self.keep_going and not self.stopped and exc.errno == self._UC_ERR_INSN_INVALID and size:
                self.uc.reg_write(self.ip_reg, ip + size)
                self.skipped += 1
                self.index += 1
                return {"index": self.index, "address": ip, "size": size, "text": text,
                        "bytes": self._safe_read(ip, size).hex(), "changed": {},
                        "regs_before": before, "mem": [], "skipped": True}
            if not self.stopped:  # a fault the hooks did not turn into a clean stop
                self.stop_reason = f"cpu fault: {exc}"
                self.stop_addr = ip
            return None
        self.index += 1
        after = self.regs()
        changed = {n: after[n] for n in after if after[n] != before.get(n)}
        return {"index": self.index, "address": ip, "size": size, "text": text,
                "bytes": self._safe_read(ip, size or 1).hex(), "changed": changed,
                "regs_before": before, "mem": list(self._mem_events)}


def _make_disassembler(bits: int):
    """Return decode(code, addr) -> (text, size). size is None when Capstone is absent."""
    try:
        import capstone
        md = capstone.Cs(capstone.CS_ARCH_X86,
                         capstone.CS_MODE_64 if bits == 64 else capstone.CS_MODE_32)

        def disasm(code: bytes, addr: int):
            for insn in md.disasm(bytes(code), addr):
                return (f"{insn.mnemonic} {insn.op_str}".strip(), insn.size)
            return ("db " + (f"{code[0]:02x}" if code else "??"), None)

        return disasm
    except ImportError:
        return lambda code, addr: ("? " + " ".join(f"{b:02x}" for b in bytes(code)[:8]), None)


# ----------------------------------------------------------------- cli: step + trace

def run_cli(dump: MiniDump, thread: Thread, count: int, start_at: str | None, keep_going: bool,
            trace_path: str | None, trace_csv: str | None, quiet: bool, dump_path: str = "") -> int:
    emu = Emulator(dump, thread, start_at, keep_going)
    mode = "keep-going (speculative past missing data)" if keep_going else "faithful (stops at snapshot edge)"
    print(f"arch x{emu.bits}  thread {thread.tid:#x}  start {emu.ip:#018x}  "
          f"{emu.mapped_pages} pages mapped  [{mode}]\n")

    recording = trace_path is not None or trace_csv is not None
    records = []
    for _ in range(count):
        record = emu.step()
        if record is None:
            break
        if recording:
            records.append(record)
        if not quiet:
            changes = ", ".join(f"{n}={v:x}" for n, v in record["changed"].items() if n != emu.ip_name)
            print(f"{record['address']:#018x}  {record['text']:<42}{changes}")

    print()
    if emu.stopped:
        where = f" at {emu.stop_addr:#018x}" if emu.stop_addr is not None else ""
        mod = emu.dump.module_at(emu.stop_addr) if emu.stop_addr is not None else None
        in_mod = f" (in {mod.name})" if mod else ""
        print(f"stopped after {emu.index} instructions: {emu.stop_reason}{where}{in_mod}")
        if not keep_going:
            print("edge of the snapshot -- retry with --keep-going to push past it (results become speculative).")
    else:
        print(f"stepped {emu.index} instructions (reached --count)")
    if keep_going and (emu.synthetic_pages or emu.skipped):
        bits = []
        if emu.synthetic_pages:
            bits.append(f"{emu.synthetic_pages} zero-filled pages invented")
        if emu.skipped:
            bits.append(f"{emu.skipped} undecodable instructions skipped")
        print(f"note: {', '.join(bits)} -- the trace is speculative from there.")

    if trace_path is not None:
        payload = {
            "dump": dump_path,
            "arch": f"x{emu.bits}",
            "thread": thread.tid,
            "keep_going": keep_going,
            "synthetic_pages": emu.synthetic_pages,
            "stopped": emu.stop_reason,
            "count": len(records),
            "instructions": [
                {"index": r["index"], "address": f"{r['address']:#x}", "size": r["size"],
                 "disasm": r["text"], "bytes": r["bytes"],
                 "registers": {n: f"{v:#x}" for n, v in r["changed"].items()},
                 "mem": [{"address": f"{a:#x}", "old": f"{o:#x}", "new": f"{n:#x}"}
                         for a, o, n, _w in r.get("mem", [])],
                 **({"skipped": True} if r.get("skipped") else {})}
                for r in records
            ],
        }
        Path(trace_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {len(records)} instructions to {Path(trace_path).resolve()}")

    if trace_csv is not None:
        write_trace_csv(trace_csv, emu, thread, records)
        print(f"wrote {len(records)} instructions to {Path(trace_csv).resolve()}")
    return 0


# Column order of TraceExport's CSV (src/dbg/TraceExport.cpp), eflags shown as rflags on x64.
_CSV_REGS = {
    64: ["rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi",
         "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15", "rip", "eflags"],
    32: ["eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi", "eip", "eflags"],
}


def _hexu(value: int) -> str:
    return f"0x{value:X}"  # matches TraceExport's "0x%llX"


def _csv_field(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'  # matches TraceExportCsvString (always quoted)


def write_trace_csv(path: str, emu: Emulator, thread: Thread, records: list[dict]) -> None:
    """Write the emulated trace in TraceExport's exact CSV layout (same columns, hex and \\r\\n)."""
    names = _CSV_REGS[emu.bits]
    header_names = [("rflags" if n == "eflags" and emu.bits == 64 else n) for n in names]
    lines = ["index,thread,address,module,bytes,disasm," + ",".join(header_names) + ",memory\r\n"]
    for r in records:
        regs = r["regs_before"]
        row_bytes = " ".join(f"{b:02X}" for b in bytes.fromhex(r["bytes"]))
        mod = emu.dump.module_at(r["address"])
        module = Path(mod.name).name if mod else ""
        mem = ";".join(
            f"{_hexu(a)}:{_hexu(o)}" + (f"->{_hexu(n)}" if n != o else "")
            for a, o, n, _w in r.get("mem", [])
        )
        cells = [
            str(r["index"]), str(thread.tid), _hexu(r["address"]),
            _csv_field(module), _csv_field(row_bytes), _csv_field(r["text"]),
            *(_hexu(regs.get(n, 0)) for n in names),
            _csv_field(mem),
        ]
        lines.append(",".join(cells) + "\r\n")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)


# ----------------------------------------------------------------- pybridge-compatible server

class EmulationServer:
    """Speaks the pybridge line-JSON protocol so x64dbg_bridge.Debugger drives the emulator.

    The debuggee is the dump: `Debugger(port=...)` connects, then step_into(), regs(),
    read(), disasm() behave as on a live target, within the snapshot's limits.
    """

    def __init__(self, emu: Emulator):
        self.emu = emu

    def handle(self, method: str, params: dict) -> object:
        emu = self.emu
        if method == "ping":
            return {"arch": "x64" if emu.bits == 64 else "x32"}
        if method == "state":
            return {"debugging": True, "cip": f"{emu.ip:#x}"}
        if method == "regs":
            return {n: f"{v:#x}" for n, v in emu.regs().items()}
        if method == "reg_get":
            return f"{emu.reg(params['name']):#x}"
        if method == "reg_set":
            emu.set_reg(params["name"], _as_int(params["value"]))
            return True
        if method == "eval":
            return f"{emu.evaluate(str(params['expr'])):#x}"
        if method == "mem_read":
            return emu.read(_as_int(params["addr"]), int(params["size"])).hex()
        if method == "mem_write":
            emu.write(_as_int(params["addr"]), bytes.fromhex(params["data"]))
            return True
        if method == "mem_valid":
            return emu.valid(_as_int(params["addr"]))
        if method == "disasm":
            return [{"address": f"{e['address']:#x}", "size": e["size"],
                     "text": e["text"], "bytes": e["bytes"]}
                    for e in emu.disasm(_as_int(params["addr"]), int(params.get("count", 1)))]
        if method in ("step_into", "step_over"):
            if method == "step_over":
                self._step_over()
            else:
                emu.step()
            return {"paused": not emu.stopped}
        if method in ("run", "pause", "wait"):
            return {"paused": not emu.stopped}  # no free-run in the emulator; report state
        raise ValueError(f"unsupported method: {method}")

    def _step_over(self) -> None:
        emu = self.emu
        insn = emu.disasm(emu.ip, 1)[0]
        if insn["text"].startswith("call"):
            target_return = emu.ip + insn["size"]
            for _ in range(200000):  # bounded: step into the call until it returns in-dump
                if emu.step() is None or emu.ip == target_return:
                    return
        else:
            emu.step()


def _as_int(value) -> int:
    return value if isinstance(value, int) else int(str(value), 0)


def serve(emu: Emulator, host: str, port: int) -> int:
    server = EmulationServer(emu)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, port))
    listener.listen(1)
    print(f"pybridge-compatible emulation server on {host}:{port} "
          f"(x{emu.bits}, thread {emu.thread.tid:#x}) -- Ctrl+C to stop")
    print("connect with:  from x64dbg_bridge import Debugger;  dbg = Debugger(port=%d)" % port)
    try:
        while True:
            client, _ = listener.accept()
            threading.Thread(target=_serve_client, args=(server, client), daemon=True).start()
    except KeyboardInterrupt:
        print("\nstopped")
        return 0
    finally:
        listener.close()


def _serve_client(server: EmulationServer, client: socket.socket) -> None:
    with client, client.makefile("rb") as reader:
        for line in reader:
            try:
                request = json.loads(line)
                result = server.handle(request["method"], request.get("params", {}))
                response = {"id": request.get("id"), "result": result}
            except Exception as exc:  # report as a protocol error, keep the connection open
                response = {"id": None, "error": str(exc)}
            try:
                client.sendall(json.dumps(response).encode("utf-8") + b"\n")
            except OSError:
                break


# ----------------------------------------------------------------- argument parsing

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dump", help="path to the .dmp file")
    parser.add_argument("--thread", type=int, default=0, help="thread index to emulate (default: 0)")
    parser.add_argument("--count", type=int, default=100, help="max instructions to step (ignored with --serve)")
    parser.add_argument("--from", dest="start_at", default=None,
                        help="start address/expression (default: the thread's captured rip)")
    parser.add_argument("--keep-going", action="store_true",
                        help="do not stop at the snapshot edge: map missing pages as zero, skip syscalls (speculative)")
    parser.add_argument("--trace", dest="trace_path", default=None, help="write the emulated trace to this JSON file")
    parser.add_argument("--trace-csv", dest="trace_csv", default=None,
                        help="write the emulated trace to this CSV file (TraceExport column layout)")
    parser.add_argument("--quiet", action="store_true", help="do not print each instruction (useful with --trace)")
    parser.add_argument("--serve", action="store_true", help="serve the emulator over the pybridge protocol")
    parser.add_argument("--port", type=int, default=27041, help="port for --serve (default: 27041)")
    parser.add_argument("--host", default="127.0.0.1", help="bind host for --serve")
    parser.add_argument("--list-threads", action="store_true", help="list threads and exit")
    args = parser.parse_args()

    dump = MiniDump(Path(args.dump).read_bytes())
    if not dump.threads:
        sys.exit("no thread context in this dump (nothing to emulate)")

    if args.list_threads:
        ip_name = "rip" if dump.bits == 64 else "eip"
        for i, t in enumerate(dump.threads):
            print(f"[{i}] tid={t.tid:#x}  {ip_name}={t.regs.get(ip_name, 0):#018x}")
        return 0

    if not 0 <= args.thread < len(dump.threads):
        sys.exit(f"thread index out of range (0..{len(dump.threads) - 1})")
    thread = dump.threads[args.thread]

    if args.serve:
        emu = Emulator(dump, thread, args.start_at, args.keep_going)
        return serve(emu, args.host, args.port)

    return run_cli(dump, thread, args.count, args.start_at, args.keep_going,
                   args.trace_path, args.trace_csv, args.quiet, args.dump)


if __name__ == "__main__":
    raise SystemExit(main())
