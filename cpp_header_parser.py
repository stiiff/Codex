"""Parser for the hardware-oriented subset of C/C++ struct declarations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from struct_layout_optimizer import Array, Field, Reserved, Struct, Type, UInt, Union


class HeaderParseError(ValueError):
    pass


@dataclass(frozen=True)
class _RawField:
    name: str
    type_name: str
    bit_width: int | None
    array_count: int | None


@dataclass(frozen=True)
class _RawComposite:
    name: str
    kind: str
    fields: tuple[_RawField, ...]


_TOKEN = re.compile(r"[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*|\d+|[{}\[\];:,]")
_INTEGER = re.compile(r"(?:std::)?u?int(\d+)(?:_t)?$", re.IGNORECASE)
_RSVD = re.compile(r"(?:^|_)(?:rsvd|reserved)(?:_|$)", re.IGNORECASE)


def _clean(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    source = re.sub(r"//.*?$", "", source, flags=re.MULTILINE)
    source = re.sub(r"^\s*#.*?$", "", source, flags=re.MULTILINE)
    return source


class _Parser:
    def __init__(self, source: str):
        self.tokens = _TOKEN.findall(_clean(source))
        self.pos = 0
        self.definitions: dict[str, _RawComposite] = {}
        self.order: list[str] = []

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> str:
        token = self.peek()
        if token is None:
            raise HeaderParseError("unexpected end of header")
        self.pos += 1
        return token

    def skip_to(self, token: str) -> None:
        while self.peek() is not None and self.take() != token:
            pass

    def parse(self) -> tuple[dict[str, _RawComposite], list[str]]:
        while self.peek() is not None:
            is_typedef = self.peek() == "typedef"
            if is_typedef:
                self.take()
            if self.peek() not in ("struct", "union"):
                self.skip_to(";")
                continue
            kind = self.take()
            tag = None
            if self.peek() not in ("{", None):
                tag = self.take()
            if self.peek() != "{":
                self.skip_to(";")
                continue
            self.take()
            fields = self._fields()
            if self.take() != "}":
                raise HeaderParseError("missing closing brace")
            alias = None
            if self.peek() not in (";", None):
                alias = self.take()
            self.skip_to(";")
            name = alias if is_typedef and alias else tag
            if not name:
                raise HeaderParseError("anonymous struct/union requires a typedef name")
            raw = _RawComposite(name, kind, tuple(fields))
            self.definitions[name] = raw
            if tag and tag != name:
                self.definitions[tag] = raw
            self.order.append(name)
        return self.definitions, self.order

    def _fields(self) -> list[_RawField]:
        fields: list[_RawField] = []
        while self.peek() not in ("}", None):
            if self.peek() in ("struct", "union"):
                self.take()
            type_name = self.take()
            if self.peek() in (";", "}", None):
                self.skip_to(";")
                continue
            name = self.take()
            bit_width = None
            array_count = None
            if self.peek() == ":":
                self.take()
                bit_width = int(self.take())
            if self.peek() == "[":
                self.take()
                array_count = int(self.take())
                if self.take() != "]":
                    raise HeaderParseError(f"missing ] after {name}")
            if self.peek() != ";":
                raise HeaderParseError(f"unsupported declaration near field {name}")
            self.take()
            fields.append(_RawField(name, type_name, bit_width, array_count))
        return fields


def parse_header_text(source: str, root: str | None = None) -> Type:
    """Parse declarations and return the selected root type.

    If ``root`` is omitted, the last struct or union definition is selected.
    """
    definitions, order = _Parser(source).parse()
    if not order:
        raise HeaderParseError("no struct or union definition found")
    root_name = root or order[-1]
    if root_name not in definitions:
        raise HeaderParseError(f"unknown root type: {root_name}")

    cache: dict[str, Type] = {}
    resolving: set[str] = set()

    def resolve(name: str) -> Type:
        integer = _INTEGER.fullmatch(name)
        if integer:
            return UInt(int(integer.group(1)))
        if name in cache:
            return cache[name]
        if name in resolving:
            raise HeaderParseError(f"recursive by-value type is unsupported: {name}")
        raw = definitions.get(name)
        if raw is None:
            raise HeaderParseError(f"unknown field type: {name}")
        resolving.add(name)
        converted: list[Field] = []
        for field in raw.fields:
            if _RSVD.search(field.name):
                width = field.bit_width
                if width is None:
                    match = _INTEGER.fullmatch(field.type_name)
                    width = int(match.group(1)) if match else None
                if width is None:
                    raise HeaderParseError(f"cannot infer rsvd width: {field.name}")
                field_type: Type = Reserved(width)
            elif field.bit_width is not None:
                field_type = UInt(field.bit_width)
            else:
                field_type = resolve(field.type_name)
            if field.array_count is not None:
                field_type = Array(field_type, field.array_count)
            converted.append(Field(field.name, field_type))
        result: Type = (
            Struct(raw.name, converted)
            if raw.kind == "struct"
            else Union(raw.name, converted)
        )
        resolving.remove(name)
        cache[name] = result
        return result

    return resolve(root_name)


def parse_header(path: str | Path, root: str | None = None) -> Type:
    return parse_header_text(Path(path).read_text(encoding="utf-8"), root)
