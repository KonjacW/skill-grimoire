#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pre_llm_call shell hook —— 技能工作流触发层（skill-grimoire / using-superpowers）。

要解决的问题（实测，见仓内 ROADMAP G18）：Hermes 的技能索引里只有「名字 + 描述 + 路径」，
触发条件写在技能正文里，而路由入口 `using-superpowers` 14 天只被读 4 次 ⇒ 并行判断与发散判断
从不发生。取证结论：Hermes 侧触达 = **用户消息里的词 × 索引描述里的词 × 记忆指针**，三者对齐才发生。
本脚本补的就是「用户消息里的词」这一环：条件命中时往本轮用户消息追加一行「先读哪个技能」，
零命中时不产生任何 token。

wire protocol（Hermes shell hook；见 agent/shell_hooks.py 与 agent/turn_context.py）：
    stdin  = {"hook_event_name": "pre_llm_call", "session_id": "...", "cwd": "...",
              "extra": {"user_message": ..., "conversation_history": [...],
                        "parent_session_id": ..., "is_first_turn": ...}}
    stdout = {"context": "追加到本轮用户消息的文本"} 或 {}（不注入）

设计约束（每条都对应一个真实代价）：
- 命中才注入、每轮最多 1 行、同一技能 COOLDOWN_MSGS 条消息内不重复 —— 注入本身就是成本。
- `parent_session_id` 非空 ⇒ 这是被派出去的子代理回合，直接静默（14 天 390 次 spawn_subagent）。
- 用户下了硬约束（只评审 / 不要执行 / 只改这一处）⇒ 抑制「并行 / 发散」类提醒。
- 任何异常吞掉并回 {} —— hook 出错绝不能影响正常回合。
- 只写技能名，不写路径：Hermes 按名取技能（skill_view），写路径既啰嗦又会引入非中立内容。

自测（内联，不另建文件）：python workflow-trigger.py --selftest
干跑（不经 Hermes）：   python workflow-trigger.py --explain "把这三个目录清点一遍"
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time

COOLDOWN_MSGS = 12          # 同一技能：距上次注入不足这么多条消息就不再注入
STATE_DIRNAME = "workflow-trigger-state"

# 规则表 = 单一事实来源。kind: "parallel"/"divergence" 会被用户硬约束抑制。
# 顺序即优先级（越靠前越「贴着动作」）。rx 只匹配本轮用户消息。
RULES: list = [
    {"id": "push_gate", "kind": "verify",
     "rx": r"(push|推送|提交|合并|开 ?PR|提 ?PR)",
     "skill": "review-gate",
     "action": "有仓库 + 行为变更时，push 前必须过一次独立只读 Review。"},
    {"id": "pretend_done", "kind": "verify",
     "rx": r"(做完了|完成了|已修好|收尾|收工|搞定|都改好了|没问题了)",
     "skill": "pre-commit-verification",
     "action": "声称完成前核对证据强度是否与风险相称（要实测输出，不是「应该没问题」）。"},
    {"id": "fanout_explicit", "kind": "parallel",
     "rx": r"(并行|分几个|拆给|多产物|多个文件|多个模块|子代理|subagent|fan[- ]?out)",
     "skill": "subagent-fanout-delivery",
     "action": "先读 R1/R2/R3 重叠分级与任务卡必写项，再派发。"},
    {"id": "readonly_survey", "kind": "parallel",
     "rx": r"(清点|勘察|调查|盘点|比对|审计|检索|逐个查|找出所有|全量看|扫一遍)",
     "skill": "subagent-fanout-delivery",
     "action": "按《只读取证类 fan-out》判断：≥3 个可独立只读工作包即默认分片并行（各写不同产物文件）。"},
    {"id": "open_ended", "kind": "divergence", "min_msgs": 8, "min_len": 16,
     "rx": r"(优化|提升|改进|设计|找机制|找上限|怎么才能|如何提高|探索|能不能更好)",
     "skill": "using-superpowers",
     "action": "按《一次并行判断》C 档（命中 ≥3 条即默认进入）先预注册判据；多轮发散见 "
               "subagent-fanout-delivery/references/iterative-research.md。"},
    {"id": "plan_needed", "kind": "plan",
     "rx": r"(迁移|部署|权限|跨会话|共享契约|高风险|重构)",
     "skill": "plan",
     "action": "先用 plan 把方案收敛成计划文件，再动手。"},
    {"id": "handover", "kind": "handover",
     "rx": r"(交接|交给下一个|换会话|新会话继续|进展交底)",
     "skill": "agent-handover-prompts",
     "action": "按「任务卡 / 进展交底」两形态之一写交接文档。"},
]

