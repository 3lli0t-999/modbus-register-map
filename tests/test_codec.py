import unittest

from modbus_map.codec import (
    ModbusError,
    append_crc,
    build_read,
    crc16,
    decode_pdu,
    decode_rtu,
    decode_tcp,
    encode_rtu,
    encode_tcp,
)
from modbus_map.register_map import Register, RegisterMap


class CodecTests(unittest.TestCase):
    def test_crc_known_vector(self):
        # Unit 1, read 10 holding registers from 0 (classic example frame).
        self.assertEqual(crc16(bytes.fromhex("01030000000A")), 0xCDC5)

    def test_rtu_roundtrip(self):
        frame = encode_rtu(build_read(3, 0, 10), unit=1)
        self.assertEqual(frame, bytes.fromhex("01030000000AC5CD"))
        unit, pdu = decode_rtu(frame)
        self.assertEqual(unit, 1)
        self.assertEqual(pdu, bytes.fromhex("030000000A"))

    def test_rtu_rejects_corrupt_crc(self):
        frame = bytearray(encode_rtu(build_read(3, 0, 1), 1))
        frame[-1] ^= 0xFF
        with self.assertRaises(ModbusError):
            decode_rtu(bytes(frame))

    def test_tcp_roundtrip(self):
        frame = encode_tcp(build_read(4, 100, 2), unit=7, transaction_id=42)
        tid, unit, pdu = decode_tcp(frame)
        self.assertEqual((tid, unit), (42, 7))
        self.assertEqual(pdu, build_read(4, 100, 2))

    def test_decode_read_response(self):
        pdu = bytes.fromhex("030601004142007F")
        decoded = decode_pdu(pdu)
        self.assertEqual(decoded["registers"], [256, 16706, 127])

    def test_decode_exception(self):
        decoded = decode_pdu(bytes([0x83, 0x02]))
        self.assertTrue(decoded["exception"])
        self.assertEqual(decoded["exception_name"], "illegal_data_address")

    def test_crc_reserved_range_guard(self):
        with self.assertRaises(ModbusError):
            build_read(3, 0, 0)


class RegisterMapTests(unittest.TestCase):
    def test_float32_big_word_order(self):
        reg = Register(tag="LT-101.PV", address=0, type="float32")
        self.assertAlmostEqual(reg.decode([0x42C8, 0x0000]), 100.0)

    def test_float32_swapped_word_order(self):
        reg = Register(tag="X", address=0, type="float32", word_order="little")
        self.assertAlmostEqual(reg.decode([0x0000, 0x42C8]), 100.0)

    def test_scaled_integer(self):
        reg = Register(tag="AIT-105.PV", address=9, type="u16", scale=0.01)
        self.assertAlmostEqual(reg.decode([712]), 7.12)

    def test_bitfield(self):
        reg = Register(
            tag="P-101.STATE",
            address=8,
            type="bitfield",
            bits={0: "running", 1: "fault", 2: "remote"},
        )
        self.assertEqual(reg.decode([0b101])["active"], ["running", "remote"])

    def test_encode_roundtrip(self):
        reg = Register(tag="PT-103.PV", address=4, type="float32")
        self.assertAlmostEqual(reg.decode(reg.encode(7.25)), 7.25)

    def test_overlap_rejected(self):
        document = {
            "registers": [
                {"tag": "A", "address": 0, "type": "float32"},
                {"tag": "B", "address": 1, "type": "u16"},
            ]
        }
        with self.assertRaises(ValueError):
            RegisterMap(document)


if __name__ == "__main__":
    unittest.main()
