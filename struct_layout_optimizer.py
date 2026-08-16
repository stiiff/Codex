"""Exact bit-field layout optimizer for small hardware-facing structures.

The optimizer never invents padding.  Reserved fields (``Reserved``) are the
only bits that may be split and placed between fields.  Layouts are recursive:
an embedded structure is optimized together with its parent, and every element
of an array uses the same element layout.

The search is exhaustive and is consequently intended for small structures.
For larger inputs a branch-and-bound or heuristic front-end can reuse the
``evaluate`` function and data model in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations, product
from typing import Iterable, Iterator, Sequence


@dataclass(frozen=True)
class UInt:
    bits: int

    def __post_init__(self) -> None:
        if self.bits <= 0:
            raise ValueError("integer width must be positive")


@dataclass(frozen=True)
class Reserved:
    bits: int

    def __post_init__(self) -> None:
        if self.bits <= 0:
            raise ValueError("reserved width must be positive")


@dataclass(frozen=True)
class Field:
    name: str
    type: "Type"


@dataclass(frozen=True)
class Struct:
    name: str
    fields: tuple[Field, ...]

    def __init__(self, name: str, fields: Sequence[Field]):
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "fields", tuple(fields))
        names = [f.name for f in fields]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate field name in {name}")


@dataclass(frozen=True)
class Array:
    element: "Type"
    count: int

    def __post_init__(self) -> None:
        if self.count <= 0:
            raise ValueError("array count must be positive")


@dataclass(frozen=True)
class Union:
    name: str
    members: tuple[Field, ...]

    def __init__(self, name: str, members: Sequence[Field]):
        if not members:
            raise ValueError("union must contain at least one member")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "members", tuple(members))


Type = UInt | Reserved | Struct | Array | Union


@dataclass(frozen=True, order=True)
class Cost:
    """Lexicographic objective: WORD crossings, BYTE crossings, fragments."""

    cross32: int = 0
    cross8: int = 0
    rsvd_fragments: int = 0

    def __add__(self, other: "Cost") -> "Cost":
        return Cost(
            self.cross32 + other.cross32,
            self.cross8 + other.cross8,
            self.rsvd_fragments + other.rsvd_fragments,
        )


@dataclass(frozen=True)
class Placement:
    path: str
    offset: int
    bits: int
    reserved: bool = False


@dataclass(frozen=True)
class Result:
    size_bits: int
    cost: Cost
    placements: tuple[Placement, ...]


@dataclass(frozen=True)
class Comparison:
    """Declared layout and optimized layout for the same type."""

    original: Result
    optimized: Result

    @property
    def saved_cross32(self) -> int:
        return self.original.cost.cross32 - self.optimized.cost.cross32

    @property
    def saved_cross8(self) -> int:
        return self.original.cost.cross8 - self.optimized.cost.cross8


@dataclass(frozen=True)
class _AtomTemplate:
    type: Type


@dataclass(frozen=True)
class _StructTemplate:
    struct: Struct
    order: tuple[int, ...]
    gaps: tuple[int, ...]
    children: tuple["Template", ...]


@dataclass(frozen=True)
class _ArrayTemplate:
    array: Array
    element: "Template"


@dataclass(frozen=True)
class _UnionTemplate:
    union: Union
    members: tuple["Template", ...]


Template = _AtomTemplate | _StructTemplate | _ArrayTemplate | _UnionTemplate


def size_bits(type_: Type) -> int:
    if isinstance(type_, (UInt, Reserved)):
        return type_.bits
    if isinstance(type_, Struct):
        return sum(size_bits(f.type) for f in type_.fields)
    if isinstance(type_, Array):
        return size_bits(type_.element) * type_.count
    if isinstance(type_, Union):
        return max(size_bits(f.type) for f in type_.members)
    raise TypeError(type_)


def _compositions(total: int, slots: int) -> Iterator[tuple[int, ...]]:
    """All ways to distribute total indistinguishable bits among slots."""
    if slots == 1:
        yield (total,)
        return
    for first in range(total + 1):
        for tail in _compositions(total - first, slots - 1):
            yield (first,) + tail


def templates(type_: Type) -> Iterable[Template]:
    """Enumerate legal, fixed layouts for a type.

    A template is independent of its absolute address.  This is important for
    arrays: one element template is selected and reused for every element.
    """
    if isinstance(type_, (UInt, Reserved)):
        yield _AtomTemplate(type_)
        return

    if isinstance(type_, Array):
        for child in templates(type_.element):
            yield _ArrayTemplate(type_, child)
        return

    if isinstance(type_, Union):
        choices = [tuple(templates(f.type)) for f in type_.members]
        for selected in product(*choices):
            yield _UnionTemplate(type_, selected)
        return

    if isinstance(type_, Struct):
        normal = [i for i, f in enumerate(type_.fields) if not isinstance(f.type, Reserved)]
        reserve = sum(
            f.type.bits for f in type_.fields if isinstance(f.type, Reserved)
        )
        # All direct rsvd fields form one conserved, splittable bit pool.
        for order in permutations(normal):
            child_choices = [tuple(templates(type_.fields[i].type)) for i in order]
            for gaps in _compositions(reserve, len(order) + 1):
                for children in product(*child_choices):
                    yield _StructTemplate(type_, order, gaps, children)
        return

    raise TypeError(type_)


def _crossings(offset: int, bits: int, boundary: int) -> int:
    return (offset + bits - 1) // boundary - offset // boundary


def evaluate(template: Template, start: int = 0, path: str = "") -> Result:
    if isinstance(template, _AtomTemplate):
        type_ = template.type
        bits = size_bits(type_)
        reserved = isinstance(type_, Reserved)
        cost = Cost() if reserved else Cost(
            cross32=_crossings(start, bits, 32),
            cross8=_crossings(start, bits, 8),
        )
        return Result(bits, cost, (Placement(path, start, bits, reserved),))

    if isinstance(template, _ArrayTemplate):
        total = Cost()
        placed: list[Placement] = []
        element_size = size_bits(template.array.element)
        for i in range(template.array.count):
            item = evaluate(template.element, start + i * element_size, f"{path}[{i}]")
            total += item.cost
            placed.extend(item.placements)
        return Result(element_size * template.array.count, total, tuple(placed))

    if isinstance(template, _UnionTemplate):
        total = Cost()
        placed: list[Placement] = []
        for field, child in zip(template.union.members, template.members):
            item = evaluate(child, start, _join(path, field.name))
            total += item.cost
            placed.extend(item.placements)
        return Result(size_bits(template.union), total, tuple(placed))

    if isinstance(template, _StructTemplate):
        cursor = start
        total = Cost()
        placed: list[Placement] = []
        fragment_index = 0
        for position, (field_index, child) in enumerate(zip(template.order, template.children)):
            gap = template.gaps[position]
            if gap:
                placed.append(Placement(_join(path, f"rsvd#{fragment_index}"), cursor, gap, True))
                total += Cost(rsvd_fragments=1)
                fragment_index += 1
                cursor += gap
            field = template.struct.fields[field_index]
            item = evaluate(child, cursor, _join(path, field.name))
            total += item.cost
            placed.extend(item.placements)
            cursor += item.size_bits
        gap = template.gaps[-1]
        if gap:
            placed.append(Placement(_join(path, f"rsvd#{fragment_index}"), cursor, gap, True))
            total += Cost(rsvd_fragments=1)
            cursor += gap
        return Result(cursor - start, total, tuple(placed))

    raise TypeError(template)


def _join(prefix: str, name: str) -> str:
    return f"{prefix}.{name}" if prefix else name


def optimize(type_: Type, start: int = 0) -> Result:
    """Return the exact best layout under the lexicographic ``Cost``."""
    best: Result | None = None
    for template in templates(type_):
        result = evaluate(template, start, getattr(type_, "name", ""))
        if best is None or result.cost < best.cost:
            best = result
    if best is None:  # A structure containing only rsvd has no normal fields.
        raise ValueError("type has no legal layout")
    return best


def evaluate_original(type_: Type, start: int = 0, path: str | None = None) -> Result:
    """Evaluate the declared field order without moving or splitting rsvd.

    This provides the baseline used when reporting optimization improvements.
    Nested structs and arrays also retain their declared layouts.
    """
    root_path = getattr(type_, "name", "") if path is None else path

    if isinstance(type_, (UInt, Reserved)):
        bits = type_.bits
        reserved = isinstance(type_, Reserved)
        cost = Cost(rsvd_fragments=1) if reserved else Cost(
            cross32=_crossings(start, bits, 32),
            cross8=_crossings(start, bits, 8),
        )
        return Result(bits, cost, (Placement(root_path, start, bits, reserved),))

    if isinstance(type_, Struct):
        cursor = start
        cost = Cost()
        placements: list[Placement] = []
        for field in type_.fields:
            item = evaluate_original(field.type, cursor, _join(root_path, field.name))
            cursor += item.size_bits
            cost += item.cost
            placements.extend(item.placements)
        return Result(cursor - start, cost, tuple(placements))

    if isinstance(type_, Array):
        element_size = size_bits(type_.element)
        cost = Cost()
        placements: list[Placement] = []
        for index in range(type_.count):
            item = evaluate_original(
                type_.element,
                start + index * element_size,
                f"{root_path}[{index}]",
            )
            cost += item.cost
            placements.extend(item.placements)
        return Result(element_size * type_.count, cost, tuple(placements))

    if isinstance(type_, Union):
        cost = Cost()
        placements: list[Placement] = []
        for member in type_.members:
            item = evaluate_original(member.type, start, _join(root_path, member.name))
            cost += item.cost
            placements.extend(item.placements)
        return Result(size_bits(type_), cost, tuple(placements))

    raise TypeError(type_)


def compare_layouts(type_: Type, start: int = 0) -> Comparison:
    """Return the declared layout and the globally optimized layout."""
    return Comparison(
        original=evaluate_original(type_, start),
        optimized=optimize(type_, start),
    )


def format_result(result: Result) -> str:
    lines = [
        f"size={result.size_bits} bits, cross32={result.cost.cross32}, "
        f"cross8={result.cost.cross8}, rsvd_fragments={result.cost.rsvd_fragments}"
    ]
    for p in sorted(result.placements, key=lambda p: (p.offset, p.path)):
        kind = "rsvd" if p.reserved else "field"
        lines.append(f"{p.offset:4d}..{p.offset + p.bits - 1:<4d} {kind:5s} {p.path} ({p.bits} bits)")
    return "\n".join(lines)


def format_comparison(comparison: Comparison) -> str:
    """Format a concise before/after report followed by both layouts."""
    before = comparison.original
    after = comparison.optimized
    lines = [
        "优化对比",
        "--------",
        f"总位宽       {before.size_bits:>6} -> {after.size_bits:<6} bit",
        f"跨 32-bit    {before.cost.cross32:>6} -> {after.cost.cross32:<6} "
        f"(减少 {comparison.saved_cross32})",
        f"跨 8-bit     {before.cost.cross8:>6} -> {after.cost.cross8:<6} "
        f"(减少 {comparison.saved_cross8})",
        f"rsvd 片段    {before.cost.rsvd_fragments:>6} -> "
        f"{after.cost.rsvd_fragments:<6}",
        "",
        "[优化前：保持声明顺序]",
        format_result(before),
        "",
        "[优化后]",
        format_result(after),
    ]
    return "\n".join(lines)