# 用户下了硬约束 ⇒ 只抑制「并行 / 发散」两类（验证与 push 门禁不抑制）
SUPPRESS_RX = re.compile(r"(只评审|不要执行|不要动|只读审查|只改这一处|先别动手|别改|不要开始)")
SUPPRESSED_KINDS = {"parallel", "divergence"}


def _text(value) -> str:
    """user_message 可能是 str / list（多模态）/ dict：安全降级成字符串。"""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(_text(v) for v in value)
    if isinstance(value, dict):
        return " ".join(_text(v) for v in value.values())
    return "" if value is None else str(value)


def _passes_size_gate(rule: dict, n_history: int, msg_len: int) -> bool:
    """体积门槛是 **OR** 语义：满足任一即放行。

    为什么必须是 OR：发散类若只按对话长度设门（n≥8），最该被提醒的形态恰恰被挡住 ——
    「用户在一个新会话的第一句就提出开放目标」（此时 n=0）。反之若只看消息长度，
    长会话里的一句「继续优化」又会被漏掉。两个都设 ⇒「问题已成形」或「会话已聊开」。
    """
    min_len = int(rule.get("min_len", 0))
    min_msgs = int(rule.get("min_msgs", 0))
    if not min_len and not min_msgs:
        return True
    return msg_len >= min_len or n_history >= min_msgs


def extract_payload(payload):
    """从 hook payload 取 (user_message, n_history, parent_session_id)。

    实测坑（本脚本第一版踩过）：Hermes 把 `parent_session_id` 提升为**顶层** payload 键
    （`agent/shell_hooks.py` 的 `_TOP_LEVEL_PAYLOAD_KEYS = {tool_name, args, session_id, parent_session_id}`），
    只读 `extra` 会拿到空串 ⇒ 子代理回合的静默判据失效（实测：探针会话派出的子会话也被写了注入记录）。
    两处都读，顶层优先；`extra` 内的同名字段作为兼容。
    """
    payload = payload if isinstance(payload, dict) else {}
    extra = payload.get("extra")
    extra = extra if isinstance(extra, dict) else {}
    parent = payload.get("parent_session_id") or extra.get("parent_session_id") or ""
    history = extra.get("conversation_history") or []
    try:
        n = len(history)
    except Exception:                                        # noqa: BLE001
        n = 0
    return extra.get("user_message"), n, str(parent)


def decide(user_message, n_history: int, parent_session_id: str, state: dict):
    """纯函数：返回 (命中的规则 dict 或 None, 新 state)。不读不写文件。

    状态文件是**外部输入**（可能被手改、被旧版本写过、将来字段改型），所以这里的取值一律
    防御性处理：坏值等价于「没有历史注入记录」，绝不把异常抛给调用方。
    """
    state = state if isinstance(state, dict) else {}
    raw_last = state.get("last")
    last = dict(raw_last) if isinstance(raw_last, dict) else {}
    if parent_session_id:
        return None, {}                                      # 子代理回合：静默
    msg = _text(user_message)
    if not msg.strip():
        return None, {"last": last}
    suppressed = bool(SUPPRESS_RX.search(msg))
    try:
        n = int(n_history)
    except Exception:                                        # noqa: BLE001
        n = 0
    for rule in RULES:
        if rule.get("kind") in SUPPRESSED_KINDS and suppressed:
            continue
        if not _passes_size_gate(rule, n, len(msg.strip())):
            continue
        if not re.search(rule["rx"], msg):
            continue
        try:
            prev = int(last.get(rule["skill"], -(10 ** 9)))
        except Exception:                                    # noqa: BLE001
            prev = -(10 ** 9)                                # 坏值 ⇒ 当没有历史注入
        if n - prev < COOLDOWN_MSGS:
            continue                                         # 冷却内：不重复
        last[rule["skill"]] = n
        return rule, {"last": last}
    return None, {"last": last}


