# 并行重叠分级与写入权边界（R1/R2/R3）

> 文中的 `spawn_subagent`（含控制动作 `action='stop'`）指**宿主提供的子代理工具**——换成你自己宿主的工具名即可。

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

## 慢子代理：接管与增量回馈

主 Agent 在回合内**要么等、要么接管**，不要空等。子 Agent 的结果只在主 Agent 回合**之间**投递（源码 `tools/async_delegation.py` 模块头写明 never mid-turn），因此回合内**唯一可读的通道是文件**：宿主 home 下的 `cache/delegation/live/<delegation_id>/task-<N>.log`（源码 `tools/delegation_live_log.py:3-8`：每行 append 时即 flush、7 天保留）。

### 接管的两个硬触发（假阳性都极低）

| 信号 | 判定 | 阈值 |
|---|---|---|
| 流水停滞 | 对 `task-<N>.log` 两次 `stat -c %s`（间隔 ≥60s）字节数不变，**且**最后一条 `tool`/`result` 行的时间戳陈旧 | 静止 ≥ **450s** |
| 原地重试 | `tool` 行中同一命令指纹的出现次数，**或**单条 `result` 载荷里同一失败标志（重复 Traceback / 多个非零退出码）的出现次数 | ≥ 3 次 |

> **450s 的适用范围（源码实测）**：`tools/async_delegation.py:59-60` 是 `_STALE_CHECK_INTERVAL = 30.0`、`_STALE_IDLE_SECONDS = 450.0`；但**子 Agent 正在工具调用中时宿主用的是 `_STALE_IN_TOOL_SECONDS = 1200.0`**（同文件 :61，与 :839 `limit = _STALE_IN_TOOL_SECONDS if in_tool else _STALE_IDLE_SECONDS`）。宿主自己的 monitor 线程也会在超过阈值 + `_STALL_GRACE_SECONDS = 120.0` 宽限后把子 Agent 判为 stalled 并终结（行为注释 :55-58；常量 `_STALL_GRACE_SECONDS` 在 :62），所以**宿主可能比你先动手**；遇到宿主已终结的情况，按已拿到的产物 + 流水收尾即可，不必再 stop。

> **不要用 `mtime` 单独判「最后一次动作」**：流式 delta 是缓冲落盘的（源码 `tools/delegation_live_log.py:34-36`：另一个事件类型到达、或完成时才整行刷出），正文类输出会让 mtime 滞后于真实活动。可靠做法是看 `tool`/`result` 行的行内时间戳（这两类 append 即 flush）。

> **实测教训（2026-09-12）**：子代理常把多次重试**塞进一次 shell 调用**，此时 `tool` 行只有 1 条、指纹只出现 1 次，**只看 `tool` 行会漏判**。实测流水长这样：`tool -> terminal(DIR=… + 7 commands)`，真正的证据在下一行 `result` 载荷里（`EXIT1=1 / EXIT2=1 / EXIT3=1` 三段 Traceback）。所以判据必须同时看 `result` 载荷。

不要用 `manifest.json` 的 `status` 判进度——它只在派发时写、整批结束才更新（源码 `tools/delegation_live_log.py:251-252` `_manifest_path`、:255-269 `_write_manifest`（落盘 `_dump_json` 在 :260）、:270-276 `update_manifest_statuses`；调用点 `tools/delegate_tool_dispatch.py:171`）。**单靠「流水不动」也不足以判定滞后**：日志是截断视图，一条长工具调用期间只写 `tool` 行、结束才写 `result` 行，流水必然静默（实测单条终端调用 20.5s 静默）。

### 接管三步

`stop` 是**协作式**的（请求后停在下一个迭代边界，并会取消进行中的工具调用，源码 `tools/delegate_tool_registry.py:98-99`）。**第 1 步必须在 stop 之前做完**——不只因为顺序规范，而是因为**完成消息可能不带任何内容**：

> **实测教训（2026-09-12）**：`stop` 之后回来的完成消息只有状态标记 `(no summary — status=interrupted)`，**没有任何部分结果内容**（宿主文档在 `tools/delegate_tool_registry.py:289-293` 却承诺 partial result 仍会回传——**当作宿主行为差异处理，不要依赖它**）。所以事实基线只有两个来源：**实时流水 + 文件系统盘点**；没取证就 stop = 手里什么都没有。
> 同一次实测还量到：`stop` 生效有延迟（从请求到真正结束约 **23s**，单样本），它会取消 in-flight 工具，中断在流水里留成 `result | terminal ERROR … "[Command interrupted]" exit_code 130`。**不要重复下 stop，也不要轮询等它。**

