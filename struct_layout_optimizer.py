"""Hybrid exact/heuristic bit-field layout optimizer.

The optimizer never invents padding.  Reserved fields (``Reserved``) are the
only bits that may be split and placed between fields.  Layouts are recursive:
an embedded structure is optimized together with its parent, and every element
of an array uses the same element layout.

Small structures use exhaustive search. Large structures use phase-cached beam
search, fixed-order reserved-bit dynamic programming, and local improvement.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations, product
from math import gcd
import random
from time import monotonic
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
    mode: str = "exact"
    optimality_guaranteed: bool = True
    elapsed_seconds: float = 0.0

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


@dataclass(frozen=True)
class OptimizationOutcome:
    template: Template
    result: Result
    mode: str
    optimality_guaranteed: bool
    elapsed_seconds: float


@dataclass(frozen=True)
class OptimizationConfig:
    mode: str = "auto"
    exact_threshold: int = 10
    beam_width: int = 128
    branch_width: int = 12
    local_iterations: int = 300
    time_limit: float = 10.0
    random_seed: int = 0

    def __post_init__(self) -> None:
        if self.mode not in ("auto", "exact", "heuristic"):
            raise ValueError("mode must be auto, exact, or heuristic")
        if min(self.exact_threshold, self.beam_width, self.branch_width) <= 0:
            raise ValueError("search limits must be positive")
        if self.local_iterations < 0 or self.time_limit <= 0:
            raise ValueError("local_iterations must be non-negative and time_limit positive")


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


def _field_cost(offset: int, bits: int) -> Cost:
    """Return the hardware boundary cost for one non-reserved leaf field.

    BYTE crossing matters only for sub-BYTE fields.  A field whose width is
    one BYTE or wider is fetched as a wider value and therefore contributes
    only to the 32-bit WORD crossing objective.
    """
    return Cost(
        cross32=_crossings(offset, bits, 32),
        cross8=_crossings(offset, bits, 8) if bits < 8 else 0,
    )


def evaluate(template: Template, start: int = 0, path: str = "") -> Result:
    if isinstance(template, _AtomTemplate):
        type_ = template.type
        bits = size_bits(type_)
        reserved = isinstance(type_, Reserved)
        cost = Cost() if reserved else _field_cost(start, bits)
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


def _scale_cost(cost: Cost, count: int) -> Cost:
    return Cost(cost.cross32 * count, cost.cross8 * count, cost.rsvd_fragments * count)


def _template_cost(template: Template, start: int = 0) -> Cost:
    """Evaluate cost without materializing leaf placements."""
    if isinstance(template, _AtomTemplate):
        if isinstance(template.type, Reserved):
            return Cost()
        return _field_cost(start, template.type.bits)
    if isinstance(template, _StructTemplate):
        cursor = start
        total = Cost()
        for position, (field_index, child) in enumerate(zip(template.order, template.children)):
            gap = template.gaps[position]
            if gap:
                cursor += gap
                total += Cost(rsvd_fragments=1)
            total += _template_cost(child, cursor)
            cursor += size_bits(template.struct.fields[field_index].type)
        if template.gaps[-1]:
            total += Cost(rsvd_fragments=1)
        return total
    if isinstance(template, _UnionTemplate):
        total = Cost()
        for child in template.members:
            total += _template_cost(child, start)
        return total
    if isinstance(template, _ArrayTemplate):
        count = template.array.count
        element_size = size_bits(template.array.element)
        period = 32 // gcd(element_size, 32)
        cycles, remainder = divmod(count, period)
        total = Cost()
        for index in range(period):
            occurrences = cycles + (1 if index < remainder else 0)
            if occurrences:
                item = _template_cost(template.element, start + index * element_size)
                total += _scale_cost(item, occurrences)
        return total
    raise TypeError(template)


def _normal_indices(struct: Struct) -> tuple[int, ...]:
    return tuple(i for i, field in enumerate(struct.fields) if not isinstance(field.type, Reserved))


def _reserve_bits(struct: Struct) -> int:
    return sum(field.type.bits for field in struct.fields if isinstance(field.type, Reserved))


def _declared_template(type_: Type) -> Template:
    """Build a legal template that preserves declaration order for fallback."""
    if isinstance(type_, (UInt, Reserved)):
        return _AtomTemplate(type_)
    if isinstance(type_, Array):
        return _ArrayTemplate(type_, _declared_template(type_.element))
    if isinstance(type_, Union):
        return _UnionTemplate(type_, tuple(_declared_template(f.type) for f in type_.members))
    if isinstance(type_, Struct):
        order: list[int] = []
        gaps: list[int] = []
        children: list[Template] = []
        pending = 0
        for index, field in enumerate(type_.fields):
            if isinstance(field.type, Reserved):
                pending += field.type.bits
            else:
                gaps.append(pending)
                pending = 0
                order.append(index)
                children.append(_declared_template(field.type))
        gaps.append(pending)
        return _StructTemplate(type_, tuple(order), tuple(gaps), tuple(children))
    raise TypeError(type_)


def _uses_heuristic(type_: Type, config: OptimizationConfig) -> bool:
    if config.mode == "heuristic":
        return True
    if config.mode == "exact":
        return False
    return isinstance(type_, Struct) and len(_normal_indices(type_)) > config.exact_threshold


def optimize(type_: Type, start: int = 0, config: OptimizationConfig | None = None) -> Result:
    """Return the best layout found by the configured solver."""
    return solve_layout(type_, start, config).result


def _optimize_exact_template(type_: Type, start: int) -> Template:
    best_template: Template | None = None
    best_cost: Cost | None = None
    for template in templates(type_):
        cost = _template_cost(template, start)
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_template = template
    if best_template is None:
        raise ValueError("type has no legal layout")
    return best_template


def optimize_template(
    type_: Type,
    start: int = 0,
    config: OptimizationConfig | None = None,
) -> Template:
    """Return the fixed layout selected by exact or scalable search."""
    return solve_layout(type_, start, config).template


def _select_template(
    type_: Type,
    start: int,
    config: OptimizationConfig,
) -> Template:
    config = config or OptimizationConfig()
    if not _uses_heuristic(type_, config):
        return _optimize_exact_template(type_, start)
    deadline = monotonic() + config.time_limit
    cache: dict[tuple[Type, int], Template] = {}
    return _optimize_cached(type_, start, config, deadline, cache)


def _optimize_cached(
    type_: Type,
    start: int,
    config: OptimizationConfig,
    deadline: float,
    cache: dict[tuple[Type, int], Template],
) -> Template:
    key = (type_, start % 32)
    if key in cache:
        return cache[key]
    if isinstance(type_, (UInt, Reserved)):
        result: Template = _AtomTemplate(type_)
    elif isinstance(type_, Array):
        element_size = size_bits(type_.element)
        period = min(type_.count, 32 // gcd(element_size, 32))
        candidates = {
            _optimize_cached(
                type_.element,
                start + index * element_size,
                config,
                deadline,
                cache,
            )
            for index in range(period)
        }
        result = min(
            (_ArrayTemplate(type_, child) for child in candidates),
            key=lambda candidate: _template_cost(candidate, start),
        )
    elif isinstance(type_, Union):
        members = tuple(
            _optimize_cached(field.type, start, config, deadline, cache)
            for field in type_.members
        )
        result = _UnionTemplate(type_, members)
    elif isinstance(type_, Struct):
        if config.mode != "heuristic" and len(_normal_indices(type_)) <= config.exact_threshold:
            result = _optimize_exact_template(type_, start)
        else:
            result = _optimize_large_struct(type_, start, config, deadline, cache)
    else:
        raise TypeError(type_)
    cache[key] = result
    return result


def _fixed_order_template(
    struct: Struct,
    order: tuple[int, ...],
    start: int,
    config: OptimizationConfig,
    deadline: float,
    cache: dict[tuple[Type, int], Template],
) -> _StructTemplate:
    reserve = _reserve_bits(struct)
    # phase -> (cost, used_rsvd, gaps, children)
    states: dict[int, tuple[Cost, int, tuple[int, ...], tuple[Template, ...]]] = {
        start % 32: (Cost(), 0, (), ())
    }
    field_prefix = 0
    for field_index in order:
        next_states: dict[int, tuple[Cost, int, tuple[int, ...], tuple[Template, ...]]] = {}
        field = struct.fields[field_index]
        for _, (cost, used, gaps, children) in states.items():
            remaining = reserve - used
            for gap in range(min(31, remaining) + 1):
                cursor = start + field_prefix + used + gap
                child = _optimize_cached(field.type, cursor, config, deadline, cache)
                new_cost = cost + _template_cost(child, cursor)
                if gap:
                    new_cost += Cost(rsvd_fragments=1)
                new_used = used + gap
                phase = (cursor + size_bits(field.type)) % 32
                candidate = (new_cost, new_used, gaps + (gap,), children + (child,))
                current = next_states.get(phase)
                if current is None or (candidate[0], candidate[1]) < (current[0], current[1]):
                    next_states[phase] = candidate
        states = next_states
        field_prefix += size_bits(field.type)
        if monotonic() >= deadline:
            break
    if len(next(iter(states.values()))[2]) != len(order):
        # Deadline during DP: finish deterministically without additional gaps.
        cost, used, gaps, children = min(states.values(), key=lambda item: item[0])
        for field_index in order[len(gaps):]:
            field = struct.fields[field_index]
            cursor = start + sum(size_bits(struct.fields[i].type) for i in order[:len(gaps)]) + used
            child = _optimize_cached(field.type, cursor, config, deadline, cache)
            cost += _template_cost(child, cursor)
            gaps += (0,)
            children += (child,)
    best = min(
        states.values(),
        key=lambda item: item[0] + (Cost(rsvd_fragments=1) if reserve > item[1] else Cost()),
    ) if all(len(item[2]) == len(order) for item in states.values()) else (cost, used, gaps, children)
    _, used, gaps, children = best
    return _StructTemplate(struct, order, gaps + (reserve - used,), children)


def _quick_append_cost(
    field: Field,
    cursor: int,
    config: OptimizationConfig,
    deadline: float,
    cache: dict[tuple[Type, int], Template],
) -> tuple[Cost, Template]:
    child = _optimize_cached(field.type, cursor, config, deadline, cache)
    return _template_cost(child, cursor), child


def _beam_orders(
    struct: Struct,
    start: int,
    config: OptimizationConfig,
    deadline: float,
    cache: dict[tuple[Type, int], Template],
) -> list[tuple[int, ...]]:
    indices = _normal_indices(struct)
    # (cost, cursor, order, remaining)
    beam: list[tuple[Cost, int, tuple[int, ...], tuple[int, ...]]] = [
        (Cost(), start, (), indices)
    ]
    for _ in range(len(indices)):
        expanded: list[tuple[Cost, int, tuple[int, ...], tuple[int, ...]]] = []
        for cost, cursor, order, remaining in beam:
            ranked = []
            for field_index in remaining:
                field_cost, _ = _quick_append_cost(
                    struct.fields[field_index], cursor, config, deadline, cache
                )
                next_phase = (cursor + size_bits(struct.fields[field_index].type)) % 32
                ranked.append((field_cost, next_phase, field_index))
            for field_cost, _, field_index in sorted(ranked)[: config.branch_width]:
                field_size = size_bits(struct.fields[field_index].type)
                new_remaining = tuple(i for i in remaining if i != field_index)
                expanded.append((cost + field_cost, cursor + field_size, order + (field_index,), new_remaining))
        dedup: dict[tuple[tuple[int, ...], int], tuple[Cost, int, tuple[int, ...], tuple[int, ...]]] = {}
        for state in sorted(expanded, key=lambda item: item[0]):
            key = (state[3], state[1] % 32)
            if key not in dedup:
                dedup[key] = state
            if len(dedup) >= config.beam_width:
                break
        beam = list(dedup.values())
        if monotonic() >= deadline:
            break
    return [state[2] for state in beam if not state[3]]


def _optimize_large_struct(
    struct: Struct,
    start: int,
    config: OptimizationConfig,
    deadline: float,
    cache: dict[tuple[Type, int], Template],
) -> _StructTemplate:
    indices = _normal_indices(struct)
    seeds: list[tuple[int, ...]] = [
        indices,
        tuple(sorted(indices, key=lambda i: size_bits(struct.fields[i].type), reverse=True)),
        tuple(sorted(indices, key=lambda i: (size_bits(struct.fields[i].type) % 32, size_bits(struct.fields[i].type)))),
    ]
    seeds.extend(_beam_orders(struct, start, config, deadline, cache))
    unique_seeds = list(dict.fromkeys(seeds))
    best_template = _fixed_order_template(struct, unique_seeds[0], start, config, deadline, cache)
    best_cost = _template_cost(best_template, start)
    for order in unique_seeds[1:]:
        if monotonic() >= deadline:
            break
        candidate = _fixed_order_template(struct, order, start, config, deadline, cache)
        cost = _template_cost(candidate, start)
        if cost < best_cost:
            best_template, best_cost = candidate, cost

    rng = random.Random(config.random_seed)
    current_order = list(best_template.order)
    for _ in range(config.local_iterations):
        if len(current_order) < 2 or monotonic() >= deadline:
            break
        trial = current_order.copy()
        if rng.random() < 0.5:
            left, right = rng.sample(range(len(trial)), 2)
            trial[left], trial[right] = trial[right], trial[left]
        else:
            source, target = rng.sample(range(len(trial)), 2)
            trial.insert(target, trial.pop(source))
        candidate = _fixed_order_template(struct, tuple(trial), start, config, deadline, cache)
        cost = _template_cost(candidate, start)
        if cost < best_cost:
            best_template, best_cost = candidate, cost
            current_order = trial
    return best_template


def solve_layout(
    type_: Type,
    start: int = 0,
    config: OptimizationConfig | None = None,
) -> OptimizationOutcome:
    """Run the solver once and return reusable template, result, and metadata."""
    config = config or OptimizationConfig()
    heuristic = _uses_heuristic(type_, config)
    started = monotonic()
    template = _select_template(type_, start, config)
    if heuristic:
        declared = _declared_template(type_)
        if _template_cost(template, start) > _template_cost(declared, start):
            template = declared
    result = evaluate(template, start, getattr(type_, "name", ""))
    return OptimizationOutcome(
        template=template,
        result=result,
        mode="heuristic" if heuristic else "exact",
        optimality_guaranteed=not heuristic,
        elapsed_seconds=monotonic() - started,
    )


def evaluate_original(type_: Type, start: int = 0, path: str | None = None) -> Result:
    """Evaluate the declared field order without moving or splitting rsvd.

    This provides the baseline used when reporting optimization improvements.
    Nested structs and arrays also retain their declared layouts.
    """
    root_path = getattr(type_, "name", "") if path is None else path

    if isinstance(type_, (UInt, Reserved)):
        bits = type_.bits
        reserved = isinstance(type_, Reserved)
        cost = Cost(rsvd_fragments=1) if reserved else _field_cost(start, bits)
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


def compare_layouts(
    type_: Type,
    start: int = 0,
    config: OptimizationConfig | None = None,
) -> Comparison:
    """Return declared and optimized layouts plus search metadata."""
    config = config or OptimizationConfig()
    outcome = solve_layout(type_, start, config)
    return Comparison(
        original=evaluate_original(type_, start),
        optimized=outcome.result,
        mode=outcome.mode,
        optimality_guaranteed=outcome.optimality_guaranteed,
        elapsed_seconds=outcome.elapsed_seconds,
    )


def comparison_from_outcome(type_: Type, outcome: OptimizationOutcome, start: int = 0) -> Comparison:
    """Build a before/after comparison without running the optimizer again."""
    return Comparison(
        original=evaluate_original(type_, start),
        optimized=outcome.result,
        mode=outcome.mode,
        optimality_guaranteed=outcome.optimality_guaranteed,
        elapsed_seconds=outcome.elapsed_seconds,
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
        f"搜索模式       {comparison.mode}",
        f"保证全局最优   {'是' if comparison.optimality_guaranteed else '否'}",
        f"搜索耗时       {comparison.elapsed_seconds:.3f} 秒",
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
