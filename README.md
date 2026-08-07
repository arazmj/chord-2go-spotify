# Chord 2go Spotify

Packaged CLI installer for adding **Spotify Connect** to a **Chord 2go** on
tested firmware **1.6.1**.

> **Important:** playback is **Spotify Connect using Ogg Vorbis up to 320 kbps**.
> It is **not Spotify Lossless**, does **not** enable private lossless
> experiments, and should not be described as genuine lossless audio.

## Overview

- Repository: `arazmj/chord-2go-spotify`
- Supported host downloads:
  - `chord-2go-spotify-macos-arm64.zip`
  - `chord-2go-spotify-macos-x86_64.zip`
  - `chord-2go-spotify-windows-x86_64.zip`
- CLI commands:
  - `install`
  - `status`
  - `uninstall`
- Tested device firmware: **1.6.1**
- Other firmware: blocked unless you pass **`--force`**, and remains **untested**

## Before you start

- Use this only on a **2go you own or are explicitly authorized to manage**.
- Keep your **computer and 2go on the same LAN**.
- Keep the computer **physically near the 2go for Bluetooth**.
- **Close Gofigure** before running the installer.
- Be ready to enter the **Gofigure PIN**. The common default is **`0000`** if
  you have never changed it.
- Understand the risk: this project changes device behavior and is supplied
  **without warranty**.

## Quick start

Prebuilt downloads are published on
[GitHub Releases](https://github.com/arazmj/chord-2go-spotify/releases).

1. Download the correct ZIP from **GitHub Releases** for your computer:
   - Apple silicon Mac: `chord-2go-spotify-macos-arm64.zip`
   - Intel Mac: `chord-2go-spotify-macos-x86_64.zip`
   - Windows x86-64: `chord-2go-spotify-windows-x86_64.zip`
2. Optionally verify the file against the published **SHA-256 checksum**.
3. Extract the ZIP.
4. Close **Gofigure**.
5. Confirm the computer and 2go are on the **same LAN** and that Bluetooth is
   enabled on the computer.
6. Run the executable:
   - macOS:
     ```bash
     ./chord-2go-spotify install
     ```
   - Windows PowerShell:
     ```powershell
     .\chord-2go-spotify.exe install
     ```
7. Select the detected 2go if more than one is found, enter the Gofigure PIN
   when prompted, and wait for installation verification.
8. In Spotify, choose the new Spotify Connect target and play normally.

> **Again:** this provides **Spotify Connect Ogg Vorbis up to 320 kbps**, not
> Spotify Lossless.

## Building from source

For local development, use **Python 3.11+**:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

On Windows, use `.venv\Scripts\python.exe` in the same commands.

To rebuild the pinned ARM device binary, run:

```bash
scripts/build-librespot.sh dist/librespot-armv7
```

**Zig** and **cargo-zigbuild** are needed only for that ARM payload rebuild
step.

Then assemble the device payload:

```bash
LIBRESPOT_BINARY=dist/librespot-armv7 \
LIBRESPOT_LICENSE=dist/librespot.LICENSE \
scripts/build-payload.sh src/chord_2go_spotify/data/spotify-install.tar.gz
```

To package the desktop CLI with PyInstaller:

```bash
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/pyinstaller --clean --noconfirm chord-2go-spotify.spec
```

## Platform security prompts

### macOS Gatekeeper

Initial releases are expected to be **unsigned**. If macOS warns about the
downloaded app:

1. Verify the GitHub release source and optional checksum.
2. In Finder, right-click the executable and choose **Open**, or use the
   contextual **Open** flow after the warning.
3. Only if needed for the downloaded executable itself, remove the quarantine
   attribute in Terminal:
   ```bash
   xattr -d com.apple.quarantine ./chord-2go-spotify
   ```

Do **not** disable Gatekeeper system-wide.

### Windows SmartScreen

Initial releases are expected to be **unsigned**. If SmartScreen appears:

1. Verify the GitHub release source and optional checksum.
2. Choose **More info** and then **Run anyway** for that downloaded executable
   only if you trust the release.

Do **not** disable SmartScreen or broader Windows protections.

## Permissions and connectivity

The CLI needs:

- **Bluetooth access** to find and authenticate with the 2go
- **Local network access** so the computer can reach the 2go on your LAN
- **Firewall permission** for the transfer and callback flow used during
  installation

Typical prompts:

- **macOS:** allow **Bluetooth** and **Local Network** access if prompted.
- **Windows:** allow **Bluetooth** access and approve any **private-network
  firewall** prompt needed for the transfer step.

If discovery or transfer fails:

- keep the computer near the 2go;
- confirm both are on the same subnet/LAN;
- allow the app through local firewall prompts;
- reopen Bluetooth if the OS denied it;
- close Gofigure and retry.

## Compatibility and firmware policy

| Item | Status |
| --- | --- |
| Chord 2go firmware 1.6.1 | Tested |
| Other firmware versions | Require `--force`; untested |
| Host platforms | macOS Intel, macOS Apple silicon, Windows x86-64 |

`--force` is for advanced users who accept the risk of untested firmware
behavior. If your 2go firmware changes, compatibility may break without notice.

## What `install` does

`install`:

- discovers nearby 2go devices over Bluetooth;
- reads model, firmware, and LAN details;
- blocks unsupported firmware unless `--force` is used;
- transfers and installs the packaged integration;
- verifies service state before reporting success.

During Spotify playback, the integration temporarily pauses or hands off audio
used by other services such as **Roon, AirPlay, DLNA/MPD, and Bluetooth**, then
restores normal behavior afterward.

The installed service is intended to **persist across reboots** until you remove
it with `uninstall` or a future firmware change overwrites compatibility.

## Status, uninstall, and recovery

### `status`

Use `status` to check:

- whether the detected firmware is supported;
- whether the integration appears installed;
- whether the Spotify-related service is active.

Examples:

```bash
./chord-2go-spotify status
```

```powershell
.\chord-2go-spotify.exe status
```

### `uninstall`

Use `uninstall` to remove the project-owned integration and restore prior
service state as closely as possible.

```bash
./chord-2go-spotify uninstall
```

```powershell
.\chord-2go-spotify.exe uninstall
```

### Recovery

If something goes wrong:

1. Run `status`.
2. Retry `install` if the first attempt was interrupted.
3. Run `uninstall` to remove this integration.
4. Reboot the 2go and your computer if Bluetooth or service state seems stuck.
5. Reopen your usual playback apps only after the device is stable again.

## Firmware update warning

**Uninstall before updating 2go firmware.** Firmware updates may overwrite,
break, or invalidate the integration. Reinstall only after compatibility with
the new firmware has been confirmed publicly for this project.

## Safety, warranty, and legal notices

- This project is provided **as-is, without warranty of any kind**.
- Installing it may interrupt playback, require recovery work, or leave the
  device in a state that needs manual troubleshooting.
- Use it only on **devices you own or are authorized to administer**.
- You must use your **own Spotify account** and remain responsible for
  complying with Spotify's terms and policies.
- **Chord**, **2go**, **Gofigure**, and **Spotify** are trademarks of their
  respective owners.
- This project is **not affiliated with, endorsed by, sponsored by, or approved
  by Chord Electronics Ltd. or Spotify AB**.

## License

Original installer and integration code in this repository is released under
the **MIT License**. See [LICENSE](LICENSE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
