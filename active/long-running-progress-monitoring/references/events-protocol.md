# 事件协议与降级路径（events.jsonl）

> 来源：ThreadGate 技能 `long-running-progress-monitoring` v0.1.0
> （`~/.codex/plugins/cache/threadgate-local/threadgate-workflow/0.1.0/skills/long-running-progress-monitoring/SKILL.md`，4049 B）。
> 合并日期 2026-09-11。脚本已一并搬到本技能的 `scripts/`（`monitor-progress.ps1`、`read-events.ps1`）。

## 触发阈值

- 预计连续运行 **> 5 分钟**；或
- 运行期间包含多个阶段/任务/候选项；或
- 失败、卡住、提前结束会造成明显成本；或
- 用户明确要求持续观察、定期汇报或可恢复审计。

预计 ≤5 分钟且没有阶段状态、结果账本或持续观察需求的命令 → 普通前台执行，不启用本技能。**5 分钟是默认阈值**：只要存在持续可见性或事后审计需求，即使更短也应启用。

## 事件协议

`events.jsonl` 每行一个 JSON 对象，最小字段：

| 字段 | 含义 |
|---|---|
| `event_id` | 事件唯一标识 |
| `timestamp` | 事件时间 |
| `type` | 事件类型 |
| `severity` | 严重度 |
| `task` | 关联任务 |
| `summary` | 一行摘要 |

固定类型：`stage_started`、`task_started`、`task_completed`、`best_metric_updated`、`stalled`、`error`、`recovered`、`process_finished`。
心跳与无变化刷新**不**生成事件；相同类型+任务+摘要在短时间内去重。异常事件才附带日志片段。
读取失败时保留上一轮状态并显示「文件正在写入」。

## 汇报节流

- 无变化 → 静默；
- 普通状态 → **最多每 20 分钟一次**；
- 异常、恢复、阶段完成、最佳指标刷新、进程结束 → 立即摘要；
- 子 agent 只返回摘要，不转发逐轮刷新（逐轮刷新不进入 agent 对话）。

## 降级路径（宿主没有 PowerShell 时）

1. 用终端提供的条件轮询读取**同一账本与结果字段**；
2. 无法后台保持监控 → 退回前台串行等待，并**如实说明**（不得把一次性检查描述成持续监控）；
3. 脚本不可访问 / 执行被策略阻止 / `events.jsonl` 暂不可读 → 回退到内联 PowerShell：前台每 20 秒刷新，读取账本与结果文件，显示 `completed / running / pending`、阶段、当前任务、指标、ETA、PID、CPU、内存、GPU、日志尾部；缺失文件显示「等待文件」；原子写入失败保留上一轮状态并提示「文件正在写入」。

脚本路径与内联路径必须使用**相同**的任务计数、完成判定与 `Ctrl+C` 语义（`Ctrl+C` 只退出监控器，不发送停止信号）。
所有事件、游标和日志文件必须写入任务**明确授权**的产物目录。

## 计数口径（不得违反）

- 总任务数只来自冻结协议或 ledger 的候选/作业清单；未知总数显示 `?`，不伪造百分比。
- 完成数只统计完整、可解析且通过协议与路径校验的 `completed` / `success` 结果。
- `pending = total - completed - running`。
- **不读取、不枚举、不推断 `test` 数据；validation 不计入训练完成数。**

## 最终审计内容

最终状态、完成/失败/未完成任务、最佳指标、异常时间线、产物路径、验证命令。
