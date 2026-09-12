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
- **状态（2026-09-12）**：已按候选方向 ③ 处理——`plan` 与 `pre-commit-verification` 正文内联了 TDD 判据（先写失败测试→最小实现→重构；验证「测试是与代码同时写的」而非事后补），并删除了全部指向 `test-driven-development` 的派发式引用（`related_skills` 与祈使句）。因此本条目不再是「悬空引用」，只剩「包内没有独立的测试编写/根因定位技能」这一**能力缺口**；要补仍按方向 ①。
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

- `README.md` 的「目录结构」一节只列了 `active/<skill>/SKILL.md` 与 `references/`，**没提技能内可以带 `scripts/`**（新增的技能就有）。**本批已修**（补了 `active/<skill>/scripts/` 一行）。
- 包内无 CHANGELOG / 版本注记（变更只在 git log 里）。
- 已核实**无需改**的一条：README 说「技能内容与具体仓库无关」——新增技能的示例路径在发布副本里已被脱敏为占位符，该表述成立。**该条记录在此是为了防止下次被误改。**

### G10 脱敏的「整行规则」会静默塌缩：两条内容不同的 live 行被同一条规则覆盖，其中一条整段丢失

- **证据**：live 副本 `~/.codex/skills/active/agent-handover-prompts/SKILL.md:69`（123 字，陷阱教训「照抄规范样本会漏启动语句」）与 `:80`（239 字，规范样本指向）**内容不同**，却被同一条 `line_rule` 命中，替换文本同为一句 83 字；结果发布副本 `active/agent-handover-prompts/SKILL.md:69` 与 `:80` 是同一句 83 字，第 69 行那条教训**零残留**。重跑两次发布 sha1 不变——塌缩是幂等的，所以门禁不会报警。
- **影响**：发布副本静默掉内容；因为幂等，检查不会发现，读者也看不出少了什么。
- **候选方向**：① 把「同一条 `line_rule` 命中 ≥2 条**内容不同**的 live 行、且替换文本不含回引/分支」做成发布流程的**静态门禁**（fail 或 warn）；② 只靠维护者人眼复核（=现状，已经漏过一次）。**不要**改用「有没有重复长行」这类文本启发式兜底：live 里本就存在两条合法的重复长行（`finishing-a-development-branch:99,158`、`plan:158,170`，均为英文样板行），启发式必然误报。
- **成本**：① 低-中（改 `scripts/publish.py` + 自测 + 复发布）；② 零。
- **状态**：**已修**——私有脱敏表新增一条只匹配第 69 行的规则；Temp 目录重跑实测：两行各自保住、0 重复长行、门禁 exit 0。**待复发布**。

### G11 `scripts/` 目录同时绕过脱敏与门禁（潜在泄露面）

- **证据**：`SKIP_DIRS = {".git", "scripts"}` 在改前位于 `scripts/publish.py:38`（改后为 `:40`），被 `iter_text_files()`（改前 `:155`，改后 `:157`）按**目录名**在**任意层级**套用 → `active/<技能>/scripts/**` 既不参与宿主中立化，也不进 `--check` 扫描。实测本仓 27 个文本文件只扫到 23 个，漏掉的正是根 `scripts/` 下 2 个文件加 `active/long-running-progress-monitoring/scripts/` 下 2 个 `.ps1`。
- **影响**：技能内脚本是唯一不受脱敏/门禁约束的发布内容。当前两个 `.ps1` 逐类扫描 0 命中（无私人内容），属**潜在**泄露面：一旦技能内脚本带上私人路径，发布流程不会拦。
- **候选方向**：① `iter_text_files()` 改为只跳过**根级** `scripts/`（按相对路径判定，而不是按目录名）；② 仍跳过根级，但把 `active/**/scripts/**` 显式纳入扫描；③ 不改代码，把「技能内脚本目录属于发布内容，必须过门禁」写进 §6 维护纪律。
- **成本**：① 低；② 低；③ 零。
- **状态（2026-09-12）**：已按候选方向 ① 修——`iter_text_files()` 现在只跳过**仓根第一层**的 `.git`/`scripts`（仓根 `scripts/` 仍跳过，因为那里放着被 .gitignore 忽略的私有脱敏表，门禁不能自扫），扫描覆盖 23 → 25 个文本文件，`active/<技能>/scripts/**` 已纳入。独立 Review 复核时确认：`os.walk` 不跟随符号链接，深层同名目录逃逸路径未复现。

