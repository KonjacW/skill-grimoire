---
name: using-superpowers
description: "Use when workflow skills or shared contracts are unclear."
license: MIT
metadata:
  agent:
    tags: [superpowers, using-superpowers]
    related_skills: []
---

# 技能路由

先按任务风险选择最轻、仍能证明结果的路径。用户显式点名的技能、`AGENTS.md` 硬约束和平台上级指令始终优先。

## 三档入口

| 档位 | 可观察条件 | 动作 |
|---|---|---|
| 直通 | 单一范围、低上下文、无共享契约；包括只读问答、文档/格式和明确小改动 | 主 Agent 直接处理；不生成计划、不调用并行技能 |
| 轻量执行 | 普通多步任务，风险可定位且不需要跨会话 | 在内部维护轻量执行图：工作包、依赖、写入者、验证；不生成正式计划 |
| 正式计划 | 高风险、共享契约、迁移/权限/部署、跨会话，或需求缺口会改变方案 | 需要设计时先用 `plan` 收敛方案（未验证的假设先走 `spike`），确认后使用 `writing-plans` |

不要因为“可能有技能”而中断直通任务；也不要把直通误用于未确定接口或高风险行为。

## 一次并行判断

入口路由同时完成唯一一次并行判断。只有以下条件同时满足时，才使用 `subagent-fanout-delivery`（分级与任务卡规则见 `subagent-fanout-delivery/references/overlap-classification.md`）：

- 至少两个可独立推进的工作包；
- 预计节省的时间或上下文明显大于派发、等待和集成成本；
- 文件、资源和契约边界可隔离。

工作包数量本身不构成并行理由；收益不足时主 Agent 串行处理。无法证明可隔离时串行。确定并行后才由 `subagent-fanout-delivery` 分级和生成任务卡（R1/R2/R3）；正式计划只记录该路由结果，不再次判断。最终计划、共享契约、最终写入、集成和验证仍由主 Agent 保留。

## 平台适配

- **设计意图与三路分流的权威描述**：你的 Agent 工作流笔记（本机 Obsidian 知识库）。改路由或改工作流前先读它；两宿主的技能面与降级路径见该笔记的宿主可用性矩阵。

仅在平台行为会影响当前任务时读取 `references/codex-tools.md`、`references/pi-tools.md` 或 `references/antigravity-tools.md`。
