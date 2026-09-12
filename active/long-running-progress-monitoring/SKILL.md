---
name: long-running-progress-monitoring
description: "Use to monitor long-running training or batch jobs."
license: MIT
metadata:
  agent:
    tags: [superpowers, long-running-progress-monitoring]
    related_skills: []
---
# 本地长期程序进度监控

> 来源：上游 `obra/superpowers`（`https://github.com/obra/superpowers`）——**MIT 许可，2026-09-12 经 GitHub API 实测（`license: MIT`）核实**，随本包一并发布并保留署名与许可声明。加载方式：Codex 与 Hermes 都从 `active/` 读取；Windows 下用 PowerShell 脚本（`scripts/`），能力不可用时降级为文档化内联轮询。

## 统一执行策略

优先使用脚本监控器：`monitor-progress.ps1` 负责无背景刷新，`read-events.ps1` 负责读取 `events.jsonl` 增量事件。脚本位于**本技能的** `scripts/`（已从 Codex 技能目录搬入，不再依赖外部路径）；在独立环境中无法访问该目录、脚本执行被策略阻止或事件文件不可用时，回退到本技能下方的内联 PowerShell 模板。

- 事件协议（`events.jsonl` 字段与固定类型）、5 分钟阈值、20 分钟节流与无 PowerShell 时的内联降级路径：见 `references/events-protocol.md`；监控脚本在 `scripts/`。

脚本优先时，事件文件每行必须是 JSON 对象，至少包含 `event_id`、`timestamp`、`type`、`severity`、`task` 和 `summary`。只记录阶段开始、任务开始/完成、最佳指标刷新、停滞、错误、恢复和进程结束等重要变化；无变化的心跳不写入事件。读取事件失败时保留上一轮状态并标记“文件正在写入”。

脚本与内联模板都必须遵守同一计数口径：总任务数来自冻结协议或账本，完成数只计入完整且状态为 `completed`/`success` 的结果，validation/test 不得作为训练完成数来源。`Ctrl+C` 只退出监控，不终止主程序。

当本地程序预计运行数分钟以上时，必须同时提供启动命令和可复制的 PowerShell 监控命令。监控命令只读日志、账本、进程和 GPU 状态，不改变或终止主程序；输出应足够细粒度，便于判断程序是否卡住以及何时结束。

## 强制输出

- 默认每 20 秒刷新一次；训练实际运行期间，助手对用户的状态汇报频率可为每 20 分钟一次。
- 使用无背景、前台刷新输出。进度条使用 ASCII 字符（例如 `#` 和 `-`），不要依赖彩色背景、表情符号或不可见控制字符。
- 必须显示已完成任务数、总任务数和百分比，例如 `完成: 3/12 (25.0%)`，并单独显示 `completed / running / pending`。
- 显示阶段、当前任务或候选、seed、epoch、最近指标、最佳指标和已用时间；能可靠计算时显示 ETA，并说明 ETA 基于已完成任务的平均耗时。
- 显示主程序 PID、CPU 时间或利用率、内存；若环境有 NVIDIA GPU，则显示 GPU 利用率、显存占用、温度和功耗（读取失败时标记为不可用）。
- 显示日志尾部和账本状态，便于发现最后一次心跳、异常和恢复位置。
- 用户按 `Ctrl+C` 时只退出监控循环，不发送停止信号，不杀死主程序。
- 日志、账本或结果尚未生成时显示“等待文件”，不要报错退出；原子写入期间读取失败时保留上一轮状态并提示“文件正在写入”。进程结束后仍输出最终状态并退出循环。
- 不得读取、枚举或推断 `test` 数据来生成训练进度；validation 也不能被当作训练完成数来源。

## 实现规则

- 总任务数必须来自冻结协议或账本中的候选/作业清单，不能用日志行数猜测。
- 完成数只统计完整、可解析、通过协议和路径校验的结果；运行中、失败、半写入和仅有 checkpoint 的任务不能算完成。
- 优先读取结构化 JSON 字段；只有结构化字段缺失时，才用日志正则作为回退，并在输出中标注回退来源。
- PowerShell 读取应使用 `Get-Content -Tail`、`ConvertFrom-Json`、`Get-Process` 和 `nvidia-smi` 等只读操作。设置 UTF-8 以避免中文乱码：

  ```powershell
  $OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
  ```

## 推荐 PowerShell 模板

