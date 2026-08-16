# 结构体位布局优化算法

## 1. 处理流程

工具从 C/C++ 头文件读取类型，经过四层处理：

```text
.h/.hpp
   ↓ cpp_header_parser.py
抽象类型树
   ↓ struct_layout_optimizer.py
合法布局模板与最优模板
   ↓ 评估与对比
优化前后 Result
   ↓ cpp_header_writer.py
优化后的 .hpp
```

解析器、优化器和头文件生成器相互独立：优化算法不读取 C++ 文本，生成器也不重新实现搜索逻辑。

## 2. 抽象类型模型

解析后的类型由以下节点递归组成：

```text
UInt(bits)
Reserved(bits)
Struct(name, fields)
Union(name, members)
Array(element, count)
```

叶子类型是 `UInt` 和 `Reserved`。struct、union 和数组可以任意嵌套。

### C++ 声明映射

```cpp
uint17 value;
```

映射为：

```text
Field("value", UInt(17))
```

标准位域：

```cpp
uint32_t value : 17;
```

同样映射为：

```text
Field("value", UInt(17))
```

字段名称包含 `rsvd` 或 `reserved` 时映射为 `Reserved`：

```cpp
uint7 header_rsvd;
```

映射为：

```text
Field("header_rsvd", Reserved(7))
```

## 3. 布局约束

算法遵守以下约束：

1. 普通字段可以重新排序，但不能拆分。
2. 不允许创建 padding。
3. 同层 struct 中的直属 `rsvd` 可以拆分和移动。
4. 拆分后的 `rsvd` 总位宽必须等于拆分前总位宽。
5. `rsvd` 不能跨 struct 层级移动。
6. 嵌套 struct 的内部字段参与整体候选搜索。
7. 同一个数组的所有元素必须使用完全相同的元素布局模板。
8. union 的所有成员从同一个 bit 偏移开始。
9. 优化前后每个 struct、union 和数组的总位宽不变。

算法计算逻辑 bit 布局，不模拟 C++ 编译器自动 padding、对齐和 ABI。

## 4. 跨界计算

位宽为 `width` 的叶子字段从 `offset` 开始，占用半开区间：

```text
[offset, offset + width)
```

跨越给定边界的次数：

```text
cross(offset, width, boundary) =
    floor((offset + width - 1) / boundary)
    - floor(offset / boundary)
```

### 32-bit WORD

所有非 `rsvd` 叶子字段都计算 WORD 跨界：

```text
cross32 = cross(offset, width, 32)
```

### 8-bit BYTE

只有位宽严格小于 8 bit 的字段计算 BYTE 跨界：

```text
if width < 8:
    cross8 = cross(offset, width, 8)
else:
    cross8 = 0
```

因此 `uint8`、`uint12`、`uint17` 即使覆盖多个 BYTE，也不会增加 `cross8`。

示例：`uint7` 从 bit 5 开始，占用 bit 5～11：

```text
cross32 = 0
cross8  = 1
```

`uint17` 从 bit 24 开始，占用 bit 24～40：

```text
cross32 = 1
cross8  = 0
```

## 5. 代价函数

每种布局的代价为：

```text
Cost(
    cross32,
    cross8,
    rsvd_fragments,
)
```

算法按字典序比较：

1. 最小化 `cross32`；
2. `cross32` 相同时最小化 `cross8`；
3. 两者相同时最小化 `rsvd_fragments`。

例如：

```text
Cost(0, 4, 3) < Cost(1, 0, 1)
Cost(0, 3, 8) < Cost(0, 4, 1)
Cost(0, 3, 2) < Cost(0, 3, 4)
```

WORD 跨界始终比 BYTE 跨界具有更高优先级。

## 6. 原始布局评估

`evaluate_original(type, start)` 保持头文件中的声明顺序：

- struct 字段不重排；
- `rsvd` 不拆分；
- 嵌套类型保持各自声明顺序；
- 数组按声明的元素布局和 stride 展开；
- union 成员在相同起点分别评估。

这个结果构成“优化前”基线。

## 7. struct 候选生成

设一个 struct 有 `n` 个非 `rsvd` 直属字段。算法枚举全部字段排列：

```text
n!
```

例如：

```cpp
struct S {
    uint17 a;
    uint8  b;
    uint15 c;
};
```

候选包括：

```text
a,b,c  a,c,b  b,a,c  b,c,a  c,a,b  c,b,a
```

每个复合字段还会选择一个固定的内部布局模板。

## 8. rsvd 拆分

同层所有直属 `rsvd` 合并成一个总量为 `R` 的资源池。

对于 `n` 个普通字段，共有 `n+1` 个可放置位置：

```text
gap0, field0, gap1, field1, ..., fieldN, gapN
```

算法枚举所有满足以下条件的整数分配：

```text
gap0 + gap1 + ... + gapN = R
gapI >= 0
```

