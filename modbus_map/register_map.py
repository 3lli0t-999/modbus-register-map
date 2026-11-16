"""Register map loading, engineering-value decoding and scaling."""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

WORD_TYPES = {
    "u16": ("H", 1),
    "s16": ("h", 1),
    "u32": ("I", 2),
    "s32": ("i", 2),
    "float32": ("f", 2),
}

BIT_ACCESS = {"read", "write", "rw"}


@dataclass
class Register:
    tag: str
    address: int
    type: str = "u16"
    words: int = 1
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    description: str = ""
    word_order: str = "big"  # big | little (word swap only)
    bits: dict[int, str] = field(default_factory=dict)
    enum: dict[int, str] = field(default_factory=dict)
    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self) -> None:
        if self.type in WORD_TYPES:
            self.words = WORD_TYPES[self.type][1]
        elif self.type == "bitfield":
            self.words = max(self.words, 1)
        else:
            raise ValueError(f"{self.tag}: unsupported type {self.type!r}")

    @property
    def end_address(self) -> int:
        return self.address + self.words - 1

    def decode(self, registers: list[int]) -> float | int | dict:
        """Decode raw holding registers into an engineering value."""
        raw = registers[: self.words]
        if self.type == "bitfield":
            word = raw[0]
            active = [name for bit, name in self.bits.items() if word >> bit & 1]
            return {"raw": word, "active": active}
        if self.type == "enum":
            return self.enum.get(raw[0], raw[0])
        if len(raw) < self.words:
            raise ValueError(f"{self.tag}: expected {self.words} register(s), got {len(raw)}")

        if self.words == 2 and self.word_order == "little":
            raw = [raw[1], raw[0]]

        fmt, _ = WORD_TYPES[self.type]
        (value,) = struct.unpack(">" + fmt, b"".join(struct.pack(">H", w) for w in raw))
        return value * self.scale + self.offset

    def encode(self, value: float) -> list[int]:
        """Inverse of :meth:`decode`, used by test outstation tooling."""
        raw_value = (float(value) - self.offset) / self.scale
        fmt, _ = WORD_TYPES[self.type]
        if self.type.startswith("u"):
            raw_value = int(round(raw_value))
        payload = struct.pack(">" + fmt, raw_value)
        words = [struct.unpack(">H", payload[i : i + 2])[0] for i in range(0, len(payload), 2)]
        if self.words == 2 and self.word_order == "little":
            words.reverse()
        return words


class RegisterMap:
    def __init__(self, document: dict, source: str | None = None):
        self.site: str = document.get("site", "unnamed")
        self.unit_id: int = int(document.get("unit_id", 1))
        self.description: str = document.get("description", "")
        self.source = source
        self.registers: list[Register] = []
        for entry in document.get("registers", []):
            reg = Register(**{k: v for k, v in entry.items() if k in Register.__dataclass_fields__})
            if reg.type == "enum" and not reg.words:
                reg.words = 1
            self.registers.append(reg)
        self._check_overlaps()

    def _check_overlaps(self) -> None:
        seen: set[int] = set()
        for reg in self.registers:
            span = set(range(reg.address, reg.end_address + 1))
            clash = span & seen
            if clash:
                raise ValueError(
                    f"{reg.tag} overlaps existing register(s) at "
                    f"{', '.join(str(a) for a in sorted(clash))}"
                )
            seen |= span

    @classmethod
    def load(cls, path: str | Path) -> "RegisterMap":
        path = Path(path)
        return cls(json.loads(path.read_text()), source=str(path))

    def __iter__(self):
        return iter(self.registers)

    def by_tag(self, tag: str) -> Register:
        for reg in self.registers:
            if reg.tag == tag:
                return reg
        raise KeyError(tag)

    def scalar_registers(self) -> list[Register]:
        return [r for r in self.registers if r.type != "bitfield"]

    def max_address(self) -> int:
        return max((r.end_address for r in self.registers), default=0)
