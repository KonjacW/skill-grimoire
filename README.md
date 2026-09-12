# skill-grimoire

**一套完整的 Codex agent 工作流技能包** —— 从路由决策、设计计划、并行执行，到完成前验证、push 前门禁、分支收尾与会话交接。

> *grimoire* ＝ 魔导书：把技能收进一本随时可翻阅、维护、增补的书。

九个技能串成一条闭环：**怎么把活安全地分出去** → **怎么确认活真的干完了** → **怎么收尾**。
它们不绑定具体项目、不依赖第三方库；技能以文本为主，只有 `long-running-progress-monitoring` 带两个 PowerShell 脚本（`active/long-running-progress-monitoring/scripts/`），装进你的 Codex 就能用。

## 工作流全景

```
任务
 │
 ├─ using-superpowers        路由：直通 / 轻流程 / 正式计划 + 唯一一次并行判断
 │
 ├─ 需要设计时
 │   ├─ plan                 收敛方案 → 写成交付物级计划（docs/plans/）
 │   │   └─ references/execution-loop.md          逐项执行回路
 │   │   └─ references/deliverable-task-schema.md 8 字段交付物模板
 │   └─ spike                未验证的关键假设 → 丢弃式实验先证伪
 │
 ├─ 要并行时
 │   └─ subagent-fanout-delivery   R1/R2/R3 重叠分级 → 任务卡 → 分批 → 主 agent 集成
 │       └─ references/overlap-classification.md
 │
 ├─ 干完了
 │   └─ pre-commit-verification    证据强度与风险相称
 │       └─ references/verification-strength-by-risk.md
 │
 ├─ 准备 push（有仓库 + 行为变更）
 │   └─ review-gate            独立只读 Review 门禁（风险三档 + finding 处置 + 修复后复核）
 │       └─ references/review-prompt.md
 │
 ├─ 收尾
 │   └─ finishing-a-development-branch   本地合并 / 开 PR / 保持原样，由你选
 │       └─ references/worktree-setup.md   worktree 前置条件与收尾边界
 │
 └─ 换会话 / 交给下一个 agent
     └─ agent-handover-prompts   任务卡交接 / 进展交底两形态
         └─ references/进展交底骨架.md
```

## 技能一览

| 技能 | 解决什么 | 何时触发 |
|---|---|---|
| `using-superpowers` | **路由入口**：三档（直通 / 轻流程 / 正式计划）+ 唯一一次并行判断 | 任务开始时决定用哪些技能、要不要并行 |
| `plan` | **计划**：把已确认方案写成交付物级计划；含执行回路与 8 字段模板 | 高风险 / 共享契约 / 迁移权限部署 / 跨会话任务 |
| `spike` | **丢弃式验证**：关键假设先做一次性实验证伪，再动手 | 方案里有没验证过的关键假设 |
| `subagent-fanout-delivery` | **并行 fan-out**：R1/R2/R3 重叠分级、任务卡契约、写入权边界、批次收尾 | 一次要产出多个同类文件/模块；长文档分章节 |
| `pre-commit-verification` | **完成前验证**：风险档 → 最小充分证据；安全扫描与质量门禁 | 准备声明"做完了"之前 |
| `review-gate` | **push 前门禁**：独立只读 Review，风险三档、finding 严重性三档、修复后复核 | 有仓库行为变更、准备 push |
| `finishing-a-development-branch` | **收尾**：验证测试 → 摆出集成选项（本地合并 / PR / 保持）→ 清理 | 分支工作结束、由你决定怎么落地 |
| `agent-handover-prompts` | **交接**：任务卡交接 vs 进展交底，结论四层可信度 + 机检清单 | 换会话、交给无记忆的下一 agent |
| `long-running-progress-monitoring` | **长任务进度监控**：description 原文「Use to monitor long-running training or batch jobs.」；含自带脚本与文档化内联降级 | 长跑训练 / 批处理作业需要看进度时 |

## 安装

```bash
git clone https://github.com/KonjacW/skill-grimoire.git
mkdir -p ~/.codex/skills/active
cp -r skill-grimoire/active/* ~/.codex/skills/active/
```

Windows PowerShell：

```powershell
$repo = "https://github.com/KonjacW/skill-grimoire.git"
git clone $repo
New-Item -ItemType Directory -Force "$env:USERPROFILE\.codex\skills\active" | Out-Null
Copy-Item -Recurse .\skill-grimoire\active\* "$env:USERPROFILE\.codex\skills\active\"
```

技能在**会话启动时**载入，装完新开一个会话即可。

## 怎么用