### G12 发布副本没有「与 live 同步」门禁（本批已实际发生）

- **证据**：live 副本 `~/.codex/skills/active/subagent-fanout-delivery/SKILL.md`（85 行 / 11,294 字节，mtime 18:32）比仓内 `active/subagent-fanout-delivery/SKILL.md`（83 行 / 10,290 字节，mtime 16:58）多两行，多出的内容含「铁律 13：并行子代理若要各自起本地服务/实例，端口与清理口径必须在任务卡…」（live:31）；live `using-superpowers/SKILL.md` 49 行 vs 仓内 39 行（差的正是 G13 那两处只读档）。而发布流程 exit 0、不报错。
- **影响**：读者拿到的包比维护者实际在用的少内容，且没有任何信号；「包」与「live」可持续分裂。
- **候选方向**：① 发布流程加一条**单向漂移检查**（live→仓内 diff 非空即 warn，并打印差异文件与行数）；② 把「改完 live 立刻复发布」写进维护纪律（弱约束，靠人）；③ 接受分裂，在 README 声明「包是快照，不保证与维护者本机一致」。
- **成本**：① 低-中；② 零；③ 零。

### G13 并行判断缺「只读取证」档：只读勘察/取证类任务被推回串行

- **证据**：原并行口径（`active/using-superpowers/SKILL.md`《一次并行判断》+ `active/subagent-fanout-delivery/SKILL.md` 的 R1/R2/R3 重叠分级）只按**写入冲突 / 隔离成本**给条件 → 零写冲突的只读任务没有对应档位。实测后果：一次纯调查任务被串行执行，跑了 **18 次工具调用**（写冲突为零，集成成本仅为汇总）。live 侧现已有 B 档（`~/.codex/skills/active/using-superpowers/SKILL.md:35-41`「只读勘察 / 取证类 fan-out」：≥3 个可独立推进的只读工作包 + 各写不同产物文件 + 写权互不相交即默认分片并行），同批还给 `subagent-fanout-delivery` 加了《只读取证类 fan-out》小节（任务卡必写 6 项、主 Agent 亲自复算关键数字、「先落盘报告骨架」）。
- **影响**：只读批量（多目录勘察、多源取证、并行检索比对）白白串行，代价直接体现在工具调用次数与墙钟时间上。
- **候选方向**：① **复发布**把 live 的 B 档与新小节带进包（先做这个，包内即生效）；② 在包内重叠分级表里补一行「只读档」索引，让读者从 R1/R2/R3 表就能找到它；③ 不改。
- **成本**：① 低（走发布流程）；② 低；③ 零。
- **状态**：**live 已修、包内未跟上**——即 G12 的一个实例。

## 3. 建议顺序

按「对读者的误导程度 × 成本」：

