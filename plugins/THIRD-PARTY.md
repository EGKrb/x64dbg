# Plugins tiers

Ces plugins ne sont pas développés dans ce dépôt. `install-plugins.ps1` les télécharge depuis leur source officielle et vérifie leur empreinte SHA-256.

| Plugin | Version | Auteur | Licence | Source | Dans la release |
|---|---|---|---|---|---|
| ScyllaHide | v1.4 (2023-03-24) | x64dbg / NtQuery | GPL-3.0 | <https://github.com/x64dbg/ScyllaHide> (code source de cette version : <https://github.com/x64dbg/ScyllaHide/tree/v1.4>) | oui |
| xAnalyzer | 2.5.12 (2025-08-13) | ThunderCls | MIT | <https://github.com/ThunderCls/xAnalyzer> | oui |
| OllyDumpEx | v1.86 (2024-10-04) | Low Priority | aucune licence publiée (freeware, code fermé) | <https://low-priority.appspot.com/ollydumpex/> | **non** : sans licence de redistribution, il est téléchargé chez l'utilisateur par `install-plugins.ps1` |

Les textes des licences sont dans le dossier `licenses/` de la release.

## Bibliothèques du visualiseur de dumps (`x64\minidump.exe`)

Compilées dans le visualiseur par `tools/build-minidump-viewer.ps1` (versions de `src/cross/vendor/cmake.toml`) :

| Bibliothèque | Version | Licence |
|---|---|---|
| [udmp-parser](https://github.com/0vercl0k/udmp-parser) | `2fff7ac` | MIT |
| [cpp-httplib](https://github.com/yhirose/cpp-httplib) | v0.25.0 | MIT |
| [linux-pe](https://github.com/can1357/linux-pe) | `1fcb057` | BSD-2-Clause |
| [nlohmann/json](https://github.com/nlohmann/json) | v3.12.0 | MIT |

## Empreintes SHA-256 des fichiers téléchargés

| Fichier | SHA-256 |
|---|---|
| `ScyllaHide_2023-03-24_13-03.zip` | `edeb0dd203fd1ef38e1404e8a1bd001e05c50b6096e49533f546d13ffdcb7404` |
| `xAnalyzer.dp32` | `ec586fdc19e87656a630c8b4359495e0a5dc4d29bf0bb0781c4ae907efbe8a08` |
| `xAnalyzer.dp64` | `8240a3ca76b21f4181fef0b047521177a5cbff13b9760340a35848b782b38117` |
| `apis_def.zip` (xAnalyzer) | `606c9b3144de24878817fcf8391e399ce00c67651abe85373358db9195aa47f1` |
| `OllyDumpEx.zip` | `3b39e7d8d0b8d1c1407ec93531f2a35fd57ee7d26d4ce71cdc1dc3d9d766f758` |
