# PE-sieve

PE-sieve est un outil open-source par [hasherezade](https://github.com/hasherezade/pe-sieve) qui scanne un processus Windows en cours d'exécution pour détecter des **anomalies PE in-memory** : code injecté, modules remplacés (process hollowing), hooks sur des API, pages exécutables non référencées par le PE d'origine, etc. Il peut dumper les modules suspects pour analyse ultérieure.

Version packagée ici : **v0.4.1.1** (release de septembre 2025).

## Fichiers de ce dossier

| Fichier | Rôle |
|---|---|
| `pe-sieve64.exe` | pour scanner des processus 64 bits |
| `pe-sieve32.exe` | pour scanner des processus 32 bits |

Utilisez la variante correspondant à l'architecture du processus cible, pas à l'OS.

## Usage de base

Depuis ce dossier :

```powershell
# Lister les options
.\pe-sieve64.exe --help

# Scanner un processus par PID (sortie dans un dossier timestampé)
.\pe-sieve64.exe /pid 1234

# Scanner et dumper tous les modules modifiés
.\pe-sieve64.exe /pid 1234 /dmode 3

# Mode « quiet » pour un rapport JSON pur
.\pe-sieve64.exe /pid 1234 /json /quiet
```

Les résultats atterrissent dans `process_<pid>\` à côté de l'exe, avec un `summary.json` récapitulatif.

## Intégration avec x64dbg

PE-sieve est un exécutable standalone — vous le lancez à côté d'x64dbg quand vous voulez vérifier l'intégrité mémoire du processus débogué. Depuis le pybridge Python :

```python
import subprocess
from x64dbg_bridge import Debugger

with Debugger() as dbg:
    dbg.init(r"C:\path\target.exe")
    dbg.run(wait=True)                    # jusqu'au premier breakpoint
    pid = dbg.eval("$pid")
    out = subprocess.run(
        [r"<X64dbgDir>\tools\pesieve\pe-sieve64.exe", "/pid", str(pid), "/json", "/quiet"],
        capture_output=True, text=True,
    )
    print(out.stdout)
```

Utile pour détecter si une cible a déjà déballé/injecté du code au moment où un breakpoint tombe.

## Documentation complète

<https://github.com/hasherezade/pe-sieve/wiki>

## Licence

BSD-2-Clause.
