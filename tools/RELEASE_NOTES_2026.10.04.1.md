# x64dbg EGKrb 2026.10.04.1

Fork **EGKrb/x64dbg** — ajout d'un workflow automatisé de dump mémoire pour analyses de packers.

## Nouveautés

### Dump automatique des régions flipped en PAGE_EXECUTE*

Deux outils ajoutés qui attrapent le moment où un packer rend exécutable un buffer déchiffré :

- **`pybridge/examples/unpack_dump.py`** — pose un breakpoint conditionnel sur `kernelbase.VirtualProtect`, filtré sur `(arg.get(2) & 0xF0) != 0` (couvre `PAGE_EXECUTE`, `PAGE_EXECUTE_READ`, `PAGE_EXECUTE_READWRITE`, `PAGE_EXECUTE_WRITECOPY`). À chaque hit, lit `lpAddress` et `dwSize` depuis les arguments de la calling convention en vigueur (`arg_register`), puis dump la plage à un fichier horodaté dans `--out-dir` via `Debugger.dump_memory()`. Options : `--max-hits`, `--min-size`, `--timeout`, `--api VirtualProtectEx`. Compatible x64 et x32.

  ```powershell
  py pybridge\examples\unpack_dump.py C:\samples\packed.exe --out-dir dumps --max-hits 10
  ```

- **`pybridge/headless/templates/unpack-dump.txt`** — même filtre, pour `headless.exe`. Log chaque appel via `bplog` et dump la **dernière** région dans `%OUT%\vprotect-last.bin` via `bpcmd + savedata`. Limitation documentée : `savedata` dans un `bpcmd` headless n'accepte pas de nom dynamique, donc seule la dernière région persiste sur disque. Pour un dump par appel, utiliser l'exemple Python.

  ```powershell
  .\pybridge\headless\run-headless.ps1 -Template unpack-dump -Target C:\samples\packed.exe
  ```

Les deux sont intégrés automatiquement au bundle par `tools/make-release.ps1` (copie récursive de `examples/` et `headless/`).

## Checksums

Voir `SHA256SUMS.txt`.
