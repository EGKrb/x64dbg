# x64dbg (fork EGKrb) %VERSION%

Fork non officiel de x64dbg : <https://github.com/EGKrb/x64dbg>
Commit : `%COMMIT%`

## Démarrer

- `x96dbg.exe` : lanceur (choisit 32/64 bits, peut enregistrer le menu contextuel de l'Explorateur).
- `x64\x64dbg.exe` : programmes 64 bits. `x32\x32dbg.exe` : programmes 32 bits.
- `x64\headless.exe` / `x32\headless.exe` : x64dbg sans interface, piloté par script (`-cf script.txt`) ou par Python.

Le dossier doit être dans un emplacement où vous avez le droit d'écrire (pas `C:\Program Files`) : la configuration et les bases de données sont enregistrées à côté des exécutables.

## Plugins inclus

| Plugin | Rôle |
|---|---|
| ScyllaHide | masque le débogueur aux protections anti-debug (menu Plugins > ScyllaHide > Options). Le profil actif par défaut est « VMProtect x86/x64 » ; choisissez « Basic » pour un programme non protégé si celui-ci se comporte mal |
| xAnalyzer | analyse automatique : arguments des appels d'API commentés dans le désassemblage (définitions dans `plugins\apis_def`) |
| pybridge | pilotage depuis Python (`pybridge\README.md`) |

**OllyDumpEx** (dump de processus en PE) n'a pas de licence de redistribution : installez-le avec

```powershell
powershell -ExecutionPolicy Bypass -File .\install-plugins.ps1 -Plugins OllyDumpEx
```

## Nouveautés par rapport à x64dbg officiel

- Commande `TraceExport` : convertit une trace (`.trace64`/`.trace32`) en JSON ou CSV.
  ```
  TraceExport "C:\traces\cible.trace64", "C:\traces\cible.json"
  ```
- `pybridge\python\x64dbg_bridge.py` : client Python (breakpoints, pas à pas, registres, mémoire, traces).
- `pybridge\headless\run-headless.ps1` : modèles de scripts prêts à l'emploi (journal d'API, trace + export, dump, breakpoint conditionnel).

Documentation complète : <https://github.com/EGKrb/x64dbg#readme>
Licences : dossier `licenses\` (x64dbg et ScyllaHide : GPL-3.0, xAnalyzer : MIT).
