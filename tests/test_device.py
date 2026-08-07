from __future__ import annotations

import sys
from ipaddress import IPv4Address
from pathlib import Path
from unittest import mock
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chord_2go_spotify.device import SUPPORTED_FIRMWARE, parse_ipv4, select_local_ipv4, validate_firmware
from chord_2go_spotify.errors import UnsupportedFirmwareError, ValidationError


class FirmwareTests(unittest.TestCase):
    def test_supported_firmware_passes(self) -> None:
        self.assertEqual(validate_firmware(SUPPORTED_FIRMWARE), SUPPORTED_FIRMWARE)

    def test_unsupported_firmware_requires_force(self) -> None:
        with self.assertRaises(UnsupportedFirmwareError):
            validate_firmware("1.6.2")
        self.assertEqual(validate_firmware("1.6.2", force=True), "1.6.2")


class IPv4Tests(unittest.TestCase):
    def test_parse_ipv4_rejects_invalid_values(self) -> None:
        self.assertEqual(parse_ipv4("192.168.1.25"), IPv4Address("192.168.1.25"))
        with self.assertRaises(ValidationError):
            parse_ipv4("not-an-ip")

    def test_route_selection_uses_udp_socket(self) -> None:
        fake_socket = mock.MagicMock()
        fake_socket.__enter__.return_value = fake_socket
        fake_socket.getsockname.return_value = ("10.0.0.9", 55000)
        with mock.patch("chord_2go_spotify.device.socket.socket", return_value=fake_socket) as factory:
            selected = select_local_ipv4("192.168.1.50")
        factory.assert_called_once()
        fake_socket.connect.assert_called_once_with(("192.168.1.50", 9))
        self.assertEqual(selected, IPv4Address("10.0.0.9"))

    def test_route_selection_network_error_is_wrapped(self) -> None:
        fake_socket = mock.MagicMock()
        fake_socket.__enter__.return_value = fake_socket
        fake_socket.connect.side_effect = OSError("No route to host")
        with mock.patch("chord_2go_spotify.device.socket.socket", return_value=fake_socket):
            with self.assertRaises(ValidationError) as caught:
                select_local_ipv4("192.168.1.50")
        self.assertIn("Could not determine a local IPv4 route", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
