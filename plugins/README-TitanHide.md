# TitanHide

TitanHide est un **driver noyau** (open-source, maintenu par mrexodia) qui masque la présence d'un débogueur à certaines sondes Windows plus profondes que ce que ScyllaHide peut couvrir (hooks SSDT, interception de `NtQueryInformationProcess`, `NtClose`, `NtGetContextThread`, protection des registres DRx, etc.).

Source : <https://github.com/mrexodia/TitanHide>

Version packagée ici : **v0019** (release officielle de juin 2025).

## ⚠️ Prérequis importants

**Avant même de télécharger**, Windows Defender (et beaucoup d'autres AV) classifie `TitanHide.sys` comme **HackTool** et met le ZIP en quarantaine dès le téléchargement. Pour que `install-plugins.ps1 -Plugins TitanHide` fonctionne, ajoutez une exclusion sur son dossier temporaire :

```powershell
# PowerShell admin, exclut le dossier temp utilisé par install-plugins.ps1
Add-MpPreference -ExclusionPath $env:TEMP
# OU plus restreint, juste le dossier d'install final :
Add-MpPreference -ExclusionPath "<x64dbg>\titanhide"
```

Ce choix de désactiver une détection AV vous engage : TitanHide est open-source et vérifié par SHA-256, mais vous assumez que votre machine est un environnement RE/CTF où un driver anti-debug est acceptable. Sur une machine de travail ordinaire, **n'activez pas d'exclusion**.

TitanHide est un driver noyau non signé pour les systèmes modernes. Pour qu'il tourne ensuite, vous devez **tous les deux** :

1. **Désactiver PatchGuard** — le mécanisme Windows qui bloque les hooks SSDT. Sans cette étape, charger TitanHide provoque un BSOD `0x109 CRITICAL_STRUCTURE_CORRUPTION`. Outils possibles ([EfiGuard](https://github.com/Mattiwatti/EfiGuard), [SandboxBootkit](https://github.com/thesecretclub/SandboxBootkit), …) — tous ces outils modifient le démarrage de Windows et exposent la machine à des changements système sérieux.
2. **Activer test-signing** pour charger le driver :
   ```
   bcdedit /set testsigning on
   ```
   Puis **redémarrer**. Un filigrane permanent apparaîtra sur le bureau. Certains services (Netflix, apps bancaires, DRM) refusent de tourner dans ce mode.

**Si vous ne comprenez pas pleinement ces prérequis, utilisez ScyllaHide à la place** — l'auteur de TitanHide le dit explicitement dans son README. Pour l'immense majorité des cibles (y compris les packers courants, voir les profils de `scylla_hide.ini`), ScyllaHide est suffisant.

## Installation du driver (après avoir compris et activé les prérequis)

Depuis une invite de commande **administrateur**, dans ce dossier :

```
copy TitanHide.sys %systemroot%\system32\drivers\
sc create TitanHide binPath= %systemroot%\system32\drivers\TitanHide.sys type= kernel
sc start TitanHide
sc query TitanHide
```

Pour vérifier qu'il tourne : `C:\TitanHide.log` doit se remplir, ou utilisez [DebugView](https://technet.microsoft.com/en-us/sysinternals/debugview.aspx).

**Pour VMProtect ≥ 3.9.4**, renommez le service pour échapper à la détection :

```
sc create NotTitanHide ...
```

Puis, dans x64dbg : `TitanHideName NotTitanHide`.

## Installation du plugin x64dbg

Déjà fait par `install-plugins.ps1` : `TitanHide.dp32` et `TitanHide.dp64` sont dans `x32\plugins\` et `x64\plugins\`. Au chargement, le plugin détecte automatiquement si le driver est présent.

## Fichiers de ce dossier

| Fichier | Rôle |
|---|---|
| `TitanHide.sys` | driver noyau (29 KB) |
| `TitanHide.cer` | certificat auto-signé utilisé pour signer `TitanHide.sys` |
| `TitanHideGUI-x64.exe` | GUI de pilotage (64 bits) |
| `TitanHideGUI-x32.exe` | GUI de pilotage (32 bits) |

## Désinstallation

```
sc stop TitanHide
sc delete TitanHide
del %systemroot%\system32\drivers\TitanHide.sys
```

Puis (facultatif) `bcdedit /set testsigning off`, et désactivation du bypass PatchGuard selon l'outil utilisé.

## Licence

TitanHide est publié sous licence BSD-3-Clause par mrexodia et contributeurs.
