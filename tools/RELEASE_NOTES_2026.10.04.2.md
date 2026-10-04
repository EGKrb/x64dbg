# x64dbg EGKrb 2026.10.04.2

Fork **EGKrb/x64dbg** — guide et scripts anti-anti-debugging pour contourner les protections multi-couches.

## Nouveautés

### Guide anti-anti-debugging

L'outil utilise plusieurs couches de détection. Voici les fonctionnalités nécessaires pour chacune.

#### 1. Anti-anti-debugging (contourner les checks PEB / NtQuery)

**ScyllaHide** — `Plugins → ScyllaHide → Options` :

- ✅ `PEB.BeingDebugged`
- ✅ `PEB.NtGlobalFlag`
- ✅ `Heap flags`
- ✅ `NtQueryInformationProcess` (ProcessDebugPort, ProcessDebugObjectHandle, ProcessDebugFlags)

**TitanHide** (à installer) :

```powershell
cd C:\x64dbg\egkrb-2026.10.04.2\release
powershell -ExecutionPolicy Bypass -File .\install-plugins.ps1 -Plugins TitanHide
```

- ✅ Registres DR0-DR7 (hardware breakpoints)
- ✅ Masquage au niveau kernel
- ✅ Contournement SSDT hooks

#### 2. Contournement des timing checks

L'outil utilise `Rdtsc` pour détecter les pauses du debugger.

**Plugin : TitanEngine** — `Options → Preferences → Engine` :

- ✅ Use VEH Debug (Vectored Exception Handling)
- ✅ Use VCH Debug (Vectored Continue Handling)

**Script Python** — `rdtsc_hook.py` :

```python
from x64dbg_bridge import Debugger

def hook_rdtsc(dbg):
    addr = dbg.eval("ntdll.RtlGetTickCount")
    dbg.set_breakpoint(addr, command="set $eax=0; set $edx=0; ret")
```

#### 3. Contournement des callbacks noyau

L'outil utilise `ObRegisterCallbacks` pour détecter les handles de debug.

**Plugins : ScyllaHide + TitanHide**

```ini
[ScyllaHide]
HideDebugger=1
NtQuerySystemInformation=1
NtQueryInformationProcess=1
NtSetInformationThread=1
NtCreateThreadEx=1
ObRegisterCallbacks=1
```

#### 4. Contournement du packer VM

Interpréteur de bytecode custom qui ne flip jamais un gros buffer en `PAGE_EXECUTE_*`.

**Fonctionnalité** : désassembleur de bytecode personnalisé — `Plugins → xAnalyzer → Analyze Module`

**Script** — `find_bytecode.py` :

```python
from x64dbg_bridge import Debugger

def find_bytecode(dbg):
    patterns = [
        "48 8B 05 ?? ?? ?? ?? 48 85 C0 74 ?? 48 8B C8",
        "48 8B 0D ?? ?? ?? ?? 48 85 C9 74 ?? 48 8B C1",
    ]
    for pattern in patterns:
        result = dbg.eval(f'findallmem(0, "{pattern}")')
        if result:
            print(f"Pattern trouvé: {pattern} à {result}")
```

#### 5. Contournement des TLS callbacks

L'outil fait ses checks dans les TLS callbacks (avant `main`).

**Configuration x64dbg** — `Options → Preferences → Events` :

- ✅ Break on TLS Callbacks
- ✅ Suspend on TLS Callbacks

**Script** — `tls_logger.py` :

```python
from x64dbg_bridge import Debugger

def log_tls_callbacks(dbg):
    callbacks = dbg.eval("mod.tlscallbacks()")
    for cb in callbacks:
        print(f"TLS Callback: {cb}")
        dbg.set_breakpoint(cb, command='log "TLS Callback hit"')
```

#### 6. Contournement des exceptions anti-debug

L'outil utilise des exceptions intentionnelles (`int3`, `int2d`, etc.) pour détecter les debuggers.

**Configuration x64dbg** — `Options → Preferences → Engine` :

- ✅ Use Exception Breakpoints
- ✅ Pass exceptions to the debuggee

**Script** — `exception_handler.py` :

```python
from x64dbg_bridge import Debugger

def handle_exceptions(dbg):
    dbg.cmd("SetExceptionBPX 0xC0000035, 0")  # STATUS_BREAKPOINT
    dbg.cmd("SetExceptionBPX 0xC000001D, 0")  # STATUS_ILLEGAL_INSTRUCTION
    dbg.cmd("SetExceptionBPX 0xC0000096, 0")  # STATUS_PRIVILEGED_INSTRUCTION
```

#### 7. Contournement des checks de mémoire

L'outil vérifie l'intégrité de sa mémoire.

**Plugin : xAnalyzer** — `Plugins → xAnalyzer → Analyze Module`

**Script** — `integrity_check.py` :

```python
from x64dbg_bridge import Debugger
import hashlib

def check_integrity(dbg):
    base = dbg.eval("mod.base()")
    size = dbg.eval("mod.size()")
    data = dbg.read_memory(base, size)
    hash_val = hashlib.sha256(data).hexdigest()
    print(f"Module hash: {hash_val}")
```

#### 8. Contournement des checks de processus

L'outil vérifie les processus en cours d'exécution.

**Script** — `process_check.py` :

```python
from x64dbg_bridge import Debugger

def check_processes(dbg):
    processes = dbg.eval("enumprocesses()")
    for proc in processes:
        name = proc["name"]
        if any(x in name.lower() for x in ["x64dbg", "x32dbg", "ollydbg", "ida", "ghidra", "frida"]):
            print(f"Processus détecté: {name}")
```

## Checksums

Voir `SHA256SUMS.txt`.
