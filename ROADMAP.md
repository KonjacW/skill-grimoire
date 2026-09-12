# 差距与改进方向（维护者清单）

> **本文件的定位**：记录「当前包」与「理想中的完整工作流」之间的已知差距、影响与候选方向，供维护者与使用者判断该往哪补。
> **它不是契约**：技能行为以 `active/*/SKILL.md` 为准，本文件只描述差距与选项，不改变任何技能语义。
> **更新时机**：每次增删技能、或改完 `README.md` 之后，重跑 §5 的复验命令，把变化回写到 §2。

**最后核对**：2026-09-12（包内 9 个技能）。

## 1. 覆盖度对照（工作流步骤 × 包内容）

| 工作流步骤 | 包内技能 | 状态 |
|---|---|---|
| 入口分流（直通 / 轻流程 / 正式计划） | `using-superpowers` | ✅ 在包 |
| 设计与计划 | `plan`、`spike` | ✅ 在包 |
| 并行预检与边界 | `subagent-fanout-delivery` | ✅ 在包 |
| 执行与长任务 | `plan/references/execution-loop.md`、`long-running-progress-monitoring` | ✅ 在包 |
| **实现期间的质量路径（测试驱动 / 根因定位）** | **无** | ❌ **整段缺失（见 G1）** |
| 完成前验证 | `pre-commit-verification` | ✅ 在包 |
| push 前门禁 / 独立 Review | `review-gate` | ✅ 在包 |
| 分支收尾 | `finishing-a-development-branch` | ✅ 在包 |
| 会话切换与交接 | `agent-handover-prompts` | ✅ 在包 |

**结论**：主干闭环完整，**唯一整段缺的是「实现期间的质量路径」**；其余为引用完整性与文档一致性问题。

## 2. 差距清单

每条都带可复算证据（文件:行）；影响分「外部读者」与「维护者」两种视角。

### G1 实现期间的质量路径没有包内技能（影响最大）

- **证据**：`active/plan/references/deliverable-task-schema.md`（「TDD 细节由 `test-driven-development` 定义」）、`active/pre-commit-verification/SKILL.md`（`related_skills` 与正文均引用 `test-driven-development`）—— 而该技能**不在包内**。
- **影响**：读者拿到「完成前怎么验证」，但拿不到它的**上游**：测试怎么写、失败怎么定位根因。
- **候选方向**：① 只补测试驱动那一个技能（若其来源与许可清晰、frontmatter 合规，改造量最小）；② 连同根因定位一起补；③ 不补技能，改为在包内写明「本包不含该技能，按本节文字自行执行」的降级说明。
- **成本**：① 低；② 中（正文含宿主专有表述，需逐处中立化）；③ 低。
- **备注**：这一条曾被维护者主动暂缓（「待按个性化理解再充实」），本文件的 §4 保留了它需要先回答的问题。

### G2 `github` 不在包内，而 `pre-commit-verification` 明确拿它做对比

- **证据**：`active/pre-commit-verification/SKILL.md` 的 `related_skills` 与正文对比句（「本技能验证**你自己**的改动；`github` 审**别人**的 PR」）。
- **影响**：外部读者的对比落在一侧空白上。
- **候选方向**：① 把 `github` 加进 SOURCES 白名单（注意它会带入 `references/` 与 `scripts/` 多个文件，需过脱敏门禁）；② 把对比句改成自足表述（不指向包外技能）；③ 保持现状。
- **成本**：① 中；② 低。

### G3 `deliverable-checker-suite` 不在包内（**最轻**，已有降级说明）

- **证据**：`active/subagent-fanout-delivery/SKILL.md` 的 `related_skills`；同文件正文**已写明**「这些技能缺失时，按本技能正文的重叠分级与任务卡执行」。
- **影响**：低（读者有明确 fallback）。
- **候选方向**：① 补进包；② 什么都不做（推荐）。

### G4 `sketch` 不在包内，而 `spike` 引用它

- **证据**：`active/spike/SKILL.md` 的 `related_skills`。
- **影响**：低（`spike` 的动作不依赖它）。
- **候选方向**：① 补进包；② 从 `related_skills` 里去掉（前提：正文确实不需要）；③ 保持现状。

### G5 README 存在**事实过期**（对读者最直接）

- **证据**：`README.md` 正文写「**八个**技能」（实为 9）；同段写「**不含可执行代码**、不依赖第三方库」（但新增的技能带两个 PowerShell 脚本并调用系统工具）；「## 技能一览」表只有 8 行，缺新增技能。
- **影响**：读者先读 README，这三处会直接误导。
- **候选方向**：① 逐处更正 + 表格补行；② 更彻底：把「技能一览」表改成从 `active/` 自动生成的清单（维护成本最低）。
- **成本**：① 低；② 低-中。
- **注意**：`README.md` 不在 SOURCES 白名单里，属仓库根文件，**手改**；改完仍需跑发布流程让门禁放行。

### G6 维护者的工作流规则未随包发布（口径可能分裂）