分配方式数量：

```text
C(R + n, n)
```

非零 gap 在输出头文件中写为：

```cpp
uint2 rsvd_0;
uint5 rsvd_1;
```

零宽 gap 不输出。

## 9. 嵌套 struct

嵌套 struct 不能只按总位宽视为一个整数，因为其内部叶子字段也可能跨界。

父级搜索会组合：

- 父 struct 的字段排列；
- 父 struct 的 `rsvd` 分配；
- 子 struct 的字段排列；
- 子 struct 的 `rsvd` 分配；
- 更深层复合类型的候选模板。

确定子 struct 的实际起始偏移后，再递归评估其内部叶子字段。因此算法比较的是父子联合布局，而不是脱离父级位置的子级局部最优布局。

父级 `rsvd` 不能移动进子级，子级 `rsvd` 也不能移动到父级。

## 10. 数组

数组元素大小为 `element_size` 时：

```text
element_start[i] = array_start + i * element_size
```

算法只为数组选择一个元素模板，然后对所有元素重复使用该模板。这保证生成的 C++ 数组具有统一元素布局。

不同元素可能具有不同起始相位：

```text
element_start[i] % 32
```

所以每个元素会在其实际偏移上单独计分。

## 11. union

union 所有成员共享起始偏移：

```text
member_start = union_start
```

union 总位宽：

```text
max(member_size)
```

当前代价模型将所有 union 成员的代价相加，相当于各分支同等重要：

```text
union_cost = sum(member_cost)
```

未来可以扩展为按访问频率加权或最坏分支模型。

## 12. 固定模板与位置评估

搜索被分成两个概念：

### 固定布局模板

`templates(type)` 生成与绝对地址无关的合法模板，包括：

- struct 字段顺序；
- `rsvd` gap 分配；
- 嵌套模板选择；
- 数组的统一元素模板；
- union 各成员模板。

### 位置评估

`evaluate(template, start)` 将模板放到绝对 bit 偏移并计算：

- 每个叶子字段的绝对范围；
- WORD/BYTE 跨界次数；
- `rsvd` 片段数。

精确模式下，`optimize_template(type, start)` 返回全量候选中代价最小的固定模板。自动或启发式模式通过统一的 `solve_layout` 接口选择具体求解器。

## 13. 简化伪代码

```text
function optimize(type, start):
    best_template = NONE
    best_result = NONE

    for template in generate_all_templates(type):
        result = evaluate(template, start)

        if best_result is NONE or result.cost < best_result.cost:
            best_template = template
            best_result = result

    return best_template, best_result
```

struct 模板生成：

```text
for order in permutations(non_reserved_fields):
    for gaps in compositions(total_rsvd, field_count + 1):
        for children in product(each_field_templates):
            yield StructTemplate(order, gaps, children)
```

## 14. 优化前后对比

`compare_layouts(type, start)` 返回：

```text
Comparison {
    original,
    optimized,
    saved_cross32,
    saved_cross8,
}
```

总位宽必须满足：

```text
original.size_bits == optimized.size_bits
```

命令行报告同时列出原始声明顺序和优化顺序的完整字段位置。

## 15. 头文件生成

`render_optimized_header(type, start)` 使用最优固定模板生成 C++ 头文件：

- 根类型保留名称；
- 字段按最优顺序输出；
- 数组 count 保持不变；
- union 成员仍然重叠；
- 嵌套复合类型以内联匿名 struct/union 输出；
- 非零 `rsvd` gap 输出为编号片段；
- 文件注释记录优化前后指标。

以内联匿名类型输出嵌套结构，是为了让每个实例准确保存搜索选中的内部模板。

## 16. 最优性

精确模式完整枚举：

- 普通字段排列；
- `rsvd` 拆分位置；
- 嵌套类型模板组合。

因此精确模式在当前输入模型、约束和字典序代价下返回全局最优解。

启发式模式只保证返回搜索时间预算内找到的最佳结果，不保证全局最优。报告和输出头文件会明确记录搜索模式和最优性保证。

这里的“最优”不包含真实编译器 ABI padding、cache line、访问频率或字段相关性。

## 17. 复杂度

一个包含 `n` 个普通字段、`R` 位直属 `rsvd` 的 struct，仅当前层候选数约为：

```text
n! * C(R + n, n)
```

如果字段包含复合类型，还要乘以各子类型的候选数。复杂度会随字段数量、`rsvd` 位数和嵌套层数快速增长。

精确模式适合：

- 小型和中小型结构体；
- 验证硬件布局规则；
- 作为未来高性能算法的精确结果基准。

大型结构体使用混合启发式求解器，包含：

- 多起点种子顺序；
- Beam Search；
- 基于剩余字段和 `offset % 32` 的状态去重；
- 固定字段顺序下的 `rsvd` 动态规划；
- swap/move 局部搜索；
- 基于类型和 `offset % 32` 的递归模板缓存；
- 数组相位周期计分；
- 搜索时间上限。

