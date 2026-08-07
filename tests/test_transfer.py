from __future__ import annotations

import asyncio
import sys
from ipaddress import IPv4Address
from pathlib import Path
from unittest import mock
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chord_2go_spotify.errors import PayloadMissingError, TransferError, ValidationError
from chord_2go_spotify.transfer import (
    ARCHIVE_NAME,
    CHECKSUM_NAME,
    INSTALL_SUCCESS_MARKER,
    PayloadBundle,
    REMOTE_ACTION_MARKER_PREFIX,
    REMOTE_EXIT_MARKER_PREFIX,
    ReportServer,
    build_install_command,
    build_status_command,
    build_uninstall_command,
    load_payload_bundle,
    make_transfer_context,
    parse_action_report,
    UNINSTALL_MISSING_MARKER,
    validate_action_report,
)


class TransferContextTests(unittest.TestCase):
    def test_command_builders_reject_unsafe_values(self) -> None:
        with self.assertRaises(ValidationError):
            make_transfer_context("not-an-ip", 8080)
        with self.assertRaises(ValidationError):
            make_transfer_context(IPv4Address("127.0.0.1"), 0)
        with self.assertRaises(ValidationError):
            make_transfer_context(IPv4Address("127.0.0.1"), 8080, session_id="bad-token!")

    def test_install_command_uses_targeted_tmp_paths(self) -> None:
        context = make_transfer_context(IPv4Address("127.0.0.1"), 8080, session_id="abc123abc123")
        command = build_install_command(context)
        self.assertIn("/tmp/chord-2go-spotify-abc123abc123", command)
        self.assertIn(ARCHIVE_NAME, command)
        self.assertIn(CHECKSUM_NAME, command)
        self.assertIn("/report", command)
        self.assertIn("sha256sum", command)

    def test_commands_include_remote_action_markers(self) -> None:
        context = make_transfer_context(IPv4Address("127.0.0.1"), 8080, session_id="abc123abc123")
        self.assertIn(REMOTE_ACTION_MARKER_PREFIX, build_install_command(context))
        self.assertIn(REMOTE_EXIT_MARKER_PREFIX, build_status_command(context))
        self.assertIn(REMOTE_EXIT_MARKER_PREFIX, build_uninstall_command(context))
        self.assertIn(UNINSTALL_MISSING_MARKER, build_uninstall_command(context))
        self.assertIn("{false}", build_uninstall_command(context))


class RemoteReportTests(unittest.TestCase):
    def test_parse_action_report_strips_markers(self) -> None:
        parsed = parse_action_report(
            "\n".join(
                (
                    "systemctl_is_active:",
                    "active",
                    f"{REMOTE_ACTION_MARKER_PREFIX}status",
                    f"{REMOTE_EXIT_MARKER_PREFIX}0",
                )
            )
        )
        self.assertEqual(parsed.action, "status")
        self.assertEqual(parsed.exit_code, 0)
        self.assertEqual(parsed.body, "systemctl_is_active:\nactive")

    def test_install_requires_payload_success_marker(self) -> None:
        report = "\n".join(
            (
                "systemctl_is_active:",
                "active",
                "librespot_version:",
                "librespot 0.4.2",
                f"{REMOTE_ACTION_MARKER_PREFIX}install",
                f"{REMOTE_EXIT_MARKER_PREFIX}0",
            )
        )
        with self.assertRaises(TransferError):
            validate_action_report("install", report)

    def test_install_report_with_shell_errors_and_active_status_fails(self) -> None:
        report = "\n".join(
            (
                "cksum: command not found",
                "./install.sh: line 42: channel: unbound variable",
                "systemctl_is_active:",
                "active",
                "librespot_version:",
                "librespot 0.4.2",
                INSTALL_SUCCESS_MARKER,
                f"{REMOTE_ACTION_MARKER_PREFIX}install",
                f"{REMOTE_EXIT_MARKER_PREFIX}1",
            )
        )
        with self.assertRaises(TransferError):
            validate_action_report("install", report)

    def test_status_report_with_shell_errors_fails(self) -> None:
        report = "\n".join(
            (
                "sh: librespot: not found",
                "systemctl_is_active:",
                "active",
                "librespot_version:",
                f"{REMOTE_ACTION_MARKER_PREFIX}status",
                f"{REMOTE_EXIT_MARKER_PREFIX}0",
            )
        )
        with self.assertRaises(TransferError):
            validate_action_report("status", report)

    def test_uninstall_requires_zero_exit(self) -> None:
        report = "\n".join(
            (
                "systemctl_is_active:",
                "inactive",
                f"{REMOTE_ACTION_MARKER_PREFIX}uninstall",
                f"{REMOTE_EXIT_MARKER_PREFIX}1",
            )
        )
        with self.assertRaises(TransferError):
            validate_action_report("uninstall", report)

    def test_uninstall_missing_entrypoint_report_fails_even_if_exit_zero(self) -> None:
        report = "\n".join(
            (
                UNINSTALL_MISSING_MARKER,
                "systemctl_is_active:",
                "inactive",
                f"{REMOTE_ACTION_MARKER_PREFIX}uninstall",
                f"{REMOTE_EXIT_MARKER_PREFIX}0",
            )
        )
        with self.assertRaises(TransferError):
            validate_action_report("uninstall", report)


class PayloadBundleTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_paths_and_checksum(self) -> None:
        bundle = PayloadBundle.from_bytes(b"payload-bytes")
        async with ReportServer(IPv4Address("127.0.0.1"), bundle=bundle) as server:
            archive_response = await self._request(
                server.port,
                f"GET /{ARCHIVE_NAME} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode(),
            )
            checksum_response = await self._request(
                server.port,
                f"GET /{CHECKSUM_NAME} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode(),
            )
        self.assertIn(b"HTTP/1.1 200 OK", archive_response)
        self.assertTrue(archive_response.endswith(bundle.archive_bytes))
        self.assertIn(bundle.sha256_hex.encode(), checksum_response)
        self.assertTrue(checksum_response.endswith(bundle.checksum_bytes))

    async def test_report_is_bounded_and_recorded(self) -> None:
        bundle = PayloadBundle.from_bytes(b"payload-bytes")
        async with ReportServer(IPv4Address("127.0.0.1"), bundle=bundle, report_limit=8) as server:
            payload = b"hello"
            response = await self._request(
                server.port,
                b"POST /report HTTP/1.1\r\nHost: localhost\r\nContent-Length: 5\r\n\r\nhello",
            )
            self.assertIn(b"HTTP/1.1 204 No Content", response)
            self.assertEqual(await server.wait_for_report(1), payload.decode())

    async def _request(self, port: int, request: bytes) -> bytes:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(request)
        await writer.drain()
        response = await reader.read(-1)
        writer.close()
        await writer.wait_closed()
        return response


class PayloadLoadingTests(unittest.TestCase):
    def test_missing_payload_fails_clearly(self) -> None:
        fake_root = mock.Mock()
        fake_root.joinpath.return_value = fake_root
        fake_root.read_bytes.side_effect = FileNotFoundError("missing")
        with mock.patch("chord_2go_spotify.transfer.resources.files", return_value=fake_root):
            with self.assertRaises(PayloadMissingError):
                load_payload_bundle()

    def test_status_command_uses_report_path(self) -> None:
        context = make_transfer_context(IPv4Address("127.0.0.1"), 8080, session_id="abc123abc123")
        command = build_status_command(context)
        self.assertIn("http://127.0.0.1:8080/report", command)


if __name__ == "__main__":
    unittest.main()
