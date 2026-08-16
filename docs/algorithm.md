# 结构体位布局优化算法原理

## 1. 问题定义

输入类型可以由以下元素递归组成：

- 任意位宽无符号整数，例如 `uint1`、`uint12`、`uint17`；
- 可拆分的 `rsvd` 保留域；
- 嵌套结构体；
- 数组；
- union。

硬件只能按照 8-bit BYTE 或 32-bit WORD 读取数据。优化目标是在不增加 padding、不改变总位宽的前提下，重新排列字段并拆分已有 `rsvd`，尽量减少普通字段跨越 BYTE 和 WORD 边界的次数。

算法遵守以下约束：

1. 普通字段可以重新排序，但不能拆分。
2. 不允许生成新的 padding。
3. 同一层结构体中的直属 `rsvd` 可以拆分和移动，但位数总和保持不变。
4. `rsvd` 不允许跨结构体层级移动。
5. 嵌套结构体必须参与父结构体的联合优化。
6. 数组的所有元素必须使用相同的元素布局。
7. union 的所有成员从同一偏移开始。

## 2. 跨界代价

一个位宽为 `width` 的字段占用半开区间：

```text
[offset, offset + width)
```

它跨越某种边界的次数定义为：

```text
cross(offset, width, boundary) =
    floor((offset + width - 1) / boundary)
    - floor(offset / boundary)
```

BYTE 和 WORD 跨界次数分别为：

```text
cross8  = cross(offset, width, 8)
cross32 = cross(offset, width, 32)
```

例如 `uint17` 从 bit 0 开始，占用 bit 0～16：

```text
cross32 = 0
cross8  = 2
```

如果它从 bit 24 开始，占用 bit 24～40：

```text
cross32 = 1
cross8  = 2
```

## 3. 优化目标

每种布局的总代价表示为：

```text
Cost {
    cross32,
    cross8,
    rsvd_fragments
}
```

算法按照字典序比较代价：

1. 优先最小化跨 32-bit 边界次数；
2. 在 `cross32` 相同时最小化跨 8-bit 边界次数；
3. 前两项相同时最小化 `rsvd` 片段数。

例如：

```text
Cost(0, 5, 3) 优于 Cost(1, 0, 1)
Cost(0, 4, 5) 优于 Cost(0, 5, 1)
Cost(0, 4, 2) 优于 Cost(0, 4, 3)
```

这保证算法不会为了减少几个 BYTE 跨界而引入更昂贵的 WORD 跨界。

## 4. 普通结构体字段排列

对于：

```text
a: uint17
b: uint12
c: uint6
```

算法枚举全部字段排列：

```text
a, b, c
a, c, b
b, a, c
b, c, a
c, a, b
c, b, a
```

对每一种排列，从结构体起始偏移开始依次确定字段位置，并计算所有叶子字段的跨界代价。

`n` 个普通字段共有：

```text
n!
```

种排列。

## 5. rsvd 拆分

同一层结构体中的所有直属 `rsvd` 首先合并为一个资源池。例如：

```text
rsvd0: uint3
rsvd1: uint4
```

合并后：

```text
R = 7 bit
```

如果当前层有三个普通字段，就存在四个可放置 `rsvd` 的位置：

```text
gap0, field0, gap1, field1, gap2, field2, gap3
```

算法枚举所有满足以下条件的分配：

```text
gap0 + gap1 + gap2 + gap3 = R
gapN >= 0
```

例如：

```text
(0, 0, 0, 7)
(0, 0, 1, 6)
(0, 1, 2, 4)
(3, 0, 4, 0)
(1, 2, 3, 1)
```

对于 `R` 位 `rsvd` 和 `n` 个普通字段，分配方式数量为：

```text
C(R + n, n)
```

由于所有 gap 的总和严格等于原有 `rsvd` 位宽，算法不会产生新位，也不会改变结构体总大小。

## 6. 嵌套结构体联合优化

嵌套结构体不能只按总位宽视为一个普通字段。例如：

```text
Parent {
    uint7 head;
    Child child;
    uint8 rsvd;
}

Child {
    uint17 wide;
    uint8 small;
}
```

算法递归生成 `Child` 的所有合法布局：

```text
wide, small
small, wide
```

搜索父结构体时，同时枚举：