候选状态的核心信息可以表示为：

```text
已放置字段集合
已使用 rsvd 位数
当前 offset % 32
累计 Cost
```

因为 BYTE 边界 8 是 WORD 边界 32 的因数，`offset % 32` 已包含后续两种边界判断所需的相位信息。

## 18. 解析与模型限制

当前头文件解析器不是完整 C++ 前端，不运行预处理器，也不使用编译器 ABI。暂不支持：

- 指针、引用和函数字段；
- 模板、继承、虚函数和方法；
- 宏定义后的类型或数组长度；
- `alignas`、`#pragma pack` 和编译器自动 padding；
- 多字段声明语句；
- 匿名输入复合成员；
- 递归按值类型。

如果输入超出该子集，解析器应报错，而不是推测真实 C++ 布局。

## 19. 大规模混合求解器

### 19.1 自动选择

默认配置：

```text
mode = auto
exact_threshold = 10
beam_width = 128
branch_width = 12
local_iterations = 300
time_limit = 10 秒
random_seed = 0
```

自动模式根据当前根 struct 的直属普通字段数量选择：

```text
field_count <= exact_threshold → exact
field_count >  exact_threshold → heuristic
```

用户也可以强制选择模式。对上百字段强制 exact 会产生不可接受的运行时间。

### 19.2 32 相位缓存

跨界代价只依赖绝对偏移模 32：

```text
phase = offset % 32
```

递归类型模板缓存以 `(type, phase)` 为键。同一个类型在相同相位再次出现时直接复用模板，避免重复优化嵌套结构。

### 19.3 无 Placement 成本评估

搜索过程中使用 `_template_cost` 只计算 `Cost`，不创建每个叶子字段的 `Placement` 对象。最终选出模板后才执行一次完整 `evaluate` 生成输出位置。

这对大数组和 Beam Search 状态非常重要，可以显著降低内存分配。

### 19.4 数组周期

元素相位周期为：

```text
period = 32 / gcd(element_size, 32)
```

成本评估只计算一个周期内的元素，再乘以完整周期数量。数组 count 很大时，计算量不会与 count 线性增长。

启发式模式会在周期内各个实际起始相位分别求出元素候选模板，去重后按整个数组的累计 Cost 选择一个统一模板。因此不会只根据第一个数组元素的相位决定所有元素布局。

### 19.5 多起点顺序

大型 struct 首先生成多个确定性种子：

```text
原始声明顺序
按字段位宽降序
按 size % 32 和位宽排序
Beam Search 完整顺序
```

每个种子都进入固定顺序 `rsvd` 优化，选择其中代价最小者作为局部搜索起点。

### 19.6 Beam Search

Beam 状态包含：

```text
累计 Cost
当前绝对 offset
已经排列的字段
剩余字段
```

每层只扩展即时代价最好的 `branch_width` 个字段，并最多保留 `beam_width` 个状态。

状态按以下键去重：

```text
(remaining_fields, offset % 32)
```

同键只保留累计代价最小的状态。

近似状态扩展量为：

```text
O(n * beam_width * branch_width)
```

实际排序候选仍有额外开销，但不会出现 `n!` 个完整排列。

### 19.7 固定顺序 rsvd 动态规划

字段顺序确定后，算法使用 DP 安排 `rsvd` gap。每一步最多尝试在字段前放置 0～31 位保留位：

```text
gap ∈ [0, min(31, remaining_rsvd)]
```

增加整整 32 位不改变后续相位，所以超过 31 位的等价部分可以留到尾部。DP 对相同结束相位只保留更优状态，使每层状态数最多约 32。

### 19.8 局部搜索

最佳种子继续执行确定性随机的：

```text
swap(i, j)
move(i, j)
```

只有新布局的字典序 Cost 更小时才接受。`random_seed` 保证相同配置和输入可以复现结果。

### 19.9 时间预算与闭环输出

Beam Search、DP 和局部搜索共享同一个 deadline。时间耗尽时停止扩展并返回当前最佳完整布局。

一次 `solve_layout` 同时返回：

```text
OptimizationOutcome {
    template
    result
    mode
    optimality_guaranteed
    elapsed_seconds
}
```

CLI 复用同一个 Outcome 生成文本报告和优化后 `.hpp`，不会重复运行搜索。

### 19.10 压力测试

`tests/fixtures/large_layout.hpp` 包含 120 个直属普通字段和一个可拆分保留域。测试验证：

- auto 自动进入 heuristic；
- 优化后总位宽不变；
- Cost 不劣于原始声明顺序；
- 在设定时间预算附近返回；
- 输出头文件标记 `Search mode: heuristic`；
- 输出头文件标记 `Globally optimal: no`。