将下面变量替换为实际路径和 PID 后运行。它不使用后台作业，关闭窗口或按 `Ctrl+C` 只会停止监控。

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$root = '<PROJECT_DIR>\artifacts\run'
$targetPid = 12345
$logPath = Join-Path $root 'logs\run.log'
$ledgerPath = Join-Path $root 'ledgers\stage.json'
$resultsPath = Join-Path $root 'results'
$barWidth = 45

while ($true) {
    Clear-Host
    $now = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $ledger = $null
    if (Test-Path -LiteralPath $ledgerPath) {
        try { $ledger = Get-Content -LiteralPath $ledgerPath -Raw | ConvertFrom-Json } catch { }
    }

    $total = 0
    if ($ledger -and $ledger.candidate_ids) {
        $candidateCount = @($ledger.candidate_ids).Count
        $seedCount = if ($ledger.seeds) { @($ledger.seeds).Count } else { 1 }
        $total = $candidateCount * $seedCount
    } elseif ($ledger -and $ledger.jobs) { $total = @($ledger.jobs).Count }

    $completed = 0
    if (Test-Path -LiteralPath $resultsPath) {
        $completed = @(Get-ChildItem -LiteralPath $resultsPath -Filter '*.json' -File -ErrorAction SilentlyContinue | Where-Object {
            try { $r = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json; $r.status -in @('completed','success') } catch { $false }
        }).Count
    }
    $running = if ($ledger -and $ledger.running) { @($ledger.running).Count } else { 0 }
    $pending = if ($total -gt 0) { [Math]::Max(0, $total - $completed - $running) } else { '?' }
    $percent = if ($total -gt 0) { [Math]::Min(100, 100.0 * $completed / $total) } else { 0 }
    $filled = if ($total -gt 0) { [Math]::Round($barWidth * $percent / 100) } else { 0 }
    $bar = ('#' * $filled).PadRight($barWidth, '-')

    $proc = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
    $procState = if ($proc) { '运行中' } else { '已结束或未启动' }
    $cpu = if ($proc) { '{0:N1}s' -f $proc.CPU } else { 'N/A' }
    $mem = if ($proc) { '{0:N0} MB' -f ($proc.WorkingSet64 / 1MB) } else { 'N/A' }
    $tail = if (Test-Path -LiteralPath $logPath) { @(Get-Content -LiteralPath $logPath -Tail 8 -ErrorAction SilentlyContinue) } else { @('等待日志文件') }

    Write-Host "时间: $now"
    Write-Host "状态: $procState  PID: $targetPid  CPU: $cpu  内存: $mem"
    Write-Host ("进度: [{0}] {1,6:N1}%  完成: {2}/{3}" -f $bar, $percent, $completed, $(if ($total -gt 0) { $total } else { '?' }))
    Write-Host "任务: completed=$completed  running=$running  pending=$pending"
    if ($ledger -and $ledger.current_job) { Write-Host "当前: $($ledger.current_job)" }
    if ($ledger -and $ledger.best_auroc) { Write-Host "最佳 AUROC: $($ledger.best_auroc)" }
    if ($total -gt 0 -and $completed -gt 0 -and $proc) { Write-Host 'ETA: 按已完成任务平均耗时估算（仅供参考）' } else { Write-Host 'ETA: 暂不可稳定估计' }
    Write-Host 'GPU:'
    try { nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw --format=csv,noheader,nounits 2>$null } catch { Write-Host 'GPU: 不可用' }
    Write-Host '日志尾部:'
    $tail | ForEach-Object { Write-Host $_ }
    if (-not $proc) { break }
    Start-Sleep -Seconds 20
}
```

## 进度与 ETA 口径

- 多阶段程序显示当前阶段的局部进度，同时保留全局阶段名；阶段切换时总任务数可以重新计算，但必须明确标注。
- 没有完成任务时 ETA 显示“不稳定”或“暂不可估计”；GPU 利用率只能作为资源指标，不能当作进度。
- 若总任务数未知，显示 `?` 而不是伪造百分比；待账本出现后自动恢复正常计算。
- 进程结束后保留最后一轮日志、账本和最终比例，随后退出监控循环。

## 常见错误

- 只输出日志，不显示完成/总任务比例和可视化进度条。
- 把运行中任务、失败任务或半写入结果算作完成。
- 使用默认编码导致中文乱码，或使用彩色背景遮挡关键信息。
- 监控脚本按 `Ctrl+C` 误杀主进程，或把监控放在会自动结束主程序的后台作业中。
- 通过 validation/test 文件推断训练进度，造成数据边界污染。
- 程序尚未启动时无限空转而不提示“等待进程/文件”。
