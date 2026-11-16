"""Modbus RTU / TCP frame codec.

Deliberately dependency free: this module is used both in test rigs and in
small field gateways where pulling in a full Modbus stack is not an option.

References: MODBUS Application Protocol V1.1b3, MODBUS over Serial Line V1.02.
"""

from __future__ import annotations

import struct

FUNCTION_NAMES = {
    1: "read_coils",
    2: "read_discrete_inputs",
    3: "read_holding_registers",
    4: "read_input_registers",
    5: "write_single_coil",
    6: "write_single_register",
    15: "write_multiple_coils",
    16: "write_multiple_registers",
    22: "mask_write_register",
    23: "read_write_multiple_registers",
}

EXCEPTION_NAMES = {
    1: "illegal_function",
    2: "illegal_data_address",
    3: "illegal_data_value",
    4: "slave_device_failure",
    5: "acknowledge",
    6: "slave_device_busy",
    8: "memory_parity_error",
    10: "gateway_path_unavailable",
    11: "gateway_target_failed_to_respond",
}


class ModbusError(Exception):
    """Raised for malformed frames or exception responses."""

    def __init__(self, message: str, exception_code: int | None = None):
        super().__init__(message)
        self.exception_code = exception_code


def crc16(data: bytes) -> int:
    """CRC-16/MODBUS (polynomial 0xA001 reflected, init 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def append_crc(pdu: bytes) -> bytes:
    """Return ``pdu`` with the little-endian CRC appended."""
    return pdu + struct.pack("<H", crc16(pdu))


def crc_valid(frame: bytes) -> bool:
    if len(frame) < 4:
        return False
    return crc16(frame[:-2]) == struct.unpack("<H", frame[-2:])[0]


# --------------------------------------------------------------------------
# PDU construction
# --------------------------------------------------------------------------


def build_read(function: int, address: int, count: int) -> bytes:
    if function not in (1, 2, 3, 4) or function not in FUNCTION_NAMES:
        raise ModbusError(f"function {function} is not a read function")
    if not 0 <= address <= 0xFFFF:
        raise ModbusError("address out of range")
    if not 1 <= count <= 2000:
        raise ModbusError("quantity out of range for a read request")
    return struct.pack(">BHH", function, address, count)


def build_write_single_coil(address: int, value: bool) -> bytes:
    return struct.pack(">BHH", 5, address, 0xFF00 if value else 0x0000)


def build_write_single_register(address: int, value: int) -> bytes:
    if not 0 <= value <= 0xFFFF:
        raise ModbusError("register value must fit in 16 bits")
    return struct.pack(">BHH", 6, address, value)


def build_write_multiple_registers(
    address: int, values: list[int], unit: int = 1
) -> bytes:
    if not 1 <= len(values) <= 123:
        raise ModbusError("write multiple supports 1..123 registers per PDU")
    payload = struct.pack(">BHHB", 16, address, len(values), len(values) * 2)
    return payload + b"".join(struct.pack(">H", v & 0xFFFF) for v in values)


# --------------------------------------------------------------------------
# PDU decoding
# --------------------------------------------------------------------------


def decode_pdu(pdu: bytes) -> dict:
    """Decode a request or response PDU into a plain dict.

    The shape is intentionally loose so callers can log unknown function
    codes without special-casing them.
    """
    if not pdu:
        raise ModbusError("empty PDU")

    function = pdu[0]
    if function & 0x80:
        code = pdu[1] if len(pdu) > 1 else None
        return {
            "function": function & 0x7F,
            "function_name": FUNCTION_NAMES.get(function & 0x7F, "unknown"),
            "exception": True,
            "exception_code": code,
            "exception_name": EXCEPTION_NAMES.get(code, "unknown"),
        }

    name = FUNCTION_NAMES.get(function, "unknown")

    # Read requests are 5 bytes; a 5-byte read response is not valid because
    # the byte count would have to be odd.
    if function in (1, 2, 3, 4) and len(pdu) == 5:
        address, quantity = struct.unpack(">HH", pdu[1:5])
        return {
            "function": function,
            "function_name": name,
            "request": True,
            "address": address,
            "quantity": quantity,
        }

    if function in (1, 2) and len(pdu) >= 2:
        byte_count = pdu[1]
        bits = []
        for index, byte in enumerate(pdu[2 : 2 + byte_count]):
            for bit in range(8):
                bits.append(bool(byte >> bit & 1))
        return {
            "function": function,
            "function_name": name,
            "byte_count": byte_count,
            "bits": bits[: byte_count * 8],
        }

    if function in (3, 4) and len(pdu) >= 2:
        byte_count = pdu[1]
        registers = [
            struct.unpack(">H", pdu[i : i + 2])[0]
            for i in range(2, 2 + byte_count, 2)
        ]
        return {
            "function": function,
            "function_name": name,
            "byte_count": byte_count,
            "registers": registers,
        }

    if function in (5, 6) and len(pdu) >= 5:
        address, value = struct.unpack(">HH", pdu[1:5])
        return {
            "function": function,
            "function_name": name,
            "address": address,
            "value": value,
            "bool_value": value == 0xFF00 if function == 5 else None,
            "echo": True,
        }

    if function in (15, 16) and len(pdu) >= 5:
        address, quantity = struct.unpack(">HH", pdu[1:5])
        return {
            "function": function,
            "function_name": name,
            "address": address,
            "quantity": quantity,
        }

    return {
        "function": function,
        "function_name": name,
        "raw": pdu.hex(),
    }


# --------------------------------------------------------------------------
# RTU framing (unit id + PDU + CRC16, little endian)
# --------------------------------------------------------------------------


def encode_rtu(pdu: bytes, unit: int = 1) -> bytes:
    return append_crc(bytes([unit & 0xFF]) + pdu)


def decode_rtu(frame: bytes) -> tuple[int, bytes]:
    if len(frame) < 4:
        raise ModbusError("RTU frame too short")
    if not crc_valid(frame):
        raise ModbusError("bad CRC16")
    return frame[0], frame[1:-2]


# --------------------------------------------------------------------------
# TCP framing (MBAP header: tid, proto=0, length, unit)
# --------------------------------------------------------------------------


def encode_tcp(pdu: bytes, unit: int = 1, transaction_id: int = 1) -> bytes:
    header = struct.pack(">HHHB", transaction_id, 0, len(pdu) + 1, unit & 0xFF)
    return header + pdu


def decode_tcp(frame: bytes) -> tuple[int, int, bytes]:
    """Return ``(transaction_id, unit, pdu)``."""
    if len(frame) < 8:
        raise ModbusError("MBAP frame too short")
    tid, proto, length, unit = struct.unpack(">HHHB", frame[:7])
    if proto != 0:
        raise ModbusError(f"unexpected protocol id {proto}")
    pdu = frame[7:]
    if length != len(pdu) + 1:
        raise ModbusError(
            f"MBAP length {length} does not match payload {len(pdu) + 1}"
        )
    return tid, unit, pdu
