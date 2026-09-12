# skill-grimoire

**Agent workflow skills for Codex** — 并行 fan-out 分级、push 前独立 Review 门禁、技能路由、交接文档写作。

> *grimoire* ＝ 魔导书：把技能收进一本随时可翻阅、维护、增补的书。

这 4 个技能解决的是同一件事的两端：**怎么把活安全地分出去**，以及**怎么确认活真的干完了**。
它们不绑定任何具体项目、不依赖第三方库，装进你的 Codex 就能用。

## 包含的技能

| 技能 | 解决什么 | 大约何时触发 |
|---|---|---|
| `subagent-fanout-delivery` | 子代理并行 fan-out：**R1/R2/R3 重叠分级**、任务卡契约、写入权边界、批次收尾与集成 | 一次要产出多个同类文件/模块；长文档分章节并行；只读子代理做独立审查 |
| `review-gate` | push 前**独立只读 Review 门禁**：风险三档（免审 / 中风险 / 高风险）、finding 三档严重性与处置、修复后复核 | 有仓库行为变更、准备 push 时 |
| `using-superpowers` | **技能路由**：直通 / 轻流程 / 正式计划三档入口，以及**唯一一次**并行判断（并行是否值得） | 任务开始时决定该用哪些技能、要不要并行 |
| `agent-handover-prompts` | **交接文档写作**：任务卡交接 vs 进展交底两种形态、结论四层可信度（已实测/已推导/估算/未检查）、机检自检清单 | 换会话、交给无记忆的下一 agent 时 |

## 安装

```bash
git clone https://github.com/KonjacW/skill-grimoire.git
mkdir -p ~/.codex/skills/active
cp -r skill-grimoire/active/* ~/.codex/skills/active/
```

Windows PowerShell：

```powershell
git clone https://github.com/KonjacW/skill-grimoire.git
New-Item -ItemType Directory -Force "$env:USERPROFILE\.codex\skills\active" | Out-Null
Copy-Item -Recurse .\skill-grimoire\active\* "$env:USERPROFILE\.codex\skills\active\"
```

技能在**会话启动时**载入，装完新开一个会话即可。

## 怎么用

- **自动路由**：技能靠 `description` 匹配任务。例如「把这份规格拆成 3 个独立模块并行做」会命中 `subagent-fanout-delivery`；「准备 push 了，先过一遍门禁」会命中 `review-gate`。
- **显式点名**：在提示里直接写技能名，例如「用 `subagent-fanout-delivery` 的 R1/R2/R3 给这个任务分级」。
- **典型链路**：

```
任务 → using-superpowers（路由：直通/轻流程/正式计划 + 并行判断）
     → 设计 / 计划
     → subagent-fanout-delivery（R1/R2/R3 分级 → 任务卡 → 分批执行 → 主 agent 集成）
     → 完成前验证（证据强度与风险相称）
     → review-gate（有仓库行为变更且要 push 时：独立只读 Review）
     → agent-handover-prompts（换会话/交给下一个 agent 时）
```

## 目录结构

```
active/<skill>/SKILL.md        技能本体（每个技能一个目录）
active/<skill>/references/     按需加载的细则
scripts/publish.py             维护者用：重建本仓库（含脱敏与门禁扫描）
```

## 设计取向

- **写入权集中在主 agent**：子 agent 默认只读——不写入共享最终工作区、不提交、不推送、不执行不可逆外部操作；候选产物由主 agent 检查后单点写回。
- **按重叠度分级而不是一刀切**：R1（独立文件）可隔离并行产出；R2（同文件不同区域）交定位 patch 由主 agent 顺序应用；R3（共享契约/同一决策路径）先由主 agent 定不变量，只允许只读设计或隔离候选。
- **门禁不可自审替代**：没有独立审查者时，正确做法是**停止 push 并如实报告门禁未满足**，而不是自己看一遍。
- **证据与风险相称**：文档改动给最小验证就够；契约、迁移、权限、并发类变更才上完整 Review。**「未检查」不得写成「通过」**。
- **结论分层**：交接与报告区分「已实测（有原始输出）/ 已推导 / 估算 / 未检查」，未检查单独成节。

## 适用范围

- 面向 Codex（技能目录 `~/.codex/skills/`）。技能内容与具体仓库无关，可直接用于任何 git 项目。
- `review-gate` 的 push 门禁假定项目里有 `AGENTS.md`（或同类约定文件）声明硬门槛；没有也能用，按其风险表执行。
- 本技能包是**流程/协议类**技能：不含可执行代码，不依赖任何第三方库或 API。
- 技能正文以中文为主。

## 许可

MIT（见 `LICENSE`）。`using-superpowers` 的写法参考 [obra/superpowers](https://github.com/obra/superpowers)（MIT），在此致谢。

问题或改进建议欢迎开 issue。