- 父结构体的字段顺序；
- 父结构体的 `rsvd` 分配；
- 子结构体的字段顺序；
- 子结构体自身的 `rsvd` 分配。

确定 `child` 在父结构体中的实际起始偏移后，再递归计算其内部所有叶子字段的跨界代价。因此优化对象是：

```text
父结构体布局 + 子结构体布局
```

的组合，而不是脱离父结构体位置独立选择一个子结构体局部最优解。

### rsvd 层级约束

子结构体内部的 `rsvd` 只能在子结构体内部移动。父结构体的 `rsvd` 也不能进入子结构体。每一层都有独立且守恒的 `rsvd` 资源池。

## 7. 数组

对于：

```text
Child children[3]
```

算法先为 `Child` 选择一个固定布局模板，然后对三个元素重复使用同一模板：

```text
element_start[i] =
    array_start + i * sizeof(Child)
```

相同数组中的元素字段顺序和 `rsvd` 拆分方式完全相同，但由于元素起始偏移不同，其跨界代价可能不同。

例如元素大小为 17 位时：

```text
children[0] offset % 32 = 0
children[1] offset % 32 = 17
children[2] offset % 32 = 2
```

算法分别计算每个元素在实际位置上的代价，然后求和。

## 8. union

union 所有成员从同一位偏移开始：

```text
member_start = union_start
```

union 的总位宽为：

```text
max(sizeof(member))
```

当前实现分别递归优化所有成员，并将所有成员的跨界代价相加。这相当于假设所有 union 分支同等重要。

如果可以获得实际访问频率，可扩展为：

```text
union_cost =
    sum(member_access_frequency * member_cost)
```

也可以采用最坏情况模型：

```text
union_cost = max(member_cost)
```

## 9. 算法执行过程

实现将搜索分为两个阶段。

### 9.1 生成固定布局模板

`templates(type)` 递归生成所有合法布局，包括：

```text
字段排列
rsvd 分配
嵌套结构体布局
数组元素布局
union 成员布局
```

模板只描述相对布局，不依赖结构体最终放置的绝对位置。

### 9.2 评估模板

`evaluate(template, start)` 把模板放在指定绝对位偏移，然后递归计算：

```text
每个叶子字段的绝对偏移
跨 32-bit 边界次数
跨 8-bit 边界次数
rsvd 片段数
```

`optimize(type, start)` 评估全部模板，并返回字典序代价最小的布局。

## 10. 简化伪代码

```text
function optimize(type, start):
    best = NONE

    for template in generate_all_legal_templates(type):
        result = evaluate(template, start)

        if best is NONE or result.cost < best.cost:
            best = result

    return best
```

递归评估结构体：

```text
function evaluate_struct(template, start):
    cursor = start
    total_cost = 0

    for each field in template.order:
        reserve_bits = rsvd_gap_before(field)
        cursor += reserve_bits

        field_result = evaluate(field.template, cursor)
        total_cost += field_result.cost
        cursor += field_result.size

    cursor += trailing_rsvd

    return Result(
        size = cursor - start,
        cost = total_cost,
        placements = all_recursive_placements
    )
```

## 11. 最优性

当前规则下，所有合法决策包括：

- 普通字段顺序；
- 原有 `rsvd` 的拆分位置；
- 每个嵌套类型使用的合法布局。

算法完整枚举这些选择，并计算每种选择的确定代价，因此返回的是当前代价模型下的全局最优解，而不是近似解。

## 12. 复杂度

对于一个包含 `n` 个普通字段、`R` 位直属 `rsvd` 的结构体，仅当前层的候选数约为：

```text
n! * C(R + n, n)
```

存在嵌套结构体时，还需要乘以各子结构体的候选数量：

```text
当前层候选数
* 子结构体1候选数
* 子结构体2候选数
* ...
```

因此当前精确穷举算法适合：

- 验证优化规则；
- 小型和中小型结构体；
- 作为后续高性能算法的正确性基准。

字段较多或嵌套较深时，可以进一步实现：

```text
子集动态规划
等价状态合并
分支限界
大结构体启发式搜索
```

动态规划可以使用以下核心状态：

```text
已经放置的字段集合
已经使用的 rsvd 位数
当前 offset % 32
累计代价
```

因为 8 是 32 的因数，`offset % 32` 已经包含判断后续 BYTE 和 WORD 跨界所需的相位信息。
