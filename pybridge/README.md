# pybridge

Piloter x64dbg (interface graphique ou `headless.exe`) depuis Python, plus des modèles de scripts prêts à l'emploi pour `headless.exe`.

- `src/` : le plugin x64dbg (`pybridge.dp64` / `pybridge.dp32`). Il ouvre un serveur TCP sur **127.0.0.1** et traduit des requêtes JSON en appels à l'API d'x64dbg.
- `python/x64dbg_bridge.py` : le client Python (bibliothèque standard uniquement, rien à installer).
- `examples/` : scripts Python d'exemple.
- `headless/` : lanceur PowerShell et modèles de scripts x64dbg pour `headless.exe`.

> **Sécurité** : le serveur n'accepte que les connexions locales, mais tout programme local qui s'y connecte contrôle complètement le débogueur (lecture/écriture mémoire du processus débogué, exécution de commandes). Ne le démarrez que quand vous en avez besoin.

## Compilation

Prérequis : Visual Studio 2022 (C++), CMake, Ninja. Le SDK de plugins est pris par défaut dans l'installation winget d'x64dbg (`-DX64DBG_SDK=...` pour un autre chemin).

```bat
:: 64 bits (x64dbg)
"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
cmake -B build-x64 -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build-x64

:: 32 bits (x32dbg), dans un autre terminal
"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat"
cmake -B build-x32 -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build-x32
```

## Installation

Copier le plugin dans le dossier `plugins` d'x64dbg :

```powershell
$x64dbg = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\x64dbg.x64dbg_Microsoft.Winget.Source_8wekyb3d8bbwe\release"
Copy-Item build-x64\pybridge.dp64 "$x64dbg\x64\plugins\"
Copy-Item build-x32\pybridge.dp32 "$x64dbg\x32\plugins\"
```

Le serveur démarre :

- automatiquement si la variable d'environnement `X64DBG_PYBRIDGE_PORT` est définie (c'est ce que fait `Debugger.launch()`) ;
- sinon avec la commande `pybridge.start [port]` dans x64dbg (port décimal, 27041 par défaut). Aussi : `pybridge.stop`, `pybridge.status`.

## Utilisation depuis Python

```python
import sys
sys.path.insert(0, r"C:\chemin\vers\x64dbg\pybridge\python")
from x64dbg_bridge import Debugger

X64DBG = r"C:\chemin\vers\x64dbg\bin"   # dossier qui contient x64 et x32

with Debugger.launch(X64DBG) as dbg:          # démarre headless.exe ; gui=True pour x64dbg.exe
    dbg.init(r"C:\Windows\System32\whoami.exe")
    dbg.set_breakpoint("kernelbase.CreateFileW")
    if dbg.run(wait=True):
        print(dbg.read_string("rcx", wide=True))   # 1er argument (x64)
        print(dbg.regs())
        for ins in dbg.disasm("rip", 5):
            print(hex(ins["address"]), ins["text"])
```

Pour se connecter à un x64dbg déjà ouvert (après `pybridge.start`) : `Debugger()`.

Les adresses et valeurs acceptent un entier ou une **expression x64dbg** : `"kernelbase.CreateFileW"`, `"rsp+8"`, `"[rsp]"`, `"mod.base(target.exe)"`. Dans les expressions, les nombres sont en **hexadécimal** par défaut (`.100` = 100 décimal).

| Catégorie | Méthodes |
|---|---|
| Session | `launch()`, `init(path, arguments, cwd)`, `attach(pid)`, `stop()`, `close()` |
| Exécution | `run(wait, timeout, pass_exceptions)`, `pause()`, `step_into()`, `step_over()`, `step_out()`, `wait(timeout)`, `state()` |
| Registres | `regs()`, `reg(name)`, `set_reg(name, value)` |
| Mémoire | `read(addr, size)`, `write(addr, data)`, `read_ptr(addr)`, `read_string(addr, wide)`, `is_valid(addr)`, `disasm(addr, count)` |
| Breakpoints | `set_breakpoint(addr, condition, log, command, break_, singleshot)`, `delete_breakpoint(addr)`, `set_hardware_breakpoint(addr, kind, size)` |
| Traces | `trace(record_file, condition, max_steps, step_over)`, `export_trace(trace, output, fmt)` |
| Commandes | `cmd("texte brut")`, `command(name, *args)` (échappement automatique), `eval(expr)`, `result` (`$result`) |

`export_trace()` utilise la commande `TraceExport`, qui n'existe que dans le x64dbg de ce dépôt (pas dans les versions officielles).

## Exemples

Dans `examples/` (option `--x64dbg <dossier release>` ou variable `X64DBG_DIR` pour choisir la version d'x64dbg) :

| Script | Rôle |
|---|---|
| `api_monitor.py cible.exe` | journalise les appels d'API (CreateFileW, LoadLibraryExW, VirtualProtect...) sans arrêter le programme |
| `trace_to_json.py cible.exe --steps 20000 --out dossier` | enregistre une trace depuis le point d'entrée, l'exporte en JSON/CSV et affiche des statistiques |
| `dump_memory.py --target cible.exe --addr "mod.base(cible.exe)" --size "mod.size(cible.exe)" --out m.bin` | sauvegarde une zone mémoire (ou `--pid` pour s'attacher) |
| `step_log.py cible.exe --count 50` | exécute pas à pas et affiche les registres modifiés par chaque instruction |

## Modèles pour headless.exe

```powershell
.\headless\run-headless.ps1 -Template api-log -Target C:\Windows\System32\whoami.exe
.\headless\run-headless.ps1 -Template trace-export -Target .\programme.exe -X64dbgDir C:\chemin\vers\x64dbg\bin
```

Le lanceur remplace `%TARGET%`, `%MODULE%`, `%OUT%` et `%BITS%` dans le modèle, lance `headless.exe -cf` avec un dossier de configuration isolé (les `settingset` du modèle ne modifient pas votre configuration d'x64dbg) et écrit tout dans `out\<modèle>-<date>\` (`script.txt`, `headless.log`, fichiers produits). Un modèle se termine par `log "[template] done"`.

| Modèle | Rôle |
|---|---|
| `api-log` | journalise les appels d'API avec leurs arguments, sans pause |
| `trace-export` | trace 50 000 instructions depuis le point d'entrée et exporte en JSON/CSV (nécessite `TraceExport`) |
| `dump-module` | sauvegarde le module principal (`.mem`) et un minidump complet au point d'entrée |
| `break-on-file` | breakpoint conditionnel (chemin contenant `.txt`) puis actions automatiques : log, sauvegarde de la pile, minidump |

Les modèles utilisent `arg.get(n)` pour lire les arguments : ils fonctionnent en x64 et en x32 (`-Arch x32`).

## Protocole (pour d'autres langages)

Une requête JSON par ligne, une réponse JSON par ligne :

```
→ {"id": 1, "method": "mem_read", "params": {"addr": "rsp", "size": 16}}
← {"id": 1, "result": "00000000000000009512A857F77F0000"}
← {"id": 2, "error": "cannot read memory"}
```

Méthodes : `ping`, `cmd`, `eval`, `state`, `wait`, `run`, `pause`, `step_into`, `step_over`, `step_out`, `regs`, `reg_get`, `reg_set`, `mem_read`, `mem_write`, `mem_valid`, `disasm` (voir `src/api.cpp`). Les adresses et registres sont renvoyés en chaînes hexadécimales (`"0x7FF6..."`).
