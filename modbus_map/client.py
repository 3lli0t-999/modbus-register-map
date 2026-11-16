"""Small Modbus TCP client with retries and transaction-id tracking."""

from __future__ import annotations

import socket
import struct
import time

from .codec import (
    ModbusError,
    build_read,
    decode_pdu,
    decode_tcp,
    encode_tcp,
)


class ModbusTcpClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 502,
        unit: int = 1,
        timeout: float = 2.0,
        retries: int = 2,
    ):
        self.host = host
        self.port = port
        self.unit = unit
        self.timeout = timeout
        self.retries = retries
        self._transaction_id = 0
        self._sock: socket.socket | None = None

    # -- connection handling -------------------------------------------------
    def connect(self) -> None:
        if self._sock is not None:
            return
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        self._sock = sock

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def __enter__(self) -> "ModbusTcpClient":
        self.connect()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- transport -----------------------------------------------------------
    def _next_tid(self) -> int:
        self._transaction_id = (self._transaction_id + 1) & 0xFFFF
        return self._transaction_id

    def _recv_exact(self, count: int) -> bytes:
        assert self._sock is not None
        chunks = []
        remaining = count
        while remaining:
            chunk = self._sock.recv(remaining)
            if not chunk:
                raise ConnectionError("peer closed the connection")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def request(self, pdu: bytes) -> dict:
        """Send a PDU and return the decoded response."""
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                self.connect()
                assert self._sock is not None
                tid = self._next_tid()
                self._sock.sendall(encode_tcp(pdu, self.unit, tid))
                header = self._recv_exact(7)
                _, proto, length, unit = struct.unpack(">HHHB", header)
                if proto != 0:
                    raise ModbusError(f"bad protocol id {proto}")
                body = self._recv_exact(length - 1)
                frame = header + body
                resp_tid, resp_unit, resp_pdu = decode_tcp(frame)
                if resp_tid != tid:
                    raise ModbusError(f"transaction id mismatch ({resp_tid} != {tid})")
                if resp_unit != self.unit:
                    raise ModbusError(f"unit id mismatch ({resp_unit} != {self.unit})")
                decoded = decode_pdu(resp_pdu)
                if decoded.get("exception"):
                    raise ModbusError(
                        f"exception {decoded['exception_code']} "
                        f"({decoded['exception_name']}) from unit {resp_unit}",
                        exception_code=decoded["exception_code"],
                    )
                return decoded
            except (OSError, ModbusError) as exc:
                last_error = exc
                self.close()
                if isinstance(exc, ModbusError) and exc.exception_code is not None:
                    break  # the device answered, retrying will not help
                if attempt < self.retries:
                    time.sleep(0.25 * (attempt + 1))
        raise ModbusError(f"request failed: {last_error}") from last_error

    # -- convenience wrappers ------------------------------------------------
    def read_registers(self, address: int, count: int, function: int = 3) -> list[int]:
        result = self.request(build_read(function, address, count))
        return result["registers"]

    def read_coils(self, address: int, count: int) -> list[bool]:
        result = self.request(build_read(1, address, count))
        return result["bits"][:count]
