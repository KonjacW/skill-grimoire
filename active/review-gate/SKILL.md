---
name: review-gate
description: "Use when 有仓库+行为变更准备 push：先过独立只读 Review。"
license: MIT
metadata:
  agent:
    tags: [review, gate, push, workflow]
    related_skills: [subagent-fanout-delivery, pre-commit-verification]
---

# 变更门禁（push 前独立 Review）

有仓库行为变更且准备 push 时，必须做一次独立只读 Review。用户决定 push；Review 不授予提交或推送权限。

宿主没有独立 reviewer、子代理或可用人工审查者时，不得用主 Agent 自审冒充独立 Review；停止 push/merge 收尾并报告门禁尚未满足。

## 路由

| 路径 | 条件 | 最低要求 |
|---|---|---|
| 免审 | 纯文档、注释、格式；调查 Plan；或明确无行为变化 | 最小相关验证 |
| 中风险默认 | 其余局部行为变更 | 一次轻量独立 Review：需求、明显回归、diff 范围 |
| 高风险 | API/外部契约、持久化或迁移、权限、并发/幂等、缓存/队列、部署、跨 Agent 集成不变量 | 风险标签驱动完整 Review、七项 finding 与处置 |

无法可靠判定风险时按高风险处理。并行局部 Review 不替代最终集成 diff Review。

## 范围清单

审查前记录：基线、`git status --short`、已提交范围（`merge-base(base, HEAD)...HEAD`）、已暂存 diff、未暂存 diff 和包含路径。审查结论必须回显该清单。

轻量 finding：严重性、文件与行号、错误行为、证据、建议动作。高风险 finding：严重性、文件与行号、触发条件、错误行为、影响、证据、最小修复建议。只报告可复现或能由代码路径证明的问题。 **不得替用户固化未表态项**：文档里明确标注「留给你决定 / 尚未表态」的条目，finding 只登记、不得直接改写为已定——那属于越过该文件记录的未决决策。

## 修复后复核

复核原 finding、修复 diff、相关不变量和回归验证。仅当修复扩大风险面、新增高风险接口或改变原不变量时，重新完整 Review。未修复阻塞项禁止 push；高风险重要项必须闭环。

提示模板见 `references/review-prompt.md`。`AGENTS.md` 的 push 前硬门槛保持权威。

## 阻断项处置

finding 里出现**阻断**严重性时，处置不是「记一笔然后放弃」，而是三件：① 回炉补足被质疑的基础（缺统计依据的性能保证 ⇒ 补外样本检验 / 重估停时规则）；② **预先约定降级形态**（「过不了检验就退回无保证的固定参数版」）；③ 写明**解除条件**——用哪个检验通过即解锁。缺第 ③ 条，路线会被永久关闭。

把「保证」与「机制」解耦：保证被证伪则机制保留、退回无保证版，不要整条路线报废。

长驻子代理多轮研究形态里的阻断项，同样走本节；该形态文件只留价值判断与指针，不复制本清单。

> frontmatter 里的 `related_skills` 只作交叉引用。缺失的技能不影响本技能独立使用——按本文各节执行即可。