1. **G5**（README 事实过期）—— ✅ 已修：三处事实 + 目录结构 + 新增《占位符说明》。
2. **G12**（发布副本与 live 漂移）—— ✅ 已修：已复发布，且 `--check` 现在逐文件比对 live↔发布副本，漂移不再静默。
3. **G10**（脱敏塌缩丢内容）—— ✅ 已修：私有表加规则救回被吃掉的那条陷阱；同形态已门禁化（单规则塌缩 + 跨规则同常量两条判据）。
4. **G13**（只读取证档）—— ✅ 已修并已随本次复发布进包。
5. **G11**（`scripts/` 绕过门禁）—— ✅ 已修：只跳过仓根第一层，覆盖 23→25。
6. **G1**（质量路径）—— 🟡 派发式引用已清除（改内联判据），剩余「包内无独立的测试编写/根因定位技能」属能力缺口，要补按方向 ①。
7. **G6**（规则口径）—— ⬜ 未动：先做 ③（声明分工），再决定是否落进技能。
8. **G2**（`github` 对比句）/ **G4**（`spike` 引用 `sketch`）—— ✅ 已修：改成自足表述，包内已无指向包外技能的派发式引用。
9. **G8**（内部引用可解析自检）—— ⬜ 未做：本批用人工 + 子代理清单处理了现存悬空引用，但**自动检查仍未加进 `publish.py`**，同形态漂移还会复发。
10. **G3 / G7 / G9** —— ⬜ 低影响或属长期设计取向（G3 已有降级说明，按原推荐「什么都不做」）。

## 4. 尚待定夺的两个问题

- **Q1 判定标准**：所谓「完整工作流」，是要求**包能独立跑通全链**（读者只靠包即可），还是**包＝执行面、私有设计文档＝原理面**？这直接决定 G1 / G6 / G7 往哪边补。
- **Q2 三个被引用的包外技能**（`github`、`deliverable-checker-suite`、`sketch`）：是**该进包**，还是**该把引用改自足**？二者都不做，就会长期留在 G2/G3/G4。

## 5. 复验命令

在仓库根执行（Windows + git-bash；把 `G` 换成你的本机路径）：

```bash
G="<path-to>/skill-grimoire"
ls -d "$G"/active/*/ | wc -l                  # 包内技能数（应=9，与 §1 声明一致）
grep -n "八个技能\|不含可执行代码" "$G/README.md"   # G5：本批已修 → 应 0 命中
awk '/^## 技能一览/,/^## 安装/' "$G/README.md" | grep -c '^| `'   # 技能一览表行数（应=9；勿用全文件 grep，会把「许可与致谢」表一起数）
cd "$G" && python scripts/publish.py && git status --short   # 门禁应通过，且无未预期改动
```

两个根文档的不变量（重复长行 / 行尾）与占位符自扫：

```bash
python - <<'PY'
import collections, os, re
for p in ("README.md", "ROADMAP.md"):
    b = open(p, "rb").read()
    ls = b.decode("utf-8").split("\n")
    dup = [l for l, n in collections.Counter(x for x in ls if len(x) >= 40).items() if n > 1]
    print(p, "CRLF" if b"\r\n" in b else "LF", "重复长行:", dup or "无")
c = collections.Counter()
for dp, dn, fn in os.walk("."):
    if ".git" in dp.split(os.sep):
        continue
    for f in fn:
        try:
            t = open(os.path.join(dp, f), encoding="utf-8").read()
        except Exception:
            continue
        c.update(re.findall(r"<[A-Z][A-Z0-9_]{2,}>", t))
print("占位符:", dict(c) or "无")
PY
```

设计内**只应有** `<PROJECT_DIR>` / `<NOTE_VAULT>` / `<OBSIDIAN_VAULT>` 三个全大写占位符；冒出第四个 = 有人手写了占位符或替换表漏项，要查。

**这条自扫的数字在克隆侧与维护者侧不同，别当成不变量**：维护者侧当前各 5 处（技能正文示例 1 + 脱敏替换表 2 + README 说明表 1 + 本节 1），但其中「脱敏替换表 2」来自被 `.gitignore` 忽略的本机私有表——克隆者跑同一条命令只会得到各 3 处。判定标准是**占位符的种类**（只应有那三个）与「仓内文本里没有第四种」，不是出现次数。

**索引注入成本（口径）**：Codex 技能面逐条 `name` + `description` + 固定路径开销。2026-09-12 实测 **45 条 / 11,217 字符 ≈ 2.8k tokens/轮**；早前数字附录记的 46 条 / 18,340 字符 ≈ 4.6k 已过期，不要继续引用。**本仓的复验命令不覆盖这个口径**，增删技能后需要维护者侧重新测。

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
