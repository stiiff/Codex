# Struct Layout Optimizer

面向只能按 8-bit BYTE 或 32-bit WORD 读取数据的硬件，优化任意位宽字段的结构体布局。

支持普通整数位域、可拆分 `rsvd`、嵌套结构体、数组和 union。优化不会创建 padding，也不会改变结构体总位宽。所有普通字段计算 32-bit WORD 跨界；只有位宽小于 8 bit 的字段计算 BYTE 跨界。

## 快速开始

要求 Python 3.10 或更高版本，无第三方运行时依赖。

```powershell
git clone <repository-url>
cd struct-layout-optimizer
python optimize_header.py tests/fixtures/layout_cases.hpp --root TelemetryPacket
```

项目的正式输入是 C/C++ 头文件。`--root` 指定需要优化的顶层 struct 或 union；省略时使用头文件中最后一个定义：

```powershell
python optimize_header.py path\to\types.hpp --root Packet
```

首版头文件解析器支持：

- `uint1`、`uint12`、`uint17` 等任意位宽类型；
- `uint32_t field : 17` 形式的 C/C++ 位域；
- 命名 struct/union 嵌套；
- 定长数组和结构体数组；
- 名称包含 `rsvd` 或 `reserved` 的可拆分保留域。

## Python API

```python
from struct_layout_optimizer import (
    Field, Reserved, Struct, UInt,
    compare_layouts, format_comparison,
)

packet = Struct(
    "Packet",
    [
        Field("mode", UInt(5)),
        Field("counter", UInt(17)),
        Field("value", UInt(12)),
        Field("rsvd", Reserved(6)),
    ],
)

comparison = compare_layouts(packet)
print(format_comparison(comparison))
```

核心接口：

- `optimize(type_, start=0)`：只计算优化结果；
- `evaluate_original(type_, start=0)`：计算声明顺序下的原始布局；
- `compare_layouts(type_, start=0)`：同时返回优化前后结果；
- `format_comparison(comparison)`：打印完整差异。

报告会同时显示优化前后的总位宽、跨 32-bit 次数、跨 8-bit 次数、`rsvd` 片段数、改善量和完整字段位置。

## 类型表达

```python
UInt(17)                         # 17 位整数
Reserved(5)                      # 可拆分的 5 位 rsvd
Array(UInt(12), 16)              # uint12[16]
Struct("Child", [...])           # 嵌套结构体
Union("Value", [...])            # union
```

每层结构体的 `rsvd` 独立管理，不能跨层移动。数组中的同类型元素始终使用相同布局。

## 示例与测试

```powershell
# 基础用例及优化前后对比
python -m examples.basic_usage

# 1,433-bit、多层嵌套、结构体数组和 union
python -m examples.complex_usage

# 全量测试
python -m unittest discover -v
```

## 项目结构

```text
struct-layout-optimizer/
├── cpp_header_parser.py        # C/C++ 头文件输入解析
├── optimize_header.py          # 命令行入口
├── struct_layout_optimizer.py   # 数据模型、搜索算法和报告接口
├── examples/                    # 可运行示例
├── tests/
│   ├── fixtures/layout_cases.hpp # C++ 头文件输入用例
│   ├── test_cpp_header_parser.py # 头文件解析集成测试
│   └── test_optimizer.py         # 优化算法断言
├── docs/algorithm.md            # 算法与复杂度说明
├── pyproject.toml               # Python 项目元数据
├── LICENSE
└── README.md
```

## 当前限制

当前搜索器完整枚举合法布局，返回当前代价模型下的精确最优解，但复杂度随直属字段数量、`rsvd` 位数和嵌套候选数快速增长。它适合作为中小规模输入的优化器，以及后续动态规划或启发式实现的正确性基准。

详细原理参见 [docs/algorithm.md](docs/algorithm.md)。
