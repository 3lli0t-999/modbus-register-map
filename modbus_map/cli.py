"""Command line entry point: python -m modbus_map ..."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .client import ModbusTcpClient
from .codec import (
    FUNCTION_NAMES,
    ModbusError,
    crc16,
    decode_pdu,
    decode_rtu,
    decode_tcp,
    encode_rtu,
    encode_tcp,
)
from .register_map import RegisterMap


def _parse_hex(text: str) -> bytes:
    cleaned = text.replace(" ", "").replace("-", "").replace(":", "")
    if cleaned.lower().startswith("0x"):
        cleaned = cleaned[2:]
    if len(cleaned) % 2:
        raise SystemExit("hex string must contain an even number of digits")
    return bytes.fromhex(cleaned)


def cmd_decode(args: argparse.Namespace) -> int:
    raw = _parse_hex(args.frame)
    used = "PDU"
    try:
        tid, unit, pdu = decode_tcp(raw)
        used = "MBAP (Modbus TCP)"
        meta = {"transport": used, "transaction_id": tid, "unit": unit}
    except ModbusError:
        unit, pdu = decode_rtu(raw)
        used = "RTU"
        meta = {"transport": used, "unit": unit, "crc": "ok"}

    decoded = decode_pdu(pdu)
    output = {**meta, **decoded}
    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"transport : {used}")
        for key, value in decoded.items():
            print(f"{key:10}: {value}")
    return 0


def cmd_crc(args: argparse.Namespace) -> int:
    data = _parse_hex(args.data)
    value = crc16(data)
    print(f"0x{value:04X}  (on the wire: {value & 0xFF:02X} {value >> 8:02X})")
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    regmap = RegisterMap.load(args.map)
    print(f"site={regmap.site} unit={regmap.unit_id} registers={len(regmap.registers)}")
    print(f"{'tag':<22}{'addr':>6}{'type':>10}{'len':>5} {'unit':<10}description")
    for reg in sorted(regmap.registers, key=lambda r: r.address):
        print(
            f"{reg.tag:<22}{reg.address:>6}{reg.type:>10}{reg.words:>5}"
            f" {reg.unit:<10}{reg.description}"
        )
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    regmap = RegisterMap.load(args.map)
    targets = regmap.registers if args.all else [regmap.by_tag(t) for t in args.tags]
    if not targets:
        raise SystemExit("nothing to read: pass tag names or --all")
    if not args.all and len(targets) != len(args.tags):
        raise SystemExit("unknown tag in request")
    if not 1 <= len(targets) <= 120:
        raise SystemExit("read at most 120 tags per invocation (keep PDUs small)")

    results = {}
    with ModbusTcpClient(
        args.host, args.port, regmap.unit_id, args.timeout, args.retries
    ) as client:
        for reg in targets:
            raw = client.read_registers(reg.address, reg.words)
            value = reg.decode(raw)
            results[reg.tag] = {
                "value": value,
                "unit": reg.unit,
                "raw": raw,
                "address": reg.address,
            }

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for tag, item in results.items():
            value = item["value"]
            if isinstance(value, dict):
                value = ",".join(value["active"]) or "-"
            print(f"{tag:<22} {value!s:<18} {item['unit']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="modbus-map",
        description="Inspect Modbus frames and read tags from a JSON register map.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("decode", help="decode a hex RTU or TCP frame")
    p.add_argument("frame", help='e.g. "01 03 00 00 00 0A C5 CD"')
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_decode)

    p = sub.add_parser("crc", help="compute CRC16/MODBUS over hex bytes")
    p.add_argument("data")
    p.set_defaults(func=cmd_crc)

    p = sub.add_parser("map", help="print a register map")
    p.add_argument("map")
    p.set_defaults(func=cmd_map)

    p = sub.add_parser("read", help="read tags from a Modbus TCP device")
    p.add_argument("map")
    p.add_argument("tags", nargs="*")
    p.add_argument("--all", action="store_true", help="read every tag in the map")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=502)
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--retries", type=int, default=2)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_read)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (KeyError, ValueError, ModbusError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
