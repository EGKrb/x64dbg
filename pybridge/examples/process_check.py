"""List running processes a protector might scan for and flag the usual RE tools.

    py process_check.py

This runs locally (no target launch): it uses the Windows Toolhelp snapshot
through x64dbg's own `enumprocesses` is not exposed, so we fall back to a plain
`ctypes` call. The point is to show *what the protector sees* -- if ida.exe,
ghidra.exe, x64dbg.exe, frida-server.exe etc. are visible to a Toolhelp scan,
a protector doing the same scan will flag them.

Flagged names come from the hard-coded RE_TOOLS set below; extend as needed.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

RE_TOOLS = {
    "x64dbg.exe", "x32dbg.exe", "ollydbg.exe", "ida.exe", "ida64.exe",
    "ghidra.exe", "ghidra64.exe", "frida.exe", "frida-server.exe",
    "windbg.exe", "cheatengine-x86_64.exe", "cheatengine-i386.exe",
    "processhacker.exe", "procexp.exe", "procexp64.exe", "procmon.exe",
    "procmon64.exe", "wireshark.exe", "fiddler.exe", "httpdebuggerui.exe",
    "scylla_x64.exe", "scylla_x86.exe", "petools.exe", "pe-bear.exe",
    "resourcehacker.exe", "lordpe.exe", "importrec.exe", "immunity.exe",
}

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = -1
MAX_PATH = 260


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * MAX_PATH),
    ]


def enum_processes() -> list[tuple[int, str]]:
    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        raise OSError("CreateToolhelp32Snapshot failed")
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        out: list[tuple[int, str]] = []
        if not k32.Process32FirstW(snap, ctypes.byref(entry)):
            return out
        while True:
            out.append((entry.th32ProcessID, entry.szExeFile))
            if not k32.Process32NextW(snap, ctypes.byref(entry)):
                break
        return out
    finally:
        k32.CloseHandle(snap)


def main() -> int:
    processes = enum_processes()
    print(f"[procs] {len(processes)} running")
    flagged = [(pid, name) for pid, name in processes if name.lower() in RE_TOOLS]
    if not flagged:
        print("[procs] no RE tools visible")
        return 0
    for pid, name in flagged:
        print(f"[procs] FLAGGED  pid={pid:<6} {name}")
    return 1 if flagged else 0


if __name__ == "__main__":
    raise SystemExit(main())
