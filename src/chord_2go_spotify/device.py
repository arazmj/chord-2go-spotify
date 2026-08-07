from __future__ import annotations

import re
import socket
from dataclasses import dataclass
from ipaddress import IPv4Address, ip_address
from typing import Final

from .errors import SelectionError, UnsupportedFirmwareError, ValidationError

ADVERTISING_UUID: Final[str] = "cc584d26-a1f5-11e7-abc4-cec278b6b50a"
RADIO_URL_UUID: Final[str] = "cc58cda0-a1f5-11e7-abc4-cec278b6b50a"
FIRMWARE_VERSION_UUID: Final[str] = "cc58785a-a1f5-11e7-abc4-cec278b6b50a"
MODEL_UUID: Final[str] = "cc587102-a1f5-11e7-abc4-cec278b6b50a"
NAME_UUID: Final[str] = "cc586f86-a1f5-11e7-abc4-cec278b6b50a"
IP_UUID: Final[str] = "cc58a2a8-a1f5-11e7-abc4-cec278b6b50a"
CHALLENGE_UUID: Final[str] = "cc58834a-a1f5-11e7-abc4-cec278b6b50a"
SUPPORTED_FIRMWARE: Final[str] = "1.6.1"
_PIN_RE: Final[re.Pattern[str]] = re.compile(r"^\d+$")
_PRINTABLE_RE: Final[re.Pattern[str]] = re.compile(r"^[ -~]+$")


@dataclass(frozen=True, slots=True)
class DeviceCandidate:
    address: str
    name: str = ""
    service_uuids: tuple[str, ...] = ()
    native: object | None = None

    @property
    def display_name(self) -> str:
        return self.name or self.address


@dataclass(frozen=True, slots=True)
class PreflightInfo:
    address: str
    model: str
    name: str
    firmware: str
    ip_address: IPv4Address
    challenge: str | None = None


def parse_pin(value: str | int | None) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        if value < 0:
            raise ValidationError("PIN must be a non-negative integer.")
        return value
    text = value.strip()
    if not text:
        return 0
    if not _PIN_RE.fullmatch(text):
        raise ValidationError("PIN must contain digits only.")
    return int(text, 10)


def _validate_text(label: str, value: str) -> str:
    text = value.strip()
    if not text:
        raise ValidationError(f"Device {label} was empty.")
    if not _PRINTABLE_RE.fullmatch(text):
        raise ValidationError(f"Device {label} contained unsupported characters.")
    return text


def validate_challenge(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > 128 or not _PRINTABLE_RE.fullmatch(text):
        raise ValidationError("Device challenge was invalid; verify the PIN and retry.")
    return text


def validate_firmware(version: str, *, force: bool = False) -> str:
    text = _validate_text("firmware", version)
    if text == SUPPORTED_FIRMWARE or force:
        return text
    raise UnsupportedFirmwareError(
        f"Firmware {text} is not supported; rerun with --force to continue."
    )


def validate_device_identity(model: str, name: str) -> tuple[str, str]:
    return _validate_text("model", model), _validate_text("name", name)


def parse_ipv4(value: str) -> IPv4Address:
    text = _validate_text("IPv4", value)
    try:
        parsed = ip_address(text)
    except ValueError as error:
        raise ValidationError(f"Device IPv4 address {text!r} is invalid.") from error
    if not isinstance(parsed, IPv4Address):
        raise ValidationError("Device reported a non-IPv4 address.")
    if parsed.is_multicast or parsed.is_unspecified or parsed.is_loopback:
        raise ValidationError(f"Device IPv4 address {text!r} is not a usable LAN address.")
    return parsed


def select_local_ipv4(device_ip: IPv4Address | str) -> IPv4Address:
    remote_ip = device_ip if isinstance(device_ip, IPv4Address) else parse_ipv4(device_ip)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect((str(remote_ip), 9))
            local_ip = connection.getsockname()[0]
    except OSError as error:
        raise ValidationError(
            f"Could not determine a local IPv4 route to device {remote_ip}; "
            "verify LAN connectivity and retry."
        ) from error
    return parse_ipv4(local_ip)


def build_preflight(
    *,
    address: str,
    model: str,
    name: str,
    firmware: str,
    ip_value: str,
    challenge: str | None,
    force: bool,
) -> PreflightInfo:
    validated_model, validated_name = validate_device_identity(model, name)
    return PreflightInfo(
        address=address,
        model=validated_model,
        name=validated_name,
        firmware=validate_firmware(firmware, force=force),
        ip_address=parse_ipv4(ip_value),
        challenge=validate_challenge(challenge),
    )


def select_device(candidates: list[DeviceCandidate], selector: str | None) -> DeviceCandidate:
    if not candidates:
        raise SelectionError("No Chord 2go devices were discovered.")
    if len(candidates) == 1 and not selector:
        return candidates[0]
    if not selector:
        raise SelectionError("Multiple devices were discovered; choose one explicitly.")
    token = selector.strip()
    if not token:
        raise SelectionError("Device selector cannot be empty.")
    if token.isdigit():
        index = int(token, 10)
        if 1 <= index <= len(candidates):
            return candidates[index - 1]
        raise SelectionError(f"Device index {index} was out of range.")
    lowered = token.lower()
    exact_matches = [
        candidate
        for candidate in candidates
        if candidate.address.lower() == lowered or candidate.name.lower() == lowered
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    fuzzy_matches = [
        candidate
        for candidate in candidates
        if lowered in candidate.address.lower() or lowered in candidate.name.lower()
    ]
    if len(fuzzy_matches) == 1:
        return fuzzy_matches[0]
    raise SelectionError(f"Device selector {selector!r} did not match exactly one device.")


__all__ = [
    "ADVERTISING_UUID",
    "CHALLENGE_UUID",
    "DeviceCandidate",
    "FIRMWARE_VERSION_UUID",
    "IP_UUID",
    "MODEL_UUID",
    "NAME_UUID",
    "PreflightInfo",
    "RADIO_URL_UUID",
    "SUPPORTED_FIRMWARE",
    "build_preflight",
    "parse_ipv4",
    "parse_pin",
    "select_device",
    "select_local_ipv4",
    "validate_challenge",
    "validate_device_identity",
    "validate_firmware",
]