1. **取证**：`tail -n 100 <log>` 看最后动作（尤其最后一条 `result` 的载荷）；再逐个盘点任务卡声明的产物。**「文件存在」不等于「已完成」**——中断会砍掉 in-flight 写入，半写产物与完整产物在 `test -e` 下无法区分。以任务卡声明的 **hash/字节基线**为准（共同基线本就要求记 hash，见本文件前文 R2/R3 约定）；没有基线的产物，至少间隔 60s 量两次大小，两次一致才算完成。
2. **停**：`spawn_subagent(action='stop', subagent_id=…)`（宿主的子代理控制动作）。返回 `interrupt_requested` 即已受理，**不要等**；完成消息里若没有内容，以第 1 步的流水与产物盘点为准。
3. **接着做**：从第一个未完成产物开始，**不重做第 1 步已确认完成的产物**。

**预算与重派**（约束**写类**任务卡；审查类走下一节的「停掉后重派全新审查者」，但同一审查任务卡同样最多重派一次，避免无限换人）：同一任务卡**最多接管重派一次**；一次都没有产出任何声明产物时，主 Agent 直接自己做，不再重派（每轮重派的等待不递减，而剩活递减）。剩余工作只在能切成 **≥2 个互不重叠切片且每片 ≥3 步**时才重派；否则主 Agent 自己收尾——一次自包含任务卡的派发成本，在剩 1–2 步的活上一定更慢。

### 审查类子 Agent：不得接管，但可以增量回馈

审查的全部价值在信息隔离：主 Agent 接管审查 = 实现者自审，`review-gate` 明文禁止（自审不算独立门禁）。但**不必因此干等**，两条允许路径：

1. **停掉后重派全新审查者**：停掉滞后的审查者，另派一个零上下文的独立审查者。隔离性不破，且不必无限等。
2. **增量回馈**（审查者边审边报，主 Agent 立刻开工）：审查任务卡的产物清单里必须包含一个 **findings 文件**，审查者每定一条就**追加一行**（字段沿用 `review-gate`：严重性 ｜ 文件:行 ｜ 错误行为 ｜ 证据；末项在本节改成「是否 blocking」——`review-gate` 的原第 5 项是「建议动作」，改这一项是为了让主 Agent 能立刻判断该不该开修）。主 Agent 在自己的回合内读该文件，对已写出的 findings **立刻开修**——自己修，或按上面的切片规则把互不重叠的几条并行派修（同一文件的多条必须串行，避免双写）。

> **「只读」的定义（否则本节自相矛盾，且与 `~/.codex/AGENTS.md`「审查者只读：不得修改文件」冲突）**：审查者的只读禁令针对**被审工作区**——不得修改/创建/删除被审文件、不得做 git 写操作；写**指定的 findings 文件**是**唯一例外**，且必须在任务卡里显式声明这一例外。除 findings 文件外，审查者不得产出任何东西。

增量回馈必须守住三条不变量：

- **findings 必须绑定被审基线。** 审查任务卡要求在 findings 文件头部先写一行基线：**被审 revision（commit / 相关文件 hash，含脏工作树状态）**。没有基线，「与最终 diff 对账」就没有锚点，也无法判断审查者是在新旧混合的哪个状态上下的结论。
- **部分 findings ≠ 审查完成。** 已回馈的 findings 只许用来「提前开工」，**不得**用来判定通过；门禁满足与否仍以审查**完整结束**为准（`review-gate`：审查只认集成后的最终 diff）。
- **修复后必须由独立审查者复核。** 边审边修会让 diff 在审查眼皮底下变动，所以审查结束后要**另派一个独立审查者（或原审查者，仍只读）**按 `review-gate` 复核（只复核原 finding、修复 diff、相关不变量与回归验证；仅当修复扩大风险面时才完整重审）。**主 Agent 不得自己复核自己的修复**——那正是本节禁止的自审。审查者不得被 steer 成边审边改。

## 收束

每波结束由主 Agent 检查实际 diff、验证结果、共享不变量和未决风险，再按顺序集成。
并行局部审查**不**替代最终集成 diff 的 Review（push 门禁见 `review-gate`）。
