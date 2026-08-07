# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** through **GitHub Security
Advisories / private vulnerability reporting** for this repository.

Do **not** post vulnerabilities publicly before a fix is available.

Do **not** include any of the following in public issues, discussions, or pull
requests:

- Gofigure PINs
- device credentials
- account credentials
- raw device logs or logs containing secrets or identifying network details
- packet captures
- private IP addresses

If a report requires logs, sanitize them first and share them only through a
private channel agreed during coordinated disclosure.

## Supported versions

Security fixes are intended for:

- the current release in the `v0.1.x` line
- the latest published release, if newer

Older releases may not receive fixes.

## Scope notes

- This project targets **owner-authorized devices only**.
- Playback support in this release is **Spotify Connect using Ogg Vorbis up to
  320 kbps**, not Spotify Lossless.
- Firmware compatibility is currently centered on **2go firmware 1.6.1**;
  forcing unsupported firmware may create risk outside supported expectations.
