# modbus-register-map

A small, dependency-free toolkit for the part of Modbus work that is usually done
with a spreadsheet and a lot of swearing: keeping the register map, the frame
decode and the engineering units in one place.

I wrote this after one too many commissioning jobs where the RTU documentation,
the PLC program and the SCADA tag database all disagreed about whether a value
was a 32-bit float with swapped words or a raw integer scaled by 10.

## What it does

- **Frame decode** for Modbus RTU and Modbus TCP, including exception responses.
- **JSON register maps** with types, word order, scaling, units and bitfields.
- **Tag reads** over Modbus TCP with retries and transaction-id checking.
- **CRC16/MODBUS** helper for checking captures by hand.

No third-party packages. Python 3.11+.

## Quick start

```bash
git clone https://github.com/3lli0t-999/modbus-register-map.git
cd modbus-register-map

python -m modbus_map decode "01 03 00 00 00 0A C5 CD"
python -m modbus_map crc "01 03 00 00 00 0A"
python -m modbus_map map examples/helix_north_wwtp.json
python -m modbus_map read examples/helix_north_wwtp.json LT-101.PV FT-102.PV \
    --host 10.42.7.11 --port 502
```

Sample output:

```
transport : RTU
function  : 3
function_name: read_holding_registers
byte_count: 10
registers : [0, 0, 0, 0, 0]
```

Reading a live device:

```
$ python -m modbus_map read examples/helix_north_wwtp.json --all \
      --host 127.0.0.1 --port 5020
LT-101.PV              3.42               m
FT-102.PV              118.7              m3/h
PT-103.PV              4.81               bar
TT-104.PV              61.2               degC
P-101.STATE            running,remote
AIT-105.PV             7.08               pH
VFD-101.SPD            43.5               Hz
FT-102.TOT             184223.6           m3
```

## Register map format

```json
{
  "site": "HELIX-NORTH",
  "unit_id": 1,
  "registers": [
    {"tag": "LT-101.PV", "address": 0, "type": "float32", "unit": "m"},
    {"tag": "FT-102.TOT", "address": 12, "type": "u32", "scale": 0.1, "unit": "m3"},
    {"tag": "P-101.STATE", "address": 8, "type": "bitfield",
     "bits": {"0": "running", "1": "fault", "2": "remote"}}
  ]
}
```

| Field | Notes |
|---|---|
| `type` | `u16`, `s16`, `u32`, `s32`, `float32`, `bitfield`, `enum` |
| `word_order` | `big` (default) or `little` for word-swapped 32-bit values |
| `scale` / `offset` | Applied after the raw decode: `value * scale + offset` |
| `bits` | Bit number to label mapping for `bitfield` |
| `enum` | Raw value to label mapping for `enum` |

The loader rejects overlapping register spans and unknown types, because a map
with two tags on the same address wastes a whole afternoon at site.

## Deliberate limits

- No Modbus RTU serial transport (the codec is there; serial line timing,
  turnaround delays and RS-485 adapters are left to a gateway).
- No write safety layer — writing tags is intentionally not exposed on the CLI.
- Only the function codes needed for reading and decoding are implemented.

## Tests

```bash
python -m unittest discover -s tests -v
```

## License

MIT.

---

Maintained by Glen Marsh · Helix Corp Ltd
