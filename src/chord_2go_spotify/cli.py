from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from dataclasses import dataclass
from ipaddress import IPv4Address
from typing import TextIO

from .ble import BleSession, discover_devices
from .device import DeviceCandidate, PreflightInfo, parse_pin, select_device, select_local_ipv4
from .errors import Chord2GoSpotifyError, SelectionError, ValidationError
from .transfer import (
    ReportServer,
    build_install_command,
    build_status_command,
    build_uninstall_command,
    load_payload_bundle,
    validate_action_report,
)
from .version import get_version_text


@dataclass(frozen=True, slots=True)
class OperationResult:
    action: str
    device: DeviceCandidate
    preflight: PreflightInfo
    host_ip: IPv4Address
    report: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chord-2go-spotify",
        description="Manage the Spotify payload on Chord 2go devices over BLE.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=get_version_text(),
        help="Print the project version and exit.",
    )
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--device", help="Device address, exact name, or 1-based prompt index.")
    shared.add_argument("--pin", help="Numeric device PIN. Empty input falls back to 0000.")
    shared.add_argument(
        "--force",
        action="store_true",
        help="Allow firmware other than 1.6.1.",
    )
    shared.add_argument(
        "--verbose",
        action="store_true",
        help="Emit extra progress details to stderr.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("install", parents=[shared], help="Install the payload.")
    subparsers.add_parser("status", parents=[shared], help="Read remote status.")
    subparsers.add_parser("uninstall", parents=[shared], help="Run the remote uninstall script.")
    return parser


async def run_async(
    argv: list[str] | None = None,
    *,
    input_func: callable = input,
    getpass_func: callable = getpass.getpass,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        pin = _resolve_pin(args.pin, getpass_func=getpass_func)
        devices = await discover_devices()
        device = await _resolve_device(devices, args.device, input_func=input_func, output=out)
        result = await run_operation(
            action=args.command,
            device=device,
            pin=pin,
            force=args.force,
            verbose=args.verbose,
            stderr=err,
        )
    except Chord2GoSpotifyError as error:
        print(f"Error: {error}", file=err)
        return 2
    print(format_result(result), file=out)
    return 0


async def run_operation(
    *,
    action: str,
    device: DeviceCandidate,
    pin: int,
    force: bool,
    verbose: bool,
    stderr: TextIO,
) -> OperationResult:
    _verbose(stderr, verbose, f"Connecting to {device.display_name} [{device.address}]...")
    async with BleSession(device, pin) as session:
        preflight = await session.read_preflight(force=force)
        host_ip = select_local_ipv4(preflight.ip_address)
        _verbose(stderr, verbose, f"Selected local host IPv4 {host_ip} for device {preflight.ip_address}.")
        bundle = load_payload_bundle() if action == "install" else None
        async with ReportServer(host_ip, bundle=bundle) as server:
            context = server.build_context()
            command = _build_command(action, context)
            _verbose(stderr, verbose, f"Sending {action} command via BLE.")
            await session.send_radio_command(command)
            report_timeout = 120.0 if action == "install" else 60.0
            report = validate_action_report(action, await server.wait_for_report(report_timeout))
    return OperationResult(
        action=action,
        device=device,
        preflight=preflight,
        host_ip=host_ip,
        report=report,
    )


def format_result(result: OperationResult) -> str:
    report = result.report.strip() or "(empty report)"
    return "\n".join(
        (
            f"Action: {result.action}",
            f"Device: {result.preflight.name} [{result.device.address}]",
            f"Model: {result.preflight.model}",
            f"Firmware: {result.preflight.firmware}",
            f"Device IP: {result.preflight.ip_address}",
            f"Host IP: {result.host_ip}",
            "Report:",
            report,
        )
    )


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run_async(argv))


async def _resolve_device(
    devices: list[DeviceCandidate],
    selector: str | None,
    *,
    input_func: callable,
    output: TextIO,
) -> DeviceCandidate:
    if not devices:
        raise SelectionError("No Chord 2go BLE advertisements were found.")
    if selector:
        return select_device(devices, selector)
    if len(devices) == 1:
        return devices[0]
    print("Discovered multiple devices:", file=output)
    for index, device in enumerate(devices, start=1):
        print(f"  [{index}] {device.display_name} [{device.address}]", file=output)
    try:
        selected = input_func("Select device [1]: ").strip() or "1"
    except (EOFError, KeyboardInterrupt) as error:
        raise SelectionError(
            "Multiple devices were found; rerun with --device for non-interactive use."
        ) from error
    return select_device(devices, selected)


def _resolve_pin(pin_value: str | None, *, getpass_func: callable) -> int:
    if pin_value is not None:
        return parse_pin(pin_value)
    try:
        entered = getpass_func("Chord 2go PIN [0000]: ")
    except (EOFError, KeyboardInterrupt) as error:
        raise ValidationError("PIN entry was cancelled; rerun with --pin for automation.") from error
    return parse_pin(entered)


def _build_command(action: str, context: object) -> str:
    if action == "install":
        return build_install_command(context)
    if action == "status":
        return build_status_command(context)
    if action == "uninstall":
        return build_uninstall_command(context)
    raise SelectionError(f"Unsupported action {action!r}.")


def _verbose(output: TextIO, enabled: bool, message: str) -> None:
    if enabled:
        print(message, file=output)


__all__ = ["OperationResult", "build_parser", "format_result", "main", "run_async", "run_operation"]
