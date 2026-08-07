from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_DIR = REPO_ROOT / "payload"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build-payload.sh"
WORK_ROOT = REPO_ROOT / ".test-work"
REPO_LICENSE_TEXT = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
REPO_THIRD_PARTY_NOTICES_TEXT = (REPO_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
LIBRESPOT_LICENSE_NAME = "librespot-LICENSE"
PROJECT_LICENSE_NAME = "chord-2go-spotify-LICENSE"
THIRD_PARTY_NOTICES_NAME = "chord-2go-spotify-THIRD_PARTY_NOTICES.md"
DOCS_DIR = Path("/usr/local/share/doc/chord-2go-spotify")
DEDICATED_CACHE_DIR = Path("/var/cache/chord-2go-spotify")
LEGACY_CACHE_DIR = Path("/var/cache/librespot")

SHELL_SCRIPTS = [
    PAYLOAD_DIR / "install.sh",
    PAYLOAD_DIR / "uninstall.sh",
    PAYLOAD_DIR / "librespot-aplay",
    PAYLOAD_DIR / "librespot-audio",
    BUILD_SCRIPT,
]

EXPECTED_ARCHIVE_NAMES = {
    PROJECT_LICENSE_NAME,
    THIRD_PARTY_NOTICES_NAME,
    "install.sh",
    "librespot",
    LIBRESPOT_LICENSE_NAME,
    "librespot-aplay",
    "librespot-audio",
    "librespot.service",
    "uninstall.sh",
}
INSTALL_SUCCESS_MARKER = "CHORD_2GO_SPOTIFY_INSTALL_SUCCESS"


class PayloadTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.work = WORK_ROOT / self._testMethodName
        if self.work.exists():
            shutil.rmtree(self.work)
        self.work.mkdir(parents=True)
        self.addCleanup(self._cleanup_work)

    def _cleanup_work(self) -> None:
        if self.work.exists():
            shutil.rmtree(self.work)
        if WORK_ROOT.exists() and not any(WORK_ROOT.iterdir()):
            WORK_ROOT.rmdir()

    def run_command(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        check: bool = True,
        input_text: str = "",
    ) -> subprocess.CompletedProcess[str]:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        completed = subprocess.run(
            args,
            cwd=str(cwd or REPO_ROOT),
            env=merged_env,
            input=input_text,
            text=True,
            capture_output=True,
        )
        if check and completed.returncode != 0:
            self.fail(
                f"command failed: {args}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        return completed

    def write_file(self, path: Path, content: str, mode: int | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if mode is not None:
            path.chmod(mode)

    def make_payload_tree(self) -> Path:
        payload_copy = self.work / "payload"
        shutil.copytree(PAYLOAD_DIR, payload_copy)
        self.write_file(
            payload_copy / "librespot",
            "#!/bin/sh\necho stable librespot\n",
            0o755,
        )
        self.write_file(
            payload_copy / LIBRESPOT_LICENSE_NAME,
            "Upstream librespot license text\n",
            0o644,
        )
        self.write_file(
            payload_copy / PROJECT_LICENSE_NAME,
            "Project license text\n",
            0o644,
        )
        self.write_file(
            payload_copy / THIRD_PARTY_NOTICES_NAME,
            "Third-party notices text\n",
            0o644,
        )
        return payload_copy

    def make_harness(
        self,
        *,
        active_units: tuple[str, ...] = (),
        enabled_units: tuple[str, ...] = (),
        fail_markers: tuple[str, ...] = (),
        include_sha256sum: bool = False,
        include_failing_cksum: bool = False,
    ) -> tuple[Path, dict[str, str]]:
        fakeroot = self.work / "fakeroot"
        tools = self.work / "tools"
        state_dir = self.work / "harness-state"
        log_dir = self.work / "logs"
        for path in (fakeroot, tools, state_dir, log_dir):
            path.mkdir(parents=True, exist_ok=True)

        (state_dir / "active").write_text(
            "\n".join(active_units) + ("\n" if active_units else ""),
            encoding="utf-8",
        )
        (state_dir / "enabled").write_text(
            "\n".join(enabled_units) + ("\n" if enabled_units else ""),
            encoding="utf-8",
        )
        (state_dir / "fail").write_text(
            "\n".join(fail_markers) + ("\n" if fail_markers else ""),
            encoding="utf-8",
        )

        systemctl_script = textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import os
            import sys
            from pathlib import Path

            state = Path(os.environ["FAKE_SYSTEMCTL_STATE"])
            state.mkdir(parents=True, exist_ok=True)
            log_path = state / "systemctl.log"
            args = sys.argv[1:]
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(" ".join(args) + "\\n")

            def load(name: str) -> set[str]:
                path = state / name
                if not path.exists():
                    return set()
                return {line for line in path.read_text(encoding="utf-8").splitlines() if line}

            def save(name: str, values: set[str]) -> None:
                path = state / name
                text = "\\n".join(sorted(values))
                if text:
                    text += "\\n"
                path.write_text(text, encoding="utf-8")

            if not args:
                sys.exit(1)

            command = args[0]
            options = [arg for arg in args[1:] if arg.startswith("-")]
            units = [arg for arg in args[1:] if not arg.startswith("-")]
            unit = units[0] if units else ""
            fail = load("fail")
            key = f"{command}:{unit}" if unit else command
            if key in fail or command in fail:
                sys.exit(1)

            active = load("active")
            enabled = load("enabled")

            if command == "daemon-reload":
                sys.exit(0)
            if command == "is-active":
                sys.exit(0 if unit in active else 3)
            if command == "is-enabled":
                sys.exit(0 if unit in enabled else 1)
            if command in {"start", "restart"}:
                active.add(unit)
                save("active", active)
                sys.exit(0)
            if command == "stop":
                active.discard(unit)
                save("active", active)
                sys.exit(0)
            if command == "enable":
                enabled.add(unit)
                save("enabled", enabled)
                sys.exit(0)
            if command == "disable":
                enabled.discard(unit)
                if "--now" in options:
                    active.discard(unit)
                    save("active", active)
                save("enabled", enabled)
                sys.exit(0)

            sys.exit(0)
            """
        )
        self.write_file(tools / "systemctl", systemctl_script, 0o755)

        logger_script = "#!/bin/sh\nset -eu\nprintf '%s\\n' \"$*\" >> \"$FAKE_LOGGER_LOG\"\n"
        mpc_script = "#!/bin/sh\nset -eu\nprintf '%s\\n' \"$*\" >> \"$FAKE_MPC_LOG\"\n"
        aplay_script = "#!/bin/sh\nset -eu\nprintf '%s\\n' \"$*\" >> \"$FAKE_APLAY_LOG\"\ncat >/dev/null\n"
        self.write_file(tools / "logger", logger_script, 0o755)
        self.write_file(tools / "mpc", mpc_script, 0o755)
        self.write_file(tools / "aplay", aplay_script, 0o755)

        if include_sha256sum:
            sha256sum_script = textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import hashlib
                import sys
                from pathlib import Path

                if len(sys.argv) != 2:
                    sys.exit(1)

                target = Path(sys.argv[1])
                print(f"{hashlib.sha256(target.read_bytes()).hexdigest()}  {target}")
                """
            )
            self.write_file(tools / "sha256sum", sha256sum_script, 0o755)

        if include_failing_cksum:
            cksum_script = "#!/bin/sh\nset -eu\nprintf 'cksum invoked\\n' >> \"$FAKE_CKSUM_LOG\"\nexit 127\n"
            self.write_file(tools / "cksum", cksum_script, 0o755)

        env = {
            "CHORD_2GO_SPOTIFY_ROOT": str(fakeroot),
            "SYSTEMCTL": str(tools / "systemctl"),
            "LOGGER_CMD": str(tools / "logger"),
            "MPC_CMD": str(tools / "mpc"),
            "APLAY_CMD": str(tools / "aplay"),
            "FAKE_SYSTEMCTL_STATE": str(state_dir),
            "FAKE_LOGGER_LOG": str(log_dir / "logger.log"),
            "FAKE_MPC_LOG": str(log_dir / "mpc.log"),
            "FAKE_APLAY_LOG": str(log_dir / "aplay.log"),
            "FAKE_CKSUM_LOG": str(log_dir / "cksum.log"),
            "PATH": f"{tools}{os.pathsep}{os.environ.get('PATH', '')}",
        }
        return fakeroot, env

    def parse_manifest(self, manifest_path: Path) -> dict[str, tuple[str, str, str]]:
        result: dict[str, tuple[str, str, str]] = {}
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            path, kind, backup, fingerprint = line.split("|")
            result[path] = (kind, backup, fingerprint)
        return result

    def parse_original_service_state(self, state_path: Path) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in state_path.read_text(encoding="utf-8").splitlines():
            key, value = line.split("=", 1)
            result[key] = value
        return result

    def read_systemctl_units(self, filename: str) -> set[str]:
        path = self.work / "harness-state" / filename
        if not path.exists():
            return set()
        return {line for line in path.read_text(encoding="utf-8").splitlines() if line}

    def test_shell_syntax_is_valid(self) -> None:
        self.run_command(
            ["sh", "-n", *[str(path) for path in SHELL_SCRIPTS]],
            cwd=REPO_ROOT,
        )

    def test_service_and_wrappers_are_stable_ogg_only(self) -> None:
        service = (PAYLOAD_DIR / "librespot.service").read_text(encoding="utf-8")
        self.assertIn("--name Chord-2go-Spotify", service)
        self.assertIn("--backend subprocess", service)
        self.assertIn("--device /usr/local/bin/librespot-aplay", service)
        self.assertIn("--format S32", service)
        self.assertIn("--bitrate 320", service)
        self.assertIn("--initial-volume 50", service)
        self.assertIn("--cache /var/cache/chord-2go-spotify", service)
        self.assertIn("--onevent /usr/local/sbin/librespot-audio", service)
        self.assertIn("--emit-sink-events", service)
        self.assertNotIn("/var/cache/librespot", service)
        self.assertNotIn("lossless", service)
        self.assertNotIn("PlayPlay", service)

        wrapper = (PAYLOAD_DIR / "librespot-aplay").read_text(encoding="utf-8")
        self.assertIn("-f S32_LE -c 2 -r 44100 -t raw", wrapper)
        self.assertIn("soundcard", wrapper)

        audio = (PAYLOAD_DIR / "librespot-audio").read_text(encoding="utf-8")
        for unit in ("upmpdcli", "mpd-sdhc", "mpd-scsi", "raat", "shairport-sync", "bluealsa"):
            self.assertIn(unit, audio)
        self.assertIn("LOCK_DIR=/run/librespot-audio.lock", audio)
        self.assertNotIn("--bitrate lossless", audio)

    def test_audio_helper_acquire_and_release(self) -> None:
        fakeroot, env = self.make_harness(active_units=("upmpdcli", "raat"))
        self.run_command(["sh", str(PAYLOAD_DIR / "librespot-audio"), "acquire"], env=env)

        state_file = fakeroot / "run/librespot-services"
        self.assertTrue(state_file.exists())
        self.assertEqual(state_file.read_text(encoding="utf-8").splitlines(), ["upmpdcli", "raat"])
        systemctl_log = (self.work / "harness-state/systemctl.log").read_text(encoding="utf-8")
        self.assertIn("stop upmpdcli", systemctl_log)
        self.assertIn("stop raat", systemctl_log)
        mpc_log = (self.work / "logs/mpc.log").read_text(encoding="utf-8")
        self.assertIn("stop", mpc_log)

        self.run_command(["sh", str(PAYLOAD_DIR / "librespot-audio"), "release"], env=env)
        self.assertFalse(state_file.exists())
        systemctl_log = (self.work / "harness-state/systemctl.log").read_text(encoding="utf-8")
        self.assertIn("start upmpdcli", systemctl_log)
        self.assertIn("start raat", systemctl_log)

    def test_aplay_wrapper_uses_soundcard_s32(self) -> None:
        fakeroot, env = self.make_harness()
        installed_helper = fakeroot / "usr/local/sbin/librespot-audio"
        self.write_file(
            installed_helper,
            (PAYLOAD_DIR / "librespot-audio").read_text(encoding="utf-8"),
            0o755,
        )
        self.run_command(
            ["sh", str(PAYLOAD_DIR / "librespot-aplay")],
            env=env,
        )
        aplay_log = (self.work / "logs/aplay.log").read_text(encoding="utf-8")
        self.assertIn("-q -D soundcard -f S32_LE -c 2 -r 44100 -t raw", aplay_log)

    def test_install_and_uninstall_are_transactional_and_targeted(self) -> None:
        payload_copy = self.make_payload_tree()
        fakeroot, env = self.make_harness()

        self.write_file(
            fakeroot / "usr/local/bin/librespot",
            "#!/bin/sh\necho original librespot\n",
            0o755,
        )
        self.write_file(
            fakeroot / "etc/systemd/system/librespot.service",
            "original service\n",
            0o644,
        )
        self.write_file(
            fakeroot / "usr/local/libexec/librespot-playplay",
            "#!/bin/sh\necho legacy\n",
            0o755,
        )
        self.write_file(
            fakeroot / "usr/local/share/doc/librespot-playplay/LICENSE",
            "legacy license\n",
            0o644,
        )
        self.write_file(
            fakeroot / "usr/local/share/doc/librespot-playplay/source.tar.gz",
            "legacy source\n",
            0o644,
        )
        self.write_file(
            fakeroot / "usr/local/share/doc/librespot-playplay/notes.txt",
            "leave me alone\n",
            0o644,
        )
        self.write_file(
            fakeroot / "usr/local/sbin/uninstall-2go-spotify",
            "#!/bin/sh\necho legacy uninstall\n",
            0o755,
        )
        self.write_file(
            fakeroot / "usr/local/sbin/rollback-2go-spotify-lossless",
            "#!/bin/sh\necho legacy rollback\n",
            0o755,
        )
        self.write_file(
            fakeroot / "var/cache/librespot/existing-cache-marker",
            "preserve me\n",
            0o644,
        )

        result = self.run_command(["sh", str(payload_copy / "install.sh")], cwd=payload_copy, env=env)
        self.assertEqual(result.stdout.strip(), INSTALL_SUCCESS_MARKER)

        installed_service = fakeroot / "etc/systemd/system/librespot.service"
        self.assertIn("--bitrate 320", installed_service.read_text(encoding="utf-8"))
        self.assertNotIn("lossless", installed_service.read_text(encoding="utf-8"))
        self.assertEqual(
            stat.S_IMODE((fakeroot / "usr/local/bin/librespot").stat().st_mode),
            0o755,
        )
        self.assertEqual(
            stat.S_IMODE((fakeroot / "usr/local/sbin/uninstall-chord-2go-spotify").stat().st_mode),
            0o755,
        )
        self.assertEqual(
            stat.S_IMODE((fakeroot / DOCS_DIR.relative_to("/") / LIBRESPOT_LICENSE_NAME).stat().st_mode),
            0o644,
        )
        self.assertEqual(
            stat.S_IMODE((fakeroot / DOCS_DIR.relative_to("/") / PROJECT_LICENSE_NAME).stat().st_mode),
            0o644,
        )
        self.assertEqual(
            stat.S_IMODE((fakeroot / DOCS_DIR.relative_to("/") / THIRD_PARTY_NOTICES_NAME).stat().st_mode),
            0o644,
        )
        self.assertEqual(
            (fakeroot / DOCS_DIR.relative_to("/") / LIBRESPOT_LICENSE_NAME).read_text(encoding="utf-8"),
            "Upstream librespot license text\n",
        )
        self.assertEqual(
            (fakeroot / DOCS_DIR.relative_to("/") / PROJECT_LICENSE_NAME).read_text(encoding="utf-8"),
            "Project license text\n",
        )
        self.assertEqual(
            (fakeroot / DOCS_DIR.relative_to("/") / THIRD_PARTY_NOTICES_NAME).read_text(encoding="utf-8"),
            "Third-party notices text\n",
        )
        self.assertTrue((fakeroot / DEDICATED_CACHE_DIR.relative_to("/")).is_dir())
        self.assertTrue((fakeroot / LEGACY_CACHE_DIR.relative_to("/") / "existing-cache-marker").exists())

        manifest = self.parse_manifest(fakeroot / "var/lib/chord-2go-spotify/manifest.tsv")
        self.assertEqual(manifest["/usr/local/bin/librespot"][0], "backup")
        self.assertEqual(manifest["/etc/systemd/system/librespot.service"][0], "backup")
        self.assertEqual(manifest["/usr/local/bin/librespot-aplay"][0], "created")
        self.assertEqual(manifest["/usr/local/sbin/librespot-audio"][0], "created")
        self.assertEqual(manifest["/usr/local/sbin/uninstall-chord-2go-spotify"][0], "created")
        self.assertEqual(manifest[str(DOCS_DIR / LIBRESPOT_LICENSE_NAME)][0], "created")
        self.assertEqual(manifest[str(DOCS_DIR / PROJECT_LICENSE_NAME)][0], "created")
        self.assertEqual(manifest[str(DOCS_DIR / THIRD_PARTY_NOTICES_NAME)][0], "created")

        systemctl_log = (self.work / "harness-state/systemctl.log").read_text(encoding="utf-8")
        self.assertIn("daemon-reload", systemctl_log)
        self.assertIn("enable librespot.service", systemctl_log)
        self.assertIn("restart librespot.service", systemctl_log)
        self.assertIn("is-active --quiet librespot.service", systemctl_log)

        self.assertFalse((fakeroot / "usr/local/libexec/librespot-playplay").exists())
        self.assertFalse((fakeroot / "usr/local/share/doc/librespot-playplay/LICENSE").exists())
        self.assertFalse((fakeroot / "usr/local/share/doc/librespot-playplay/source.tar.gz").exists())
        self.assertTrue((fakeroot / "usr/local/share/doc/librespot-playplay/notes.txt").exists())
        self.assertFalse((fakeroot / "usr/local/sbin/uninstall-2go-spotify").exists())
        self.assertFalse((fakeroot / "usr/local/sbin/rollback-2go-spotify-lossless").exists())

        self.run_command(
            ["sh", str(fakeroot / "usr/local/sbin/uninstall-chord-2go-spotify")],
            env=env,
        )

        self.assertEqual(
            (fakeroot / "usr/local/bin/librespot").read_text(encoding="utf-8"),
            "#!/bin/sh\necho original librespot\n",
        )
        self.assertEqual(
            (fakeroot / "etc/systemd/system/librespot.service").read_text(encoding="utf-8"),
            "original service\n",
        )
        self.assertFalse((fakeroot / "usr/local/bin/librespot-aplay").exists())
        self.assertFalse((fakeroot / "usr/local/sbin/librespot-audio").exists())
        self.assertFalse((fakeroot / DOCS_DIR.relative_to("/") / LIBRESPOT_LICENSE_NAME).exists())
        self.assertFalse((fakeroot / DOCS_DIR.relative_to("/") / PROJECT_LICENSE_NAME).exists())
        self.assertFalse((fakeroot / DOCS_DIR.relative_to("/") / THIRD_PARTY_NOTICES_NAME).exists())
        self.assertFalse((fakeroot / "var/lib/chord-2go-spotify").exists())
        self.assertFalse((fakeroot / DEDICATED_CACHE_DIR.relative_to("/")).exists())
        self.assertTrue((fakeroot / LEGACY_CACHE_DIR.relative_to("/") / "existing-cache-marker").exists())
        self.assertFalse((fakeroot / "usr/local/sbin/uninstall-chord-2go-spotify").exists())
        self.assertTrue((fakeroot / "usr/local/share/doc/librespot-playplay/notes.txt").exists())

        second = self.run_command(["sh", str(PAYLOAD_DIR / "uninstall.sh")], env=env)
        self.assertEqual(second.returncode, 0)
        self.assertTrue((fakeroot / LEGACY_CACHE_DIR.relative_to("/") / "existing-cache-marker").exists())

    def test_install_failure_restores_previous_state(self) -> None:
        payload_copy = self.make_payload_tree()
        fakeroot, env = self.make_harness(fail_markers=("restart:librespot.service",))

        self.write_file(
            fakeroot / "usr/local/bin/librespot",
            "#!/bin/sh\necho original librespot\n",
            0o755,
        )
        self.write_file(
            fakeroot / "etc/systemd/system/librespot.service",
            "original service\n",
            0o644,
        )
        self.write_file(
            fakeroot / "usr/local/libexec/librespot-playplay",
            "#!/bin/sh\necho legacy\n",
            0o755,
        )
        self.write_file(
            fakeroot / "usr/local/share/doc/librespot-playplay/LICENSE",
            "legacy license\n",
            0o644,
        )
        self.write_file(
            fakeroot / "var/cache/librespot/existing-cache-marker",
            "preserve me\n",
            0o644,
        )

        failed = self.run_command(
            ["sh", str(payload_copy / "install.sh")],
            cwd=payload_copy,
            env=env,
            check=False,
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("failed to restart librespot.service", failed.stderr)
        self.assertIn("restored previous state", failed.stderr)
        self.assertNotIn(INSTALL_SUCCESS_MARKER, failed.stdout)

        self.assertEqual(
            (fakeroot / "usr/local/bin/librespot").read_text(encoding="utf-8"),
            "#!/bin/sh\necho original librespot\n",
        )
        self.assertEqual(
            (fakeroot / "etc/systemd/system/librespot.service").read_text(encoding="utf-8"),
            "original service\n",
        )
        self.assertFalse((fakeroot / "usr/local/bin/librespot-aplay").exists())
        self.assertFalse((fakeroot / "usr/local/sbin/librespot-audio").exists())
        self.assertFalse((fakeroot / "var/lib/chord-2go-spotify/manifest.tsv").exists())
        self.assertTrue((fakeroot / "usr/local/libexec/librespot-playplay").exists())
        self.assertTrue((fakeroot / "usr/local/share/doc/librespot-playplay/LICENSE").exists())
        self.assertTrue((fakeroot / LEGACY_CACHE_DIR.relative_to("/") / "existing-cache-marker").exists())

    def test_install_uses_sha256sum_when_cksum_is_missing(self) -> None:
        payload_copy = self.make_payload_tree()
        fakeroot, env = self.make_harness(include_sha256sum=True, include_failing_cksum=True)

        result = self.run_command(["sh", str(payload_copy / "install.sh")], cwd=payload_copy, env=env)
        self.assertEqual(result.stdout.strip(), INSTALL_SUCCESS_MARKER)
        self.assertNotIn("unbound variable", result.stderr)
        self.assertFalse((self.work / "logs/cksum.log").exists())

        manifest = self.parse_manifest(fakeroot / "var/lib/chord-2go-spotify/manifest.tsv")
        for _path, (_kind, _backup, fingerprint) in manifest.items():
            self.assertTrue(fingerprint.startswith("sha256:"))

    def test_uninstall_restores_preexisting_active_enabled_service(self) -> None:
        payload_copy = self.make_payload_tree()
        fakeroot, env = self.make_harness(
            active_units=("librespot.service",),
            enabled_units=("librespot.service",),
        )

        self.write_file(
            fakeroot / "usr/local/bin/librespot",
            "#!/bin/sh\necho original librespot\n",
            0o755,
        )
        self.write_file(
            fakeroot / "etc/systemd/system/librespot.service",
            "original service\n",
            0o644,
        )

        install_result = self.run_command(["sh", str(payload_copy / "install.sh")], cwd=payload_copy, env=env)
        self.assertEqual(install_result.stdout.strip(), INSTALL_SUCCESS_MARKER)

        service_state = self.parse_original_service_state(
            fakeroot / "var/lib/chord-2go-spotify/original-service-state.env"
        )
        self.assertEqual(
            service_state,
            {"present": "1", "enabled": "1", "active": "1"},
        )

        self.run_command(
            ["sh", str(fakeroot / "usr/local/sbin/uninstall-chord-2go-spotify")],
            env=env,
        )

        self.assertEqual(
            (fakeroot / "etc/systemd/system/librespot.service").read_text(encoding="utf-8"),
            "original service\n",
        )
        self.assertEqual(
            (fakeroot / "usr/local/bin/librespot").read_text(encoding="utf-8"),
            "#!/bin/sh\necho original librespot\n",
        )
        self.assertIn("librespot.service", self.read_systemctl_units("active"))
        self.assertIn("librespot.service", self.read_systemctl_units("enabled"))

        systemctl_log = (self.work / "harness-state/systemctl.log").read_text(encoding="utf-8")
        self.assertIn("disable --now librespot.service", systemctl_log)
        self.assertIn("enable librespot.service", systemctl_log)
        self.assertIn("start librespot.service", systemctl_log)

    def test_uninstall_keeps_pristine_device_removed_and_inactive(self) -> None:
        payload_copy = self.make_payload_tree()
        fakeroot, env = self.make_harness()

        install_result = self.run_command(["sh", str(payload_copy / "install.sh")], cwd=payload_copy, env=env)
        self.assertEqual(install_result.stdout.strip(), INSTALL_SUCCESS_MARKER)

        service_state = self.parse_original_service_state(
            fakeroot / "var/lib/chord-2go-spotify/original-service-state.env"
        )
        self.assertEqual(
            service_state,
            {"present": "0", "enabled": "0", "active": "0"},
        )

        self.run_command(
            ["sh", str(fakeroot / "usr/local/sbin/uninstall-chord-2go-spotify")],
            env=env,
        )

        self.assertFalse((fakeroot / "etc/systemd/system/librespot.service").exists())
        self.assertFalse((fakeroot / "usr/local/bin/librespot").exists())
        self.assertNotIn("librespot.service", self.read_systemctl_units("active"))
        self.assertNotIn("librespot.service", self.read_systemctl_units("enabled"))
        self.assertFalse((fakeroot / "var/lib/chord-2go-spotify").exists())
        self.assertFalse((fakeroot / DEDICATED_CACHE_DIR.relative_to("/")).exists())

    def test_builder_creates_expected_archive_and_checksum(self) -> None:
        binary = self.work / "inputs/librespot"
        license_file = self.work / "inputs/LICENSE"
        output = self.work / "dist/spotify-install.tar.gz"
        self.write_file(binary, "#!/bin/sh\necho librespot arm\n", 0o755)
        self.write_file(license_file, "upstream license\n", 0o644)

        result = self.run_command(
            ["sh", str(BUILD_SCRIPT), str(binary), str(output)],
            env={"LIBRESPOT_LICENSE": str(license_file)},
        )
        self.assertTrue(output.exists())
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        self.assertIn(digest, result.stdout)

        with tarfile.open(output, "r:gz") as archive:
            names = set(archive.getnames())
            self.assertEqual(names, EXPECTED_ARCHIVE_NAMES)
            service_text = archive.extractfile("librespot.service").read().decode("utf-8")
            self.assertIn("--bitrate 320", service_text)
            self.assertIn("--cache /var/cache/chord-2go-spotify", service_text)
            self.assertNotIn("lossless", service_text)
            self.assertEqual(
                archive.extractfile(LIBRESPOT_LICENSE_NAME).read().decode("utf-8"),
                "upstream license\n",
            )
            self.assertEqual(
                archive.extractfile(PROJECT_LICENSE_NAME).read().decode("utf-8"),
                REPO_LICENSE_TEXT,
            )
            self.assertEqual(
                archive.extractfile(THIRD_PARTY_NOTICES_NAME).read().decode("utf-8"),
                REPO_THIRD_PARTY_NOTICES_TEXT,
            )

        archive_names_text = "\n".join(sorted(names))
        self.assertNotIn("librespot-playplay", archive_names_text)
        self.assertNotIn("rollback-2go-spotify-lossless", archive_names_text)

    def test_builder_finds_librespot_dot_license_next_to_binary(self) -> None:
        binary = self.work / "inputs/librespot-armv7"
        license_file = self.work / "inputs/librespot.LICENSE"
        output = self.work / "dist/spotify-install.tar.gz"
        self.write_file(binary, "#!/bin/sh\necho librespot arm\n", 0o755)
        self.write_file(license_file, "neighbor license\n", 0o644)

        self.run_command(["sh", str(BUILD_SCRIPT), str(binary), str(output)])

        with tarfile.open(output, "r:gz") as archive:
            self.assertEqual(
                archive.extractfile(LIBRESPOT_LICENSE_NAME).read().decode("utf-8"),
                "neighbor license\n",
            )

    def test_builder_rejects_missing_inputs(self) -> None:
        missing_binary = self.work / "inputs/missing-librespot"
        missing_result = self.run_command(
            ["sh", str(BUILD_SCRIPT), str(missing_binary)],
            check=False,
        )
        self.assertNotEqual(missing_result.returncode, 0)
        self.assertIn("missing file", missing_result.stderr)

        binary = self.work / "inputs/librespot"
        self.write_file(binary, "#!/bin/sh\necho librespot arm\n", 0o644)
        not_exec_result = self.run_command(
            ["sh", str(BUILD_SCRIPT), str(binary)],
            check=False,
        )
        self.assertNotEqual(not_exec_result.returncode, 0)
        self.assertIn("not executable", not_exec_result.stderr)

        binary.chmod(0o755)
        missing_license_result = self.run_command(
            ["sh", str(BUILD_SCRIPT), str(binary)],
            check=False,
        )
        self.assertNotEqual(missing_license_result.returncode, 0)
        self.assertIn("set LIBRESPOT_LICENSE", missing_license_result.stderr)


if __name__ == "__main__":
    unittest.main()
