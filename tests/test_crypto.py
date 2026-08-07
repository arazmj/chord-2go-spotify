from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chord_2go_spotify.crypto import decrypt_packet, encrypt_packet
from chord_2go_spotify.errors import ChecksumError


class CryptoTests(unittest.TestCase):
    def test_encrypt_vector_is_stable(self) -> None:
        packet = encrypt_packet("status", pin=1234, random_header=0x1234)
        self.assertEqual(packet.hex(), "0086d94c9d670aa740f7129a64f8fd5e")

    def test_round_trip_supports_extended_payloads(self) -> None:
        message = "x" * 300
        encrypted = encrypt_packet(message, pin=7, random_header=0xBEEF)
        self.assertEqual(decrypt_packet(encrypted, pin=7), message)

    def test_round_trip_supports_extended_length_boundary(self) -> None:
        message = "y" * 259
        encrypted = encrypt_packet(message, pin=9, random_header=0xCAFE)
        self.assertEqual(decrypt_packet(encrypted, pin=9), message)

    def test_checksum_rejection_raises(self) -> None:
        encrypted = bytearray(encrypt_packet("abcdefghij", pin=1, random_header=0x2222))
        encrypted[8] ^= 0x01
        with self.assertRaises(ChecksumError):
            decrypt_packet(encrypted, pin=1)


if __name__ == "__main__":
    unittest.main()
