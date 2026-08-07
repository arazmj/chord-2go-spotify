# Third-Party Notices

This repository includes or packages original code under the MIT License and
depends on third-party open-source components. Spotify Connect playback in this
project is **Ogg Vorbis up to 320 kbps**, not Spotify Lossless.

## Included or packaged components

### librespot

- Project: librespot
- Upstream: <https://github.com/librespot-org/librespot>
- Pinned source for the initial public release:
  - version `0.8.0`
  - commit `d36f9f1907e8cc9d68a93f8ebc6b627b1bf7267d`
- License: MIT
- Role: device-side Spotify Connect client used for Ogg Vorbis playback up to
  320 kbps

### Bleak

- Project: Bleak
- Upstream: <https://github.com/hbldh/bleak>
- License: MIT
- Role: host-side Bluetooth Low Energy communication

### PyInstaller

- Project: PyInstaller
- Upstream: <https://github.com/pyinstaller/pyinstaller>
- License: GPLv2-or-later with a special bootloader exception
- Role: packaging the public CLI executables for macOS and Windows

## License summary

- Original repository code: MIT
- librespot: MIT
- Bleak: MIT
- PyInstaller: GPLv2-or-later with its documented exception for bundled apps

Users and redistributors should review upstream repositories for full license
texts, notices, and any additional dependency obligations that apply to the
exact shipped release artifacts.

## Trademarks and affiliation

Spotify, Chord, 2go, and Gofigure are trademarks of their respective owners.
This project is not affiliated with, endorsed by, or sponsored by those
companies.
