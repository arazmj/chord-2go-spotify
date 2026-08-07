from __future__ import annotations

import random
import struct
from collections.abc import Callable
from typing import Final

from .errors import ChecksumError, PacketError

_BLOCK_SIZE: Final[int] = 8
_DELTA: Final[int] = 0x9E3779B9
_ROUNDS: Final[int] = 32
_SEED: Final[int] = 920_428_087


def u32(value: int) -> int:
    return value & 0xFFFFFFFF


def derive_key(pin: int) -> tuple[int, int, int, int]:
    if pin < 0:
        raise PacketError("PIN must be a non-negative integer.")
    value = pin
    key: list[int] = []
    for _ in range(4):
        value = u32(value + _SEED)
        key.append(value)
    return tuple(key)


def encrypt_block(block: bytes, key: tuple[int, int, int, int]) -> bytes:
    if len(block) != _BLOCK_SIZE:
        raise PacketError("XTEA blocks must be exactly 8 bytes.")
    left, right = struct.unpack(">II", block)
    total = 0
    for _ in range(_ROUNDS):
        left = u32(
            left
            + ((((right << 4) ^ (right >> 5)) + right) ^ (total + key[total & 3]))
        )
        total = u32(total + _DELTA)
        right = u32(
            right
            + (
                (((left << 4) ^ (left >> 5)) + left)
                ^ (total + key[(total >> 11) & 3])
            )
        )
    return struct.pack(">II", left, right)


def decrypt_block(block: bytes, key: tuple[int, int, int, int]) -> bytes:
    if len(block) != _BLOCK_SIZE:
        raise PacketError("XTEA blocks must be exactly 8 bytes.")
    left, right = struct.unpack(">II", block)
    total = u32(_DELTA * _ROUNDS)
    for _ in range(_ROUNDS):
        right = u32(
            right
            - (
                (((left << 4) ^ (left >> 5)) + left)
                ^ (total + key[(total >> 11) & 3])
            )
        )
        total = u32(total - _DELTA)
        left = u32(
            left
            - ((((right << 4) ^ (right >> 5)) + right) ^ (total + key[total & 3]))
        )
    return struct.pack(">II", left, right)


def _normalize_payload(payload: str | bytes | bytearray) -> bytes:
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return bytes(payload)


def encrypt_packet(
    payload: str | bytes | bytearray,
    pin: int = 0,
    *,
    random_header: int | None = None,
    random_source: Callable[[], int] | None = None,
) -> bytes:
    data = _normalize_payload(payload)
    if len(data) > 0xFFFF:
        raise PacketError("Payload is too large for the device packet format.")
    if random_header is None:
        random_header = random_source() if random_source is not None else random.randrange(0x10000)
    if not 0 <= random_header <= 0xFFFF:
        raise PacketError("Random header must fit in 16 bits.")

    plain = bytearray(4 + len(data))
    plain[0] = random_header & 0xFF
    padded_length = len(plain) + ((-len(plain)) % _BLOCK_SIZE)
    use_extended_length = padded_length >= 264
    plain[1] = ((len(data) >> 8) & 0xFF) if use_extended_length else ((random_header >> 8) & 0xFF)
    plain[2] = len(data) & 0xFF

    checksum = 0
    for byte in data:
        checksum ^= byte
    plain[3] = checksum

    xor_value = plain[0]
    for index, byte in enumerate(data):
        plain[4 + index] = byte ^ xor_value

    plain.extend(b"\0" * ((-len(plain)) % _BLOCK_SIZE))
    key = derive_key(pin)
    return b"".join(
        encrypt_block(plain[index : index + _BLOCK_SIZE], key)
        for index in range(0, len(plain), _BLOCK_SIZE)
    )


def decrypt_payload(data: bytes | bytearray, pin: int = 0) -> bytes:
    encrypted = bytes(data)
    if not encrypted or len(encrypted) % _BLOCK_SIZE:
        raise PacketError(
            "Encrypted packet length must be a non-zero multiple of 8 bytes."
        )

    key = derive_key(pin)
    plain = b"".join(
        decrypt_block(encrypted[index : index + _BLOCK_SIZE], key)
        for index in range(0, len(encrypted), _BLOCK_SIZE)
    )
    length = plain[2] if len(encrypted) < 264 else plain[2] | (plain[1] << 8)
    if length > len(plain) - 4:
        raise PacketError("Encrypted packet declared an invalid payload length.")

    payload = bytearray(plain[4 : 4 + length])
    xor_value = plain[0]
    checksum = 0
    for index in range(length):
        payload[index] ^= xor_value
        checksum ^= payload[index]
    if checksum != plain[3]:
        raise ChecksumError(
            "Encrypted packet checksum did not match; the PIN may be wrong or data is corrupted."
        )
    return bytes(payload)


def decrypt_packet(data: bytes | bytearray, pin: int = 0) -> str:
    return decrypt_payload(data, pin).decode("utf-8", "replace")


__all__ = [
    "decrypt_block",
    "decrypt_packet",
    "decrypt_payload",
    "derive_key",
    "encrypt_block",
    "encrypt_packet",
    "u32",
]
