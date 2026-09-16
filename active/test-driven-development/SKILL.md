---
name: test-driven-development
description: "Use when 改代码要先写失败测试（RED→GREEN→REFACTOR）。"
---

# 测试驱动开发

> **来源与署名**：`references/writing-good-tests.md` 取自 [obra/superpowers](https://github.com/obra/superpowers)（MIT © 2025 Jesse Vincent），**唯一的改动是删除其中一处指向上游另一技能的行内指针**；本文件（`SKILL.md`）为本包自有整理。再分发时请保留署名。

测试强度按变更风险与可测试性付费。可稳定自动化验证的功能、Bug 修复和行为回归优先使用 TDD；不把没有可靠测试面的局部改动伪装成 TDD。

## 路由

| 情形 | 要求 |
|---|---|
| 可稳定测试的功能或回归修复 | RED：写失败测试并确认失败原因；GREEN：最小实现并运行目标测试；REFACTOR：保持通过 |
| 无可靠自动化测试面的局部代码/脚本 | 记录原因，实施后做针对性回归或可复现手工验证 |
| 配置 | 解析、加载、启动或受影响路径验证 |
| 文档、格式、机械重命名 | 不要求 TDD；用 diff、链接、渲染或目标搜索验证 |

测试必须验证可观察行为，不以 mock 调用次数代替结果。涉及共享契约或高风险时，补充契约验证并按 `review-gate` 处理 push 前审查。

不得因为测试存在就省略需求边界；也不得因为测试困难而跳过验证。验证选择见 `pre-commit-verification`（风险档 ↔ 最小证据强度见 `pre-commit-verification/references/verification-strength-by-risk.md`）。

附属测试写法见 [`references/writing-good-tests.md`](references/writing-good-tests.md)。
