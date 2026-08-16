"""较复杂的多层嵌套结构体优化用例。"""

import sys
from time import perf_counter

from struct_layout_optimizer import (
    Array,
    Field,
    Reserved,
    Struct,
    UInt,
    Union,
    compare_layouts,
    format_comparison,
    size_bits,
)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# 二级嵌套：每个坐标包含非标准位宽整数和可拆分保留位。
coordinate = Struct(
    "Coordinate",
    [
        Field("x", UInt(17)),
        Field("y", UInt(15)),
    ],
)


# union 的所有分支覆盖同一片存储区。结构体分支自身仍参与优化。
sensor_value = Union(
    "SensorValue",
    [
        Field("raw", UInt(31)),
        Field("signed_magnitude", UInt(29)),
        Field("coordinate", coordinate),
    ],
)


# 一级记录：包含 union、普通位域、定长采样数组和直属 rsvd。
record = Struct(
    "Record",
    [
        Field("sensor", sensor_value),
        Field("channel", UInt(7)),
        Field("samples", Array(UInt(12), 4)),
        Field("record_rsvd", Reserved(1)),
    ],
)


# 包头也是嵌套结构体，并拥有自己的 rsvd 资源池。
packet_header = Struct(
    "PacketHeader",
    [
        Field("packet_type", UInt(5)),
        Field("sequence", UInt(19)),
    ],
)


# 顶层结构体包含 16 个 Record。每个数组元素必须复用同一种 Record
# 布局，不能根据各元素的绝对偏移分别改变字段顺序。
telemetry_packet = Struct(
    "TelemetryPacket",
    [
        Field("header", packet_header),
        Field("records", Array(record, 16)),
        Field("packet_rsvd", Reserved(1)),
    ],
)


if __name__ == "__main__":
    print("复杂结构体组成：")
    print("  TelemetryPacket")
    print("    PacketHeader")
    print("    Record records[16]")
    print("      SensorValue union")
    print("        Coordinate")
    print("      uint12 samples[4]")
    print()
    print(f"顶层结构体总位宽：{size_bits(telemetry_packet)} bit")

    started = perf_counter()
    comparison = compare_layouts(telemetry_packet)
    elapsed = perf_counter() - started

    print(f"优化耗时：{elapsed:.3f} 秒")
    print(format_comparison(comparison))