- **自动路由**：技能靠 `description` 匹配任务。例如「准备 push 了，先过一遍门禁」→ `review-gate`；「把这个规格拆成 3 个模块并行做」→ `subagent-fanout-delivery`；「换个会话接着做」→ `agent-handover-prompts`。
- **显式点名**：在提示里写技能名，例如「用 `subagent-fanout-delivery` 的 R1/R2/R3 给这个任务分级」。
- **按需组合**：不必每次跑完整链路——小改动走 `using-superpowers` 的"直通"档，只有真需要设计和并行时才展开。

## 设计取向

- **写入权集中在主 agent**：子 agent 默认只读，不写入共享最终工作区、不提交、不推送；候选产物由主 agent 检查后单点写回。
- **按重叠度分级，不一刀切**：R1（独立文件）可隔离并行产出；R2（同文件不同区域）交定位 patch 由主 agent 顺序应用；R3（共享契约/同一决策路径）先定不变量，只允许只读设计或隔离候选 patch。
- **计划不等于授权**：计划不自动授予提交/推送权限，也不自动触发 Review；只有你明确授权时才加入 commit 步骤。
- **门禁不可自审替代**：没有独立审查者时，正确做法是**停止 push 并报告门禁未满足**，而不是自己看一遍。
- **证据与风险相称**：文档改动给最小验证就够；契约、迁移、权限、并发类变更才上完整 Review。**「未检查」不得写成「通过」**；无法判定风险档时按高风险处理。
- **收尾不替你做决定**：集成方式（合并 / PR / 保留 / 丢弃）由你选；skill 只执行你选的那条，且不擅自清理分支或 worktree。

## 目录结构

```
active/<skill>/SKILL.md        技能本体（每个技能一个目录）
active/<skill>/references/     按需加载的细则（分级表、模板、门禁提示模板等）
active/<skill>/scripts/        个别技能自带的可执行辅助脚本（如长任务监控的 PowerShell 脚本）
scripts/publish.py             维护者用：重建本仓库（宿主中立化 + 脱敏 + fail-closed 门禁）
```

## 占位符说明

发布副本里会出现少量尖括号占位符，它们是**脱敏流程把私人路径替换掉之后的产物**，不是让你照抄的字面值——读到就代入你自己的本机路径：

| 占位符 | 含义 |
|---|---|
| `<PROJECT_DIR>` | 宿主项目根目录（示例脚本里用来指向产物目录） |
| `<NOTE_VAULT>` | 笔记库根目录 |
| `<OBSIDIAN_VAULT>` | Obsidian 仓库根目录 |

后两个由发布流程在命中私人笔记路径时写入；技能正文里若出现其它打尖括号的写法（`<path-to>`、`<skill>`、`<编号>` 之类），那是文档占位符，按上下文理解即可。全树自扫命令见 `ROADMAP.md` §5。

## 说明与依赖

- 面向 Codex（技能目录 `~/.codex/skills/`）。技能内容与具体仓库无关，可直接用于任何 git 项目。
- `review-gate` 的 push 门禁假定项目里有 `AGENTS.md`（或同类约定文件）声明硬门槛；没有也能用，按其风险表执行。
- `pre-commit-verification` 与 `spike` 里出现 `spawn_subagent` 时，指的是**宿主提供的子代理派发工具**——换成你自己宿主的工具名即可（Codex 里就是它自带的 agent 工具）。
- `plan` 默认把计划写到工作区内的 `docs/plans/`。
- `spike` 若检测到你装了上游的全量 GSD 系统（`gsd-spike` 同族技能），会建议改用那套；没有就用本技能这个轻量版。
- `long-running-progress-monitoring` 的监控脚本是 PowerShell（Windows）；在能力不可用的宿主上按技能正文的降级说明做文档化内联轮询。
- 技能正文以中文为主（部分技能为英文）。

## 许可与致谢

本仓库自有内容：MIT（见 `LICENSE`）。部分技能派生自第三方工作，按其原许可（MIT）使用：

| 技能 | 来源 |
|---|---|
| `finishing-a-development-branch` | [obra/superpowers](https://github.com/obra/superpowers) |
| `pre-commit-verification` | obra/superpowers + MorAlekss |
| `spike` | GSD（Get Shit Done）项目的 `/gsd-spike` 工作流，MIT © 2025 Lex Christopherson |
| `using-superpowers` | 写法参考 obra/superpowers |
| `plan` | 写作方法参考 obra/superpowers |
| `review-gate`、`subagent-fanout-delivery`、`agent-handover-prompts` | 自有（与 AI 协作整理） |

问题或改进建议欢迎开 issue。