- **证据**：维护者的私有设计文档里有四条规则（汇报结论的可信度分层、开工前的预算与止损线、开工前的环境就绪检查、技能面注入成本口径），而包内 9 个技能与 README 的「工作流全景」都没有对应节点。
- **影响**：外部读者按包执行时拿不到这四条；维护者自己也可能出现「文档一套、包一套」的口径分裂。
- **候选方向**：① 分别落到最贴近的包内技能；② 在 README 加一节「工作流规则」集中说明；③ 明确「私有文档是原理面、包是执行面」，并在 README 里声明这一分工（推荐先做 ③，再决定是否 ①）。
- **成本**：① 中；② 低；③ 低。

### G7 设计意图文档不在包内

- **证据**：`active/using-superpowers/SKILL.md` 里指向设计意图的那一行，对**外部读者**是一个他拿不到的指针。
- **影响**：包可以**用**，但读者无法知道「为什么这样设计、边界在哪」。
- **候选方向**：① 从私有设计文档抽一份**对外版**（去掉宿主矩阵、本机路径与历史包袱）放进包根；② 扩充 README 的「设计取向」一节；③ 保持现状，接受那行是「对作者自己的指针」。
- **成本**：① 中；② 低。

### G8 包自身缺少「内部引用可解析」自检（这类漂移会复发）

- **证据**：G1–G4 的悬空引用能长期存在，是因为 `scripts/publish.py` 的门禁只查脱敏 / frontmatter / 编码 / 宿主专有写法，**不查** `related_skills` 与反引号路径能否在包内解析。README 的三处过期同样无人拦。
- **影响**：每次增删技能都可能再漂一次。
- **候选方向**：① 在 `publish.py` 的 `check()` 里加一条规则：扫 `active/**` 的 `related_skills` 与反引号路径，目标不在 `active/` 内即报 **warn**（不 fail，避免锁死）；② 只写成维护者手检步骤；③ 不做。
- **成本**：① 低-中（改脚本 + 自测 + 复发布）；② 低。

### G9 小项

- `README.md` 的「目录结构」一节只列了 `active/<skill>/SKILL.md` 与 `references/`，**没提技能内可以带 `scripts/`**（新增的技能就有）。
- 包内无 CHANGELOG / 版本注记（变更只在 git log 里）。
- 已核实**无需改**的一条：README 说「技能内容与具体仓库无关」——新增技能的示例路径在发布副本里已被脱敏为占位符，该表述成立。**该条记录在此是为了防止下次被误改。**

## 3. 建议顺序

按「对读者的误导程度 × 成本」：

1. **G5**（README 事实过期）—— 最直接、最快。
2. **G1**（质量路径整段缺失）—— 唯一的整段缺口，且其中一个候选技能改造量最小。
3. **G6**（规则口径）—— 先做 ③（声明分工），再决定是否落进技能。
4. **G2**（`github` 对比句）—— 二选一，成本都低。
5. **G8**（内部引用自检）—— 一次性投入，止住持续漂移。
6. G3 / G4 / G7 / G9 —— 低影响或属长期设计取向。

## 4. 尚待定夺的两个问题

- **Q1 判定标准**：所谓「完整工作流」，是要求**包能独立跑通全链**（读者只靠包即可），还是**包＝执行面、私有设计文档＝原理面**？这直接决定 G1 / G6 / G7 往哪边补。
- **Q2 三个被引用的包外技能**（`github`、`deliverable-checker-suite`、`sketch`）：是**该进包**，还是**该把引用改自足**？二者都不做，就会长期留在 G2/G3/G4。

## 5. 复验命令

在仓库根执行（Windows + git-bash；把 `G` 换成你的本机路径）：

```bash
G="<path-to>/skill-grimoire"
ls -d "$G"/active/*/ | wc -l                  # 包内技能数（应与 §1 声明一致）
grep -n "八个技能\|不含可执行代码" "$G/README.md"   # G5：两处应命中（即待改）
grep -c "^| \`" "$G/README.md"                # G5：技能一览表行数
cd "$G" && python scripts/publish.py && git status --short   # 门禁应通过，且无未预期改动
```

悬空引用（G1–G4）自查：

```bash
python - <<'PY'
import os, re
G = os.environ.get("SKILL_GRIMOIRE", ".")
pkg = {d for d in os.listdir(G + "/active") if os.path.isdir(os.path.join(G, "active", d))}
for sk in sorted(pkg):
    for r, _, fs in os.walk(os.path.join(G, "active", sk)):
        for f in fs:
            if not f.endswith((".md", ".yaml")):
                continue
            t = open(os.path.join(r, f), encoding="utf-8", errors="ignore").read()
            names = set(re.findall(r"`([a-z0-9][a-z0-9-]{2,})/(?:references|scripts|templates|assets)/", t))
            names |= {x.strip() for m in re.findall(r"related_skills:\s*\[([^\]]*)\]", t) for x in m.split(",") if x.strip()}
            for n in sorted(names):
                if n != sk and n not in pkg:
                    print("悬空引用:", sk, "->", n)
PY
```

## 6. 维护纪律

- 本文件在 `scripts/publish.py` 的 `KEEP_TOP` 白名单内，**不会被发布流程删除**（该流程会清掉根目录里不在白名单的条目）。
- 发布流程的脱敏门禁会扫描本仓库的**所有文本文件**（含本文件）：写入时不得包含私人路径、私人项目名、实名、凭据；命中即 fail-closed、拒绝推送。
- 新增/删除技能、或改 `README.md` 之后，必须复跑 §5 并更新 §2 与「最后核对」日期。
