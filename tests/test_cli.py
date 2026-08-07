from __future__ import annotations

import contextlib
import io
import sys
from ipaddress import IPv4Address
from pathlib import Path
from unittest import mock
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chord_2go_spotify import cli
from chord_2go_spotify.cli import OperationResult
from chord_2go_spotify.device import DeviceCandidate, PreflightInfo
from chord_2go_spotify.errors import Chord2GoSpotifyError
from chord_2go_spotify.transfer import (
    INSTALL_SUCCESS_MARKER,
    REMOTE_ACTION_MARKER_PREFIX,
    REMOTE_EXIT_MARKER_PREFIX,
    make_transfer_context,
)
from chord_2go_spotify.version import get_version_text


class ParserTests(unittest.TestCase):
    def test_parser_basics(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["install", "--force", "--device", "AA", "--pin", "1234", "--verbose"])
        self.assertEqual(args.command, "install")
        self.assertTrue(args.force)
        self.assertEqual(args.device, "AA")
        self.assertEqual(args.pin, "1234")
        self.assertTrue(args.verbose)

    def test_global_version_prints_and_exits_zero_without_work(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch(
            "chord_2go_spotify.cli.discover_devices",
            new=mock.AsyncMock(side_effect=AssertionError("BLE discovery should not run.")),
        ):
            with mock.patch(
                "chord_2go_spotify.cli.load_payload_bundle",
                side_effect=AssertionError("Payload access should not run."),
            ):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as caught:
                        cli.main(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(stdout.getvalue().strip(), get_version_text())
        self.assertEqual(stderr.getvalue(), "")


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_async_success(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        device = DeviceCandidate(address="AA:BB", name="Chord 2go")
        result = OperationResult(
            action="status",
            device=device,
            preflight=PreflightInfo(
                address=device.address,
                model="2go",
                name="Chord 2go",
                firmware="1.6.1",
                ip_address=IPv4Address("192.168.1.10"),
            ),
            host_ip=IPv4Address("192.168.1.20"),
            report="active\nlibrespot 0.4.2",
        )
        with mock.patch("chord_2go_spotify.cli.discover_devices", new=mock.AsyncMock(return_value=[device])):
            with mock.patch("chord_2go_spotify.cli.run_operation", new=mock.AsyncMock(return_value=result)):
                exit_code = await cli.run_async(
                    ["status", "--pin", "0000"],
                    stdout=stdout,
                    stderr=stderr,
                )
        self.assertEqual(exit_code, 0)
        self.assertIn("Action: status", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    async def test_run_async_failure(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        device = DeviceCandidate(address="AA:BB", name="Chord 2go")
        with mock.patch("chord_2go_spotify.cli.discover_devices", new=mock.AsyncMock(return_value=[device])):
            with mock.patch(
                "chord_2go_spotify.cli.run_operation",
                new=mock.AsyncMock(side_effect=Chord2GoSpotifyError("boom")),
            ):
                exit_code = await cli.run_async(
                    ["status", "--pin", "0000"],
                    stdout=stdout,
                    stderr=stderr,
                )
        self.assertEqual(exit_code, 2)
        self.assertIn("Error: boom", stderr.getvalue())

    async def test_multiple_devices_prompt_for_selection(self) -> None:
        stdout = io.StringIO()
        device_a = DeviceCandidate(address="AA:BB", name="First")
        device_b = DeviceCandidate(address="CC:DD", name="Second")
        result = OperationResult(
            action="status",
            device=device_b,
            preflight=PreflightInfo(
                address=device_b.address,
                model="2go",
                name="Second",
                firmware="1.6.1",
                ip_address=IPv4Address("192.168.1.11"),
            ),
            host_ip=IPv4Address("192.168.1.20"),
            report="active",
        )
        with mock.patch(
            "chord_2go_spotify.cli.discover_devices",
            new=mock.AsyncMock(return_value=[device_a, device_b]),
        ):
            with mock.patch("chord_2go_spotify.cli.run_operation", new=mock.AsyncMock(return_value=result)):
                exit_code = await cli.run_async(
                    ["status", "--pin", "0000"],
                    input_func=lambda _: "2",
                    stdout=stdout,
                    stderr=io.StringIO(),
                )
        self.assertEqual(exit_code, 0)
        self.assertIn("Discovered multiple devices", stdout.getvalue())

    async def test_run_async_install_failure_report_exits_nonzero(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        device = DeviceCandidate(address="AA:BB", name="Chord 2go")
        preflight = PreflightInfo(
            address=device.address,
            model="2go",
            name="Chord 2go",
            firmware="1.6.1",
            ip_address=IPv4Address("192.168.1.10"),
        )
        report = "\n".join(
            (
                "cksum: command not found",
                "./install.sh: line 19: state_dir: unbound variable",
                "systemctl_is_active:",
                "active",
                "librespot_version:",
                "librespot 0.4.2",
                INSTALL_SUCCESS_MARKER,
                f"{REMOTE_ACTION_MARKER_PREFIX}install",
                f"{REMOTE_EXIT_MARKER_PREFIX}1",
            )
        )

        class FakeBleSession:
            def __init__(self, candidate: DeviceCandidate, pin: int) -> None:
                self.candidate = candidate
                self.pin = pin

            async def __aenter__(self) -> "FakeBleSession":
                return self

            async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
                return None

            async def read_preflight(self, *, force: bool) -> PreflightInfo:
                return preflight

            async def send_radio_command(self, command: str) -> None:
                self.command = command

        class FakeReportServer:
            def __init__(self, host_ip: IPv4Address, *, bundle: object | None = None) -> None:
                self.host_ip = host_ip
                self.bundle = bundle
                self.port = 8765

            async def __aenter__(self) -> "FakeReportServer":
                return self

            async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
                return None

            def build_context(self, *, session_id: str | None = None) -> object:
                return make_transfer_context(
                    self.host_ip,
                    self.port,
                    session_id=session_id or "abc123abc123",
                )

            async def wait_for_report(self, timeout: float) -> str:
                return report

        with mock.patch("chord_2go_spotify.cli.discover_devices", new=mock.AsyncMock(return_value=[device])):
            with mock.patch("chord_2go_spotify.cli.BleSession", FakeBleSession):
                with mock.patch("chord_2go_spotify.cli.ReportServer", FakeReportServer):
                    with mock.patch(
                        "chord_2go_spotify.cli.select_local_ipv4",
                        return_value=IPv4Address("192.168.1.20"),
                    ):
                        with mock.patch("chord_2go_spotify.cli.load_payload_bundle", return_value=object()):
                            exit_code = await cli.run_async(
                                ["install", "--pin", "0000"],
                                stdout=stdout,
                                stderr=stderr,
                            )
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Remote install failed with exit code 1", stderr.getvalue())

    async def test_run_async_route_error_exits_nonzero(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        device = DeviceCandidate(address="AA:BB", name="Chord 2go")
        preflight = PreflightInfo(
            address=device.address,
            model="2go",
            name="Chord 2go",
            firmware="1.6.1",
            ip_address=IPv4Address("192.168.1.10"),
        )

        class FakeBleSession:
            def __init__(self, candidate: DeviceCandidate, pin: int) -> None:
                self.candidate = candidate
                self.pin = pin

            async def __aenter__(self) -> "FakeBleSession":
                return self

            async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
                return None

            async def read_preflight(self, *, force: bool) -> PreflightInfo:
                return preflight

            async def send_radio_command(self, command: str) -> None:
                self.command = command

        fake_socket = mock.MagicMock()
        fake_socket.__enter__.return_value = fake_socket
        fake_socket.connect.side_effect = OSError("No route to host")

        with mock.patch("chord_2go_spotify.cli.discover_devices", new=mock.AsyncMock(return_value=[device])):
            with mock.patch("chord_2go_spotify.cli.BleSession", FakeBleSession):
                with mock.patch("chord_2go_spotify.device.socket.socket", return_value=fake_socket):
                    exit_code = await cli.run_async(
                        ["status", "--pin", "0000"],
                        stdout=stdout,
                        stderr=stderr,
                    )
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Could not determine a local IPv4 route", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
