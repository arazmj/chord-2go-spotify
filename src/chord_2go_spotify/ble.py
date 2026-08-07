from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Final

from .crypto import decrypt_packet, encrypt_packet
from .device import (
    ADVERTISING_UUID,
    CHALLENGE_UUID,
    DeviceCandidate,
    FIRMWARE_VERSION_UUID,
    IP_UUID,
    MODEL_UUID,
    NAME_UUID,
    RADIO_URL_UUID,
    PreflightInfo,
    build_preflight,
)
from .errors import BleOperationError, PacketError, RuntimeDependencyError, ValidationError

_DISCOVERY_ATTEMPTS: Final[int] = 3
_TRANSIENT_MARKERS: Final[tuple[str, ...]] = (
    "timeout",
    "timed out",
    "not connected",
    "in progress",
    "temporarily unavailable",
    "busy",
    "disconnected",
)
_MISSING_MARKERS: Final[tuple[str, ...]] = (
    "not found",
    "not present",
    "unknown object",
    "no such characteristic",
)


@dataclass(slots=True)
class BleSession:
    candidate: DeviceCandidate
    pin: int
    timeout: float = 20.0
    retries: int = 3
    client_factory: Any | None = None
    _client: Any | None = field(init=False, default=None, repr=False)
    _characteristics: set[str] = field(init=False, default_factory=set, repr=False)

    async def __aenter__(self) -> "BleSession":
        if self.client_factory is None:
            bleak_client, _ = require_bleak()
            self.client_factory = bleak_client
        target = self.candidate.native if self.candidate.native is not None else self.candidate.address
        self._client = self.client_factory(target, timeout=self.timeout)
        if hasattr(self._client, "__aenter__"):
            await self._client.__aenter__()
        elif hasattr(self._client, "connect"):
            await self._client.connect()
        else:
            raise BleOperationError("BLE client does not support async connection.")
        await self._load_characteristics()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._client is None:
            return None
        if hasattr(self._client, "__aexit__"):
            await self._client.__aexit__(exc_type, exc, tb)
        elif hasattr(self._client, "disconnect"):
            await self._client.disconnect()
        self._client = None
        return None

    async def _load_characteristics(self) -> None:
        if self._client is None:
            return
        services = getattr(self._client, "services", None)
        if not services and hasattr(self._client, "get_services"):
            try:
                services = await self._client.get_services()
            except Exception:
                services = None
        if not services:
            return
        for service in services:
            for characteristic in getattr(service, "characteristics", ()):
                self._characteristics.add(str(characteristic.uuid).lower())

    async def _retry(self, label: str, operation: Any) -> Any:
        for attempt in range(1, self.retries + 1):
            try:
                return await operation()
            except Exception as error:
                message = str(error).lower()
                if attempt >= self.retries or not any(
                    marker in message for marker in _TRANSIENT_MARKERS
                ):
                    raise BleOperationError(f"{label} failed: {error}") from error
                await asyncio.sleep(0.25 * attempt)
        raise BleOperationError(f"{label} failed.")

    async def read_text(self, label: str, uuid: str, *, optional: bool = False) -> str | None:
        if optional and self._characteristics and uuid.lower() not in self._characteristics:
            return None
        try:
            encrypted = await self._retry(
                f"BLE read of {label}",
                lambda: self._client.read_gatt_char(uuid),
            )
        except BleOperationError as error:
            if optional and any(marker in str(error).lower() for marker in _MISSING_MARKERS):
                return None
            raise
        try:
            return decrypt_packet(bytes(encrypted), self.pin)
        except PacketError as error:
            raise ValidationError(
                f"Failed to decrypt device {label}; verify the selected PIN."
            ) from error

    async def read_preflight(self, *, force: bool) -> PreflightInfo:
        model = await self.read_text("model", MODEL_UUID)
        name = await self.read_text("name", NAME_UUID)
        firmware = await self.read_text("firmware", FIRMWARE_VERSION_UUID)
        ip_value = await self.read_text("IPv4", IP_UUID)
        challenge = await self.read_text("challenge", CHALLENGE_UUID, optional=True)
        return build_preflight(
            address=self.candidate.address,
            model=model or "",
            name=name or "",
            firmware=firmware or "",
            ip_value=ip_value or "",
            challenge=challenge,
            force=force,
        )

    async def send_radio_command(self, command: str) -> None:
        packet = encrypt_packet(command, self.pin)
        await self._retry(
            "BLE write to radio URL",
            lambda: self._client.write_gatt_char(RADIO_URL_UUID, packet, response=True),
        )


async def discover_devices(*, timeout: float = 12.0, attempts: int = _DISCOVERY_ATTEMPTS) -> list[DeviceCandidate]:
    _, bleak_scanner = require_bleak()
    matches: dict[str, DeviceCandidate] = {}
    for _ in range(attempts):
        discovered = await bleak_scanner.discover(timeout=timeout, return_adv=True)
        entries = discovered.values() if hasattr(discovered, "values") else discovered
        for entry in entries:
            device, advertisement = entry
            service_uuids = tuple(sorted(_extract_service_uuids(advertisement)))
            name = _extract_name(device, advertisement)
            if ADVERTISING_UUID in service_uuids or "2go" in name.lower() or "chord" in name.lower():
                address = getattr(device, "address", "") or getattr(device, "name", "")
                matches.setdefault(
                    address,
                    DeviceCandidate(
                        address=address,
                        name=name,
                        service_uuids=service_uuids,
                        native=device,
                    ),
                )
    return list(matches.values())


def require_bleak() -> tuple[Any, Any]:
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError as error:
        raise RuntimeDependencyError(
            "BLE operations require the 'bleak' package. Install bleak before running install, status, or uninstall."
        ) from error
    return BleakClient, BleakScanner


def _extract_name(device: object, advertisement: object) -> str:
    return (
        getattr(advertisement, "local_name", None)
        or getattr(device, "name", None)
        or getattr(device, "address", "")
    )


def _extract_service_uuids(advertisement: object) -> set[str]:
    raw_uuids = getattr(advertisement, "service_uuids", ()) or ()
    return {str(uuid).lower() for uuid in raw_uuids}


__all__ = ["BleSession", "discover_devices", "require_bleak"]
