# x64dbg EGKrb 2026.10.04.3

Fork **EGKrb/x64dbg** — scripts Python anti-anti-debugging pour pybridge.

## Nouveautés

### Scripts anti-anti-debug (`pybridge/examples/`)

Six nouveaux exemples ajoutés :

- **`rdtsc_hook.py`** — pose des breakpoints non-bloquants sur `GetTickCount`, `GetTickCount64`, `RtlGetTickCount` et `NtQueryPerformanceCounter` pour forcer le retour à 0, neutralisant les timing checks.

  ```powershell
  py pybridge\examples\rdtsc_hook.py C:\path\target.exe --timeout 30
  ```

- **`find_bytecode.py`** — scanne la mémoire pour trouver des prologues de handlers de VM custom (patterns `mov reg,[rip+disp]; test reg,reg; jz`). Utile pour les interpréteurs de bytecode qui ne flippent pas de buffer en `PAGE_EXECUTE_*`.

  ```powershell
  py pybridge\examples\find_bytecode.py C:\path\target.exe --pause-at-entry
  ```

- **`tls_logger.py`** — énumère les TLS callbacks du module principal via `mod.tlscallbackcount` / `mod.tlscallback` et installe un breakpoint de log non-bloquant sur chacun.

  ```powershell
  py pybridge\examples\tls_logger.py C:\path\target.exe --timeout 30
  ```

- **`exception_handler.py`** — configure le filtre d'exceptions x64dbg pour passer `STATUS_BREAKPOINT`, `STATUS_ILLEGAL_INSTRUCTION`, `STATUS_PRIVILEGED_INSTRUCTION` et `STATUS_WX86_BREAKPOINT` directement au debuggee sans pause.

  ```powershell
  py pybridge\examples\exception_handler.py C:\path\target.exe --timeout 30
  ```

- **`integrity_check.py`** — snapshot SHA-256 du module principal à l'entry point, puis après un délai de runtime. Détecte le code auto-modifiant.

  ```powershell
  py pybridge\examples\integrity_check.py C:\path\target.exe --timeout 30
  ```

- **`process_check.py`** — scan local Toolhelp (sans target) qui affiche les processus qu'un protecteur détecterait (x64dbg, IDA, Ghidra, Frida, Wireshark, etc.).

  ```powershell
  py pybridge\examples\process_check.py
  ```

Tous les scripts suivent le pattern `_common.py` existant (`base_parser`, `launch`, `run_to_entry`) et sont compatibles x64/x32.

## Checksums

Voir `SHA256SUMS.txt`.
