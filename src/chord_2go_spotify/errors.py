class Chord2GoSpotifyError(Exception):
    """Base error for chord_2go_spotify."""


class RuntimeDependencyError(Chord2GoSpotifyError):
    """Raised when an optional runtime dependency is unavailable."""


class ValidationError(Chord2GoSpotifyError):
    """Raised when device or CLI input validation fails."""


class UnsupportedFirmwareError(ValidationError):
    """Raised when the device firmware is unsupported."""


class SelectionError(ValidationError):
    """Raised when device selection fails."""


class BleOperationError(Chord2GoSpotifyError):
    """Raised when a BLE operation fails."""


class TransferError(Chord2GoSpotifyError):
    """Raised when payload transfer or reporting fails."""


class PayloadMissingError(TransferError):
    """Raised when the embedded payload archive is unavailable."""


class PacketError(Chord2GoSpotifyError):
    """Raised when an encrypted packet is invalid."""


class ChecksumError(PacketError):
    """Raised when packet checksum validation fails."""
