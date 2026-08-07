from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
from contextlib import suppress
from dataclasses import dataclass
from importlib import resources
from ipaddress import IPv4Address, ip_address
from typing import Final

from .errors import PayloadMissingError, TransferError, ValidationError

ARCHIVE_NAME: Final[str] = "spotify-install.tar.gz"
CHECKSUM_NAME: Final[str] = f"{ARCHIVE_NAME}.sha256"
REPORT_PATH: Final[str] = "/report"
UNINSTALL_PATH: Final[str] = "/usr/local/sbin/uninstall-chord-2go-spotify"
LIBRESPOT_PATH: Final[str] = "/usr/local/bin/librespot"
SERVICE_UNIT: Final[str] = "librespot.service"
REMOTE_ACTION_MARKER_PREFIX: Final[str] = "CHORD_2GO_SPOTIFY_REMOTE_ACTION="
REMOTE_EXIT_MARKER_PREFIX: Final[str] = "CHORD_2GO_SPOTIFY_REMOTE_EXIT="
INSTALL_SUCCESS_MARKER: Final[str] = "Installed Chord-2go-Spotify stable payload"
UNINSTALL_MISSING_MARKER: Final[str] = "uninstall_script_missing"
_REPORT_LIMIT: Final[int] = 16_384
_ATOM_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._:/@+=-]+$")
_SESSION_RE: Final[re.Pattern[str]] = re.compile(r"^[a-f0-9]{12,32}$")
_ACTION_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z]+$")
_SHELL_VARIABLE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REMOTE_EXIT_VARIABLE: Final[str] = "chord_2go_spotify_remote_exit"
_REPORT_ERROR_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bcommand not found\b", re.IGNORECASE),
    re.compile(r":\s*not found\b", re.IGNORECASE),
    re.compile(r"\bunbound variable\b", re.IGNORECASE),
    re.compile(r"^ERROR:", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class PayloadBundle:
    archive_name: str
    archive_bytes: bytes
    checksum_name: str
    checksum_bytes: bytes
    sha256_hex: str

    @classmethod
    def from_bytes(
        cls,
        archive_bytes: bytes,
        *,
        archive_name: str = ARCHIVE_NAME,
    ) -> "PayloadBundle":
        digest = hashlib.sha256(archive_bytes).hexdigest()
        checksum_name = f"{archive_name}.sha256"
        checksum_bytes = f"{digest}  {archive_name}\n".encode("ascii")
        return cls(
            archive_name=archive_name,
            archive_bytes=archive_bytes,
            checksum_name=checksum_name,
            checksum_bytes=checksum_bytes,
            sha256_hex=digest,
        )


@dataclass(frozen=True, slots=True)
class TransferContext:
    host_ip: IPv4Address
    port: int
    session_id: str

    @property
    def base_dir(self) -> str:
        return f"/tmp/chord-2go-spotify-{self.session_id}"

    @property
    def archive_path(self) -> str:
        return f"{self.base_dir}/{ARCHIVE_NAME}"

    @property
    def checksum_path(self) -> str:
        return f"{self.base_dir}/{CHECKSUM_NAME}"

    @property
    def extract_dir(self) -> str:
        return f"{self.base_dir}/payload"

    @property
    def install_script_path(self) -> str:
        return f"{self.extract_dir}/install.sh"

    @property
    def archive_url(self) -> str:
        return f"http://{self.host_ip}:{self.port}/{ARCHIVE_NAME}"

    @property
    def checksum_url(self) -> str:
        return f"http://{self.host_ip}:{self.port}/{CHECKSUM_NAME}"

    @property
    def report_url(self) -> str:
        return f"http://{self.host_ip}:{self.port}{REPORT_PATH}"


@dataclass(frozen=True, slots=True)
class RemoteActionReport:
    action: str
    exit_code: int
    body: str


class ReportServer:
    def __init__(
        self,
        host_ip: IPv4Address,
        *,
        bundle: PayloadBundle | None = None,
        report_limit: int = _REPORT_LIMIT,
    ) -> None:
        self.host_ip = host_ip
        self.bundle = bundle
        self.report_limit = report_limit
        self.download_counts: dict[str, int] = {}
        self.port: int = 0
        self._server: asyncio.AbstractServer | None = None
        self._report_future: asyncio.Future[str] | None = None

    async def __aenter__(self) -> "ReportServer":
        self._report_future = asyncio.get_running_loop().create_future()
        self._server = await asyncio.start_server(self._handle_connection, str(self.host_ip), 0)
        socket_name = self._server.sockets[0].getsockname()
        self.port = int(socket_name[1])
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        if self._report_future is not None and not self._report_future.done():
            self._report_future.cancel()
        return None

    def build_context(self, *, session_id: str | None = None) -> TransferContext:
        return make_transfer_context(self.host_ip, self.port, session_id=session_id)

    async def wait_for_report(self, timeout: float) -> str:
        if self._report_future is None:
            raise TransferError("Report server has not started yet.")
        try:
            return await asyncio.wait_for(self._report_future, timeout)
        except TimeoutError as error:
            raise TransferError("Timed out waiting for the device report.") from error

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5)
            if not request_line:
                return
            try:
                method, path, _version = request_line.decode("ascii", "replace").strip().split(" ", 2)
            except ValueError:
                await self._write_response(writer, 400, b"")
                return

            headers: dict[str, str] = {}
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5)
                if line in {b"\r\n", b"\n", b""}:
                    break
                name, separator, value = line.partition(b":")
                if not separator:
                    await self._write_response(writer, 400, b"")
                    return
                headers[name.decode("ascii", "ignore").lower()] = value.decode(
                    "ascii", "ignore"
                ).strip()

            if method == "GET":
                await self._handle_get(path, writer)
                return
            if method == "POST" and path == REPORT_PATH:
                await self._handle_report(reader, writer, headers)
                return
            await self._write_response(writer, 404, b"")
        except asyncio.IncompleteReadError:
            return
        finally:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

    async def _handle_get(self, path: str, writer: asyncio.StreamWriter) -> None:
        if self.bundle is None:
            await self._write_response(writer, 404, b"")
            return
        if path == f"/{self.bundle.archive_name}":
            self.download_counts[path] = self.download_counts.get(path, 0) + 1
            await self._write_response(
                writer,
                200,
                self.bundle.archive_bytes,
                content_type="application/gzip",
            )
            return
        if path == f"/{self.bundle.checksum_name}":
            self.download_counts[path] = self.download_counts.get(path, 0) + 1
            await self._write_response(
                writer,
                200,
                self.bundle.checksum_bytes,
                content_type="text/plain; charset=utf-8",
            )
            return
        await self._write_response(writer, 404, b"")

    async def _handle_report(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
    ) -> None:
        try:
            content_length = int(headers.get("content-length", "0"))
        except ValueError:
            self._set_report_error("Device report sent an invalid Content-Length header.")
            await self._write_response(writer, 400, b"")
            return
        if content_length < 0 or content_length > self.report_limit:
            self._set_report_error(
                f"Device report exceeded the {self.report_limit}-byte limit."
            )
            await self._write_response(writer, 413, b"")
            return
        body = await reader.readexactly(content_length) if content_length else b""
        if not self._report_future.done():
            self._report_future.set_result(body.decode("utf-8", "replace"))
        await self._write_response(writer, 204, b"")

    def _set_report_error(self, message: str) -> None:
        if self._report_future is not None and not self._report_future.done():
            self._report_future.set_exception(TransferError(message))

    async def _write_response(
        self,
        writer: asyncio.StreamWriter,
        status_code: int,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        reasons = {
            200: b"OK",
            204: b"No Content",
            400: b"Bad Request",
            404: b"Not Found",
            413: b"Payload Too Large",
        }
        reason = reasons.get(status_code, b"OK")
        writer.write(
            b"HTTP/1.1 "
            + str(status_code).encode("ascii")
            + b" "
            + reason
            + b"\r\n"
            + f"Content-Length: {len(body)}\r\n".encode("ascii")
            + f"Content-Type: {content_type}\r\n".encode("ascii")
            + b"Connection: close\r\n\r\n"
            + body
        )
        await writer.drain()


def load_payload_bundle() -> PayloadBundle:
    try:
        payload_file = resources.files("chord_2go_spotify").joinpath("data").joinpath(ARCHIVE_NAME)
        archive_bytes = payload_file.read_bytes()
    except FileNotFoundError as error:
        raise PayloadMissingError(
            f"Embedded payload {ARCHIVE_NAME!r} was not packaged in chord_2go_spotify.data."
        ) from error
    return PayloadBundle.from_bytes(archive_bytes)


def make_transfer_context(
    host_ip: IPv4Address | str,
    port: int,
    *,
    session_id: str | None = None,
) -> TransferContext:
    try:
        parsed_host = host_ip if isinstance(host_ip, IPv4Address) else ip_address(host_ip)
    except ValueError as error:
        raise ValidationError("Transfer host must be a valid IPv4 address.") from error
    if not isinstance(parsed_host, IPv4Address):
        raise ValidationError("Only IPv4 host addresses are supported for transfer.")
    if not 1 <= int(port) <= 65535:
        raise ValidationError("Transfer port must be between 1 and 65535.")
    token = session_id or secrets.token_hex(6)
    if not _SESSION_RE.fullmatch(token):
        raise ValidationError("Transfer session id must be 12-32 lowercase hex characters.")
    return TransferContext(host_ip=parsed_host, port=int(port), session_id=token)


def build_install_command(context: TransferContext) -> str:
    install_chain = "&&".join(
        (
            _brace_command("mkdir", "-p", context.base_dir),
            _brace_command("wget", "-q", "-O", context.archive_path, context.archive_url),
            _brace_command(
                "wget", "-q", "-O", context.checksum_path, context.checksum_url
            ),
            f"({_brace_command('cd', context.base_dir)}&&{_brace_command('sha256sum', '-c', CHECKSUM_NAME)})",
            _brace_command("mkdir", "-p", context.extract_dir),
            _brace_command("tar", "-xzf", context.archive_path, "-C", context.extract_dir),
            _brace_command("sh", context.install_script_path),
        )
    )
    return _wrap_action_command("install", install_chain, context, append_status=True)


def build_status_command(context: TransferContext) -> str:
    return _wrap_action_command("status", _status_body(), context)


def build_uninstall_command(context: TransferContext) -> str:
    uninstall = (
        f"if {_brace_command('test', '-x', UNINSTALL_PATH)}; "
        f"then {_brace_command('sh', UNINSTALL_PATH)}; "
        f"else {_brace_command('echo', UNINSTALL_MISSING_MARKER)}; {_brace_command('false')}; fi"
    )
    return _wrap_action_command("uninstall", uninstall, context, append_status=True)


def validate_action_report(expected_action: str, report: str) -> str:
    parsed = parse_action_report(report)
    if parsed.action != _validate_action_name(expected_action):
        raise TransferError(
            f"Device report was for {parsed.action!r}, not the requested {expected_action!r} action."
        )
    if parsed.exit_code != 0:
        raise TransferError(
            f"Remote {parsed.action} failed with exit code {parsed.exit_code}: "
            f"{_summarize_report_issue(parsed.body)}"
        )
    report_error = _find_report_error(parsed.body)
    if report_error is not None:
        raise TransferError(f"Remote {parsed.action} reported an error: {report_error}")
    if parsed.action == "install" and INSTALL_SUCCESS_MARKER not in parsed.body:
        raise TransferError(
            "Remote install did not emit the final payload success marker."
        )
    if parsed.action == "uninstall" and UNINSTALL_MISSING_MARKER in parsed.body:
        raise TransferError("Remote uninstall entrypoint was missing on the device.")
    return parsed.body


def parse_action_report(report: str) -> RemoteActionReport:
    action: str | None = None
    exit_code: int | None = None
    body_lines: list[str] = []
    for raw_line in report.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if line.startswith(REMOTE_ACTION_MARKER_PREFIX):
            action = line.removeprefix(REMOTE_ACTION_MARKER_PREFIX)
            continue
        if line.startswith(REMOTE_EXIT_MARKER_PREFIX):
            value = line.removeprefix(REMOTE_EXIT_MARKER_PREFIX)
            try:
                exit_code = int(value, 10)
            except ValueError as error:
                raise TransferError("Device report contained an invalid remote exit marker.") from error
            continue
        body_lines.append(raw_line)
    if action is None or exit_code is None:
        raise TransferError("Device report was missing the remote action exit markers.")
    return RemoteActionReport(
        action=_validate_action_name(action),
        exit_code=exit_code,
        body="\n".join(body_lines).strip(),
    )


def _status_body() -> str:
    return ";".join(
        (
            _brace_command("echo", "systemctl_is_active:"),
            (
                f"if {_brace_command('systemctl', 'is-active', SERVICE_UNIT)} >/dev/null 2>&1; "
                f"then {_brace_command('echo', 'active')}; "
                f"else {_brace_command('echo', 'inactive')}; fi"
            ),
            _brace_command("echo", "librespot_version:"),
            (
                f"if {_brace_command('test', '-x', LIBRESPOT_PATH)}; "
                f"then {_brace_command(LIBRESPOT_PATH, '--version')}; "
                f"else {_brace_command('echo', 'librespot_missing')}; fi"
            ),
        )
    )


def _report_sink(context: TransferContext) -> str:
    return _brace_command("curl", "-fsS", "--data-binary", "@-", context.report_url)


def _wrap_action_command(
    action: str,
    action_body: str,
    context: TransferContext,
    *,
    append_status: bool = False,
) -> str:
    action_name = _validate_action_name(action)
    sections = [f"({action_body})", f"{_REMOTE_EXIT_VARIABLE}=$?"]
    if append_status:
        sections.append(_status_body())
    sections.append(_brace_command("echo", f"{REMOTE_ACTION_MARKER_PREFIX}{action_name}"))
    sections.append(_echo_marker_variable(REMOTE_EXIT_MARKER_PREFIX, _REMOTE_EXIT_VARIABLE))
    return f"nothing ;({';'.join(sections)}) 2>&1|{_report_sink(context)}"


def _brace_command(*parts: str) -> str:
    return "{" + ",".join(_validate_atom(part) for part in parts) + "}"


def _echo_marker_variable(prefix: str, variable_name: str) -> str:
    _validate_atom(prefix)
    if not _SHELL_VARIABLE_RE.fullmatch(variable_name):
        raise ValidationError(f"Unsafe shell variable rejected: {variable_name!r}")
    return f"echo {prefix}${variable_name}"


def _find_report_error(report_body: str) -> str | None:
    for line in report_body.splitlines():
        stripped = line.strip()
        if stripped and any(pattern.search(stripped) for pattern in _REPORT_ERROR_PATTERNS):
            return stripped
    return None


def _summarize_report_issue(report_body: str) -> str:
    report_error = _find_report_error(report_body)
    if report_error is not None:
        return report_error
    for line in reversed(report_body.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return "no remote diagnostics were captured"


def _validate_action_name(value: str) -> str:
    if not _ACTION_RE.fullmatch(value):
        raise TransferError(f"Invalid remote action marker value: {value!r}")
    return value


def _validate_atom(value: str) -> str:
    if not _ATOM_RE.fullmatch(value):
        raise ValidationError(f"Unsafe shell token rejected: {value!r}")
    return value


__all__ = [
    "ARCHIVE_NAME",
    "CHECKSUM_NAME",
    "INSTALL_SUCCESS_MARKER",
    "LIBRESPOT_PATH",
    "PayloadBundle",
    "RemoteActionReport",
    "REPORT_PATH",
    "REMOTE_ACTION_MARKER_PREFIX",
    "REMOTE_EXIT_MARKER_PREFIX",
    "ReportServer",
    "SERVICE_UNIT",
    "TransferContext",
    "UNINSTALL_MISSING_MARKER",
    "UNINSTALL_PATH",
    "build_install_command",
    "build_status_command",
    "build_uninstall_command",
    "load_payload_bundle",
    "make_transfer_context",
    "parse_action_report",
    "validate_action_report",
]
