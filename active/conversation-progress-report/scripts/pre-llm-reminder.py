#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pre_llm_call shell hook —— 自动提醒「进展汇报」技能，让 conversation-progress-report
不必等用户开口就能被读到。

设计（为什么是条件注入，而不是每轮都注入）：
- 短对话（纯问答）不该被这个提醒打扰，也不该付 token：会话消息数 < MIN_MESSAGES 时静默。
- 提醒要稀有：每新增 EVERY_N 条消息才注入一次（用本机状态文件记「上次注入时的消息数」）。
- **每轮都写心跳**：状态文件记 {n, last_inject_n, ts}。这是「关汇报」能落地的前提——
  agent 不一定知道自己的 session_id，让它取状态目录里 mtime 最新的文件即可确定「当前会话」。
- 用户说「关汇报」时，agent 按技能正文写 `<HERMES_HOME>/progress-report-off/<session_id>.flag`；
  脚本看到它就对该会话永久静默。
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

MIN_MESSAGES = 8   # 约 4 轮之后才开始提醒（更短的对话不可能是「有阶段成果」的长活）
EVERY_N = 6        # 之后每新增 6 条消息提醒一次（约每 3 轮一次，省 token）
SKILL = "conversation-progress-report"

REMINDER = (
    "[自动汇报提醒] 本对话若已出现阶段成果（完成一个阶段 / 关键结论 / 实验出数 / 口径定版）"
    f"且尚未开汇报，按技能 `{SKILL}` 维护 report/ 下的进展文件；用户已说「关汇报」时忽略本提醒。"
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
    off_flag = home / "progress-report-off" / f"{sid}.flag"
    state = home / "progress-report-state" / f"{sid}.json"

    if off_flag.exists():
        emit({})
        return

    last = 0
    try:
        last = int(json.loads(state.read_text(encoding="utf-8")).get("last_inject_n", 0))
    except Exception:
        last = 0

    inject = n >= MIN_MESSAGES and (n - last) >= EVERY_N
    if inject:
        last = n

    # 心跳每一轮都写（不只是注入那轮）：这是「当前会话 = 最新状态文件」这个约定的依据。
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"n": n, "last_inject_n": last, "ts": round(time.time())}),
                         encoding="utf-8")
    except Exception:
        pass              # 写不进去就退化成「每轮都提醒」——不理想，但绝不能让 hook 崩

    emit({"context": REMINDER} if inject else {})


if __name__ == "__main__":
    main()