def render(rule: dict) -> str:
    return f"[工作流触发·{rule['id']}] 先读技能 {rule['skill']}：{rule['action']}"


def hermes_home() -> pathlib.Path:
    env = os.environ.get("HERMES_HOME")
    return pathlib.Path(env) if env else pathlib.Path.home() / ".hermes"


def emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.write("\n")


def load_state(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return {}


def save_state(path: pathlib.Path, state: dict, n: int) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"n": n, "last": state.get("last") or {}, "ts": round(time.time())}),
                        encoding="utf-8")
    except Exception:                                        # noqa: BLE001
        pass                                                 # 写不进去只是丢可观测性，绝不抛


def selftest() -> int:
    """内联自测：纯函数 decide() 的表驱动用例（不写状态文件、不读 stdin）。"""
    cases = [
        # (用户消息, 历史条数, 期望技能 或 None, 说明)
        ("把这三个目录的资料分别清点一遍", 10, "subagent-fanout-delivery", "只读批量 ⇒ B 档"),
        ("这个模块要并行拆给几个子代理做", 6, "subagent-fanout-delivery", "显式并行"),
        ("帮我优化一下这个算法的吞吐，现在 12 fps", 20, "using-superpowers", "开放目标 + 会话够长 ⇒ C 档"),
        ("帮我优化一下这个算法的吞吐，现在 12 fps", 0, "using-superpowers", "**首轮**长句也注入（会话短但问题成形）"),
        ("继续优化", 20, "using-superpowers", "会话已长 ⇒ 短消息也注入"),
        ("帮我优化一下吞吐", 2, None, "短消息 + 会话短 ⇒ 两边都不满足，不注入"),
        ("我把改动都改好了", 12, "pre-commit-verification", "声明完成"),
        ("准备 push 到 main", 14, "review-gate", "push 门禁"),
        ("先给我一份迁移方案，别动手", 14, "plan", "plan 类不受抑制词影响"),
        ("只评审，不要执行；顺便看看能不能并行", 14, None, "抑制词 ⇒ parallel 类不注入"),
        ("帮我写个交接文档", 9, "agent-handover-prompts", "交接"),
        ("今天天气怎么样", 9, None, "零命中 ⇒ 不注入"),
    ]
    bad = 0
    for msg, n, want, note in cases:
        got, _st = decide(msg, n, parent_session_id="", state={})
        got_sk = got["skill"] if got else None
        ok = got_sk == want
        bad += 0 if ok else 1
        print(("  PASS " if ok else "  FAIL "), f"want={want!s:<32} got={got_sk!s:<32} {note}")
        if not ok:
            print(f"        消息: {msg!r} n={n}")

    st = {}
    _r1, st = decide("准备 push 到 main", 14, parent_session_id="", state=st)
    r2, st = decide("准备 push 到 main", 14 + COOLDOWN_MSGS - 1, parent_session_id="", state=st)
    r3, _st2 = decide("准备 push 到 main", 14 + COOLDOWN_MSGS, parent_session_id="", state=st)
    for label, r, want in (("冷却内不重复", r2, None), ("冷却后恢复", r3, "review-gate")):
        ok = (r["skill"] if r else None) == want
        bad += 0 if ok else 1
        print(("  PASS " if ok else "  FAIL "), f"{label}: want={want}")

    r, _st3 = decide("准备 push 到 main", 30, parent_session_id="parent-xyz", state={})
    ok = r is None
    bad += 0 if ok else 1
    print(("  PASS " if ok else "  FAIL "), "子代理回合静默")

    for weird in (None, "", ["列表", "消息"], {"a": 1}, 12):
        try:
            decide(weird, 5, parent_session_id="", state={})
        except Exception as exc:                             # noqa: BLE001
            bad += 1
            print("  FAIL  异常输入抛错:", repr(weird), exc)

    # 坏 state 不得抛：脚本的自我约束是「任何异常吞掉、绝不影响回合」。
    # 状态文件可能被手改、被旧版本写过、或未来字段改型，main() 只按自己的状态文件写读，
    # 一旦这里抛出去，这次该注入的提醒会静默丢失（hook rc!=0）。
    for bad_state in ({"last": [1, 2]}, {"last": {"review-gate": "oops"}}, {"last": None}, "not-a-dict"):
        try:
            r, _st = decide("准备 push 到 main", 14, parent_session_id="", state=bad_state)
            ok = r is not None                               # 坏值 ⇒ 当作「没有历史注入」，照常命中
        except Exception as exc:                             # noqa: BLE001
            ok = False
            print("        坏 state 抛错:", type(exc).__name__, exc)
        bad += 0 if ok else 1
        print(("  PASS " if ok else "  FAIL "), f"坏 state 不抛 {bad_state!r}")

    # 已知限制固定：payload 不带 conversation_history 时 n 恒为 0，冷却判据退化。
    # 退化后的行为是「同一技能本会话只注入一次」——这是可接受的下限，故用用例钉死，
    # 避免将来被无声改成「每轮都注入」。
    _st = {}
    r1, _st = decide("准备 push 到 main", 0, parent_session_id="", state=_st)
    r2, _st = decide("准备 push 到 main", 0, parent_session_id="", state=_st)
    ok = r1 is not None and r2 is None
    bad += 0 if ok else 1
    print(("  PASS " if ok else "  FAIL "), "history 缺失(n=0)：本会话只注入一次（已知限制，钉死）")

    # 载荷级接线（曾出错的地方）：Hermes 把 `parent_session_id` **提升为顶层 payload 键**
    # （agent/shell_hooks.py 的 _TOP_LEVEL_PAYLOAD_KEYS），只读 extra 会让子代理回合静默失效。
    # 纯函数级用例测的是 decide() 的入参，测不到这段接线 —— 所以这里必须喂**真实形状的 payload**。
    base_extra = {"user_message": "准备 push 到 main", "conversation_history": [{}] * 9}
    payload_cases = [
        ("顶层 parent_session_id ⇒ 静默",
         {"parent_session_id": "p-1", "extra": dict(base_extra, parent_session_id="")}, True),
        ("extra 内 parent_session_id（兼容）⇒ 静默",
         {"extra": dict(base_extra, parent_session_id="p-2")}, True),
        ("主会话（两处都无）⇒ 不静默", {"extra": dict(base_extra)}, False),
    ]
    for label, payload, want_silent in payload_cases:
        try:
            msg, n, parent = extract_payload(payload)
            rule, _st = decide(msg, n, parent, {})
            ok = (rule is None) == want_silent
        except Exception as exc:                             # noqa: BLE001
            ok = False
            print("        载荷级提取抛错:", type(exc).__name__, exc)
        bad += 0 if ok else 1
        print(("  PASS " if ok else "  FAIL "), label)

    print("selftest:", "OK" if bad == 0 else f"{bad} 项失败")
    return 0 if bad == 0 else 1


def main(argv) -> int:
    if "--selftest" in argv:
        return selftest()
    if "--explain" in argv:
        i = argv.index("--explain")
        txt = argv[i + 1] if len(argv) > i + 1 else ""
        rule, _st = decide(txt, 20, parent_session_id="", state={})
        print(render(rule) if rule else "(不注入)")
        return 0

    # 兜底：这是**每轮都跑**的 hook，任何异常都必须退化成「不注入」，而不是抛出去让进程 rc!=0
    # （rc!=0 会让宿主记 warning，并让本该注入的那一行静默丢失）。
    try:
        payload = json.load(sys.stdin)
        if str(payload.get("hook_event_name") or "") != "pre_llm_call":
            emit({})                                         # 防御：别的 payload 一律静默
            return 0
        msg, n, parent = extract_payload(payload)
        sid = str(payload.get("session_id") or "unknown")
        state_path = hermes_home() / STATE_DIRNAME / f"{sid}.json"
        state = load_state(state_path)
        rule, new_state = decide(msg, n, parent, state)
        save_state(state_path, new_state, n)                 # 每轮写心跳（可观测，不注入）
        emit({"context": render(rule)} if rule else {})
    except Exception:                                        # noqa: BLE001
        emit({})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
