"""可直接运行的结构体布局优化示例。"""

import sys

from struct_layout_optimizer import (
    Array,
    Field,
    Reserved,
    Struct,
    UInt,
    Union,
    compare_layouts,
    format_comparison,
)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def show(title, type_, start=0):
    print(f"\n{'=' * 20} {title} {'=' * 20}")
    print(format_comparison(compare_layouts(type_, start)))


# 用例 1：普通整数位宽重排
simple = Struct(
    "Simple",
    [
        Field("a", UInt(17)),
        Field("b", UInt(16)),
        Field("c", UInt(7)),
    ],
)

# 用例 2：rsvd 可以拆分，但总位数必须保持为 7
with_reserved = Struct(
    "WithReserved",
    [
        Field("a", UInt(17)),
        Field("b", UInt(12)),
        Field("spare", Reserved(7)),
    ],
)

# 用例 3：子结构体与父结构体联合优化
child = Struct(
    "Child",
    [
        Field("wide", UInt(17)),
        Field("small", UInt(8)),
        Field("child_rsvd", Reserved(3)),
    ],
)
parent = Struct(
    "Parent",
    [
        Field("head", UInt(7)),
        Field("child", child),
        Field("tail", UInt(5)),
        Field("parent_rsvd", Reserved(8)),
    ],
)

# 用例 4：数组中的每个元素使用相同的 Child 布局
child_array = Array(child, 3)

# 用例 5：union 成员从同一个起始位开始
sample_union = Union(
    "SampleUnion",
    [
        Field("short_value", UInt(12)),
        Field("long_value", UInt(17)),
        Field("structured_value", child),
    ],
)


if __name__ == "__main__":
    show("普通字段重排", simple)
    show("rsvd 拆分", with_reserved)
    show("嵌套结构体", parent)
    show("结构体数组", child_array)
    show("union（从 bit 24 开始）", sample_union, start=24)
