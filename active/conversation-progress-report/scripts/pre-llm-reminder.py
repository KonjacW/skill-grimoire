#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pre_llm_call shell hook —— 只为「已经启用汇报」的会话注入维护提醒。

口令制（用户 2026-09-15 定版）：**默认不写任何 report 文件**。只有用户在本会话说
「开汇报」（或等价的明确指令）之后，agent 才按技能 conversation-progress-report
维护该会话的进展文件，并且只在**出现实质性进展**时更新。

本脚本是这条规则的机械保证，**不是**自动开汇报的发动机：
- 没有启用标记 `<HERMES_HOME>/progress-report-on/<session_id>.flag` ⇒ 一律静默，
  一个字都不注入（未启用 = 不打扰、不诱导写文件）。
- 有标记 ⇒ 每新增 EVERY_N 条消息注入一次「别忘了更新」的提醒。
- 「关汇报」= 删除该 flag（agent 按技能正文执行）。
- 每轮都写心跳（state 文件）：agent 读环境变量 `HERMES_SESSION_ID` 就知道自己的会话 id
  （与心跳文件名严格一致）。`progress-report-state/` 里 mtime 最新的文件**只作候选排序**，
  多会话并发时它属于「最近发过调用的那个会话」，不得用来裁定「我是谁」。
- 任何异常都吞掉并输出 `{}`（等价「不注入」）：hook 出错绝不能影响正常回合。

wire protocol（Hermes shell hook，见 agent/shell_hooks.py::_serialize_payload）：
    stdin  = {"hook_event_name": "pre_llm_call", "tool_name": null, "tool_input": null,
              "session_id": "...", "cwd": "...",
              "extra": {"user_message": ..., "conversation_history": [...], ...}}
    stdout = 一个 JSON 对象；要注入就回 {"context": "追加到本轮用户消息的文本"}，不注入回 {}
"""
import json
import os
import pathlib
import sys
import time

EVERY_N = 6        # 已启用的会话里，每新增 6 条消息提醒一次（约每 3 轮一次，省 token）
SKILL = "conversation-progress-report"
REPORT_DIR = "<OBSIDIAN_VAULT>/report"

REMINDER = (
    "[汇报维护提醒] 本会话**已开汇报**（启用标记存在）。按技能 `" + SKILL + "`："
    "出现实质性进展（完成一个阶段 / 关键决策 / 口径定版 / 实验出数 / 结论翻转）时，"
    "更新该会话的报告文件（落点 `" + REPORT_DIR + "`，命名 `<对话主题>_进展汇报_<YYYYMMDD>.md`，"
    "同一对话同一天覆盖同一个文件、顶部更新「更新时间 HH:MM」），"
    "并在对话里给 3~5 行摘要 + 绝对路径。"
    "**没有实质性进展就不写**；用户说「关汇报」时按技能正文删除启用标记并停手。"
)


def hermes_home() -> pathlib.Path:
    env = os.environ.get("HERMES_HOME")
    return pathlib.Path(env) if env else pathlib.Path.home() / ".hermes"


def emit(obj) -> None:
    """stdout 只允许一个 JSON 对象：不注入就回 {}。"""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.write("\n")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        emit({})
        return

    if str(payload.get("hook_event_name") or "") != "pre_llm_call":
        emit({})          # 防御：被别的 payload 触发（如 hooks test 的合成载荷）时静默
        return

    extra = payload.get("extra") or {}
    history = extra.get("conversation_history") or []
    try:
        n = len(history)
    except Exception:
        n = 0
    sid = str(payload.get("session_id") or "unknown")

    home = hermes_home()
    on_flag = home / "progress-report-on" / f"{sid}.flag"
    state = home / "progress-report-state" / f"{sid}.json"

    last = 0
    inject = False

    # 关键：没有启用标记就绝不注入。默认路径 = 静默。
    if on_flag.exists():
        try:
            last = int(json.loads(state.read_text(encoding="utf-8")).get("last_inject_n", 0))
        except Exception:
            last = 0
        # 上下文压缩会把 conversation_history 整体替换成更短的列表（n 变小）。
        # 不处理的话 n - last 恒为负 ⇒ 注入被长期静默，直到 n 重新长回 last + EVERY_N，
        # 而长会话正是最该「防漏更新」的场景。检测到历史回退就把计数归零，
        # 使压缩后的下一次调用立刻恢复提醒（而不是再等 6 条消息）。
        if last > n:
            last = 0
        inject = (n - last) >= EVERY_N

    if inject:
        last = n

    # 心跳每一轮都写（不只是注入那轮）：这是「当前会话 = 最新状态文件」这个约定的依据。
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"n": n, "last_inject_n": last, "ts": round(time.time())}),
                         encoding="utf-8")
    except Exception:
        pass              # 写不进去就退化成「启用后每轮都提醒」——不理想，但绝不能让 hook 崩

    emit({"context": REMINDER} if inject else {})


if __name__ == "__main__":
    main()
