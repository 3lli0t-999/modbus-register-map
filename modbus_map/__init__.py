"""modbus_map - pragmatic Modbus register map tooling."""

__version__ = "0.4.1"

from .codec import crc16, decode_pdu, decode_rtu, decode_tcp, encode_rtu, encode_tcp
from .register_map import Register, RegisterMap

__all__ = [
    "Register",
    "RegisterMap",
    "crc16",
    "decode_pdu",
    "decode_rtu",
    "decode_tcp",
    "encode_rtu",
    "encode_tcp",
    "__version__",
]
