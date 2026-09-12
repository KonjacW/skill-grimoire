# worktree 的前置条件与收尾边界

> 来源：ThreadGate 技能 `using-git-worktrees` v0.1.0
> （`~/.codex/plugins/cache/threadgate-local/threadgate-workflow/0.1.0/skills/using-git-worktrees/SKILL.md`，6890 B）。
> 合并日期 2026-09-11。**只取两条被保守化的规则**——原技能的完整 worktree 建栈流程（Step 0–3、目录选择、`.gitignore` 校验）不在此处照搬；需要时按宿主原生 worktree 工具处理。

## (a) 前置条件：不是所有任务的强制步骤

只有在**四条同时满足**时才创建 worktree：

1. 有 git 仓库；
2. 属于**高风险**变更（按 `review-gate` 的档位判定：API/外部契约、持久化/迁移、权限、并发/幂等、缓存/队列、部署、跨 Agent 集成不变量）；
3. **隔离确有价值**（变更会动到共享契约、当前分支不干净，或需要保留可回滚的干净基线）；
4. **用户允许**。

非仓库、安全工作区、低风险变更 → 直接在当前工作区做，不额外创建 worktree。
未获得用户同意时不得擅自创建；用户已声明偏好时按其偏好执行，不再重复询问。

创建前必须先检测**是否已在隔离工作区**（`git rev-parse --git-dir` vs `--git-common-dir`；注意 submodule 也会让两者不等），已在其中则不再嵌套创建。

## (b) 收尾边界：集成方式由用户选择

收尾时**不得自作主张**执行 `merge`、`push`、删除分支或清理 worktree。
正确做法是把选项摆出来交用户拍板（本地合并 / 推分支开 PR / 保持原样），选中项才执行。
- 删除分支/工作区只在用户**明确要求**时发生（丢弃类操作要求用户原话确认）。
- push/merge 门禁：有行为变更时须先过 `review-gate` 的独立只读 Review（见该技能与 `AGENTS.md`）。
- 只清理本任务自己创建的 worktree 目录；其他 worktree 归宿主所有，不碰。
- 推被拒 = 远端已前进：先调查，不得用 force-push 绕过（除非用户明确要求）。
