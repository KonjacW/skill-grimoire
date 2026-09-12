# 并行重叠分级与写入权边界（R1/R2/R3）

> 来源：ThreadGate 技能 `dispatching-parallel-agents` v0.1.0，合并自
> `~/.codex/plugins/cache/threadgate-local/threadgate-workflow/0.1.0/skills/dispatching-parallel-agents/`（SKILL.md + references/overlap-integration.md + references/dispatch-contract.md）。
> 合并日期 2026-09-11。本文件只处理**已决定并行之后**的分级与写入，不重新判断并行是否值得。

## 重叠等级

| 等级 | 适用情况 | 允许的产物 | 最终写入 |
|---|---|---|---|
| R1 | 独立文件、无公共符号 | 隔离副本中的候选实现或证据 | 主 Agent 检查后集成写回 |
| R2 | 同一文件的可定位区域 | 带共同基线的 located-patch | 主 Agent 按声明顺序应用 |
| R3 | 共享契约、同一决策路径或共享不变量 | 只读设计（read-only-design）或隔离候选 patch | 主 Agent 单点写回 |

## 硬约束（任何等级都适用）

主 Agent 保留：需求解释、共享契约、最终计划、最终写入、集成与验证。
子 Agent 默认只读——不写入共享最终工作区、不提交、不推送、不执行不可逆外部操作。

R3 必须先由主 Agent 声明共享不变量；没有共同基线和隔离位置时，不得产生写入候选。
禁止在共享最终工作区并发写入，禁止以「最后写入者」作为合并策略。

## R2/R3 集成协议

| 情形 | 子 Agent 产物 | 写入规则 |
|---|---|---|
| R2：同文件不同区域 | `located-patch` | 主 Agent 按声明顺序应用，运行 `git diff --check` 与相关验证 |
| R3：同一区域、同一决策路径或共享契约 | `read-only-design` 或 `isolated-patch` | 主 Agent 先定不变量；仅隔离副本可组合 patch；最终工作区由预先锁定的单一 owner 单点写入 |

集成记录必须包含：共同基线、patch-id、应用顺序、共享不变量、语义审查结论、验证结果、写回清单。
冲突、验证失败或不变量不清时：丢弃隔离副本，保留 patch，从共同基线重来（或退回串行）。

## 任务卡

- **R1 极轻任务卡**：范围 / 目标 / 禁止事项 / 验收 / 回传。
- **R2、R3 或高风险**另加：共同基线（commit、快照或版本，含脏工作树状态与相关文件 hash）、patch-id、模式、最终写入者（未填写则为主 Agent）、共享不变量、隔离路径、停止条件、验证命令。

每个子 Agent 必须返回：影响文件、实际产物、验证结果、阻塞项、未验证项。
超时或无回包时，主 Agent **先**检查实际 diff、产物与哈希：发现副作用则接管，未发现副作用才可从共同基线重派。

## 收束

每波结束由主 Agent 检查实际 diff、验证结果、共享不变量和未决风险，再按顺序集成。
并行局部审查**不**替代最终集成 diff 的 Review（push 门禁见 `review-gate`）。
