#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能触达 / 并行 / 成本 / 发散的只读审计（ROADMAP G18 的度量口径）。

用法：
  python scripts/audit_trigger.py --days 14
  python scripts/audit_trigger.py --days 14 --json      # 机器可读，存基线用

口径（写进报告时必须原样交代）：
  * 只读打开 state.db（uri mode=ro），绝不写。
  * **权威口径（调用数）= assistant 行的 `tool_calls` 条目数**。取证（2026-09-16，全库快照；数值随库增长漂移，形态不变）：
    * 全库 0 行同时带 `tool_name` 与 `tool_calls`；`role='tool'` 的结果行带 `tool_name`，`role='assistant'` 带 JSON。
    * `skill_view` / `delegate_task` 两族的**结果行数与 JSON 条目逐会话完全相等**（快照 809/809、417/417，0 例不符）
      ⇒ 这两族的两边相加会整整翻倍（本脚本第一版就这么错过一次）。
    * **但这不能推广到全库**：快照整体 JSON 条目 46,510 vs 结果行 46,472（(会话, 工具) 组合 262/3407 不相等），
      另有 840 条 JSON 条目以通用名 `tool_call` 记录（其真名在结果行里，如 computer_use / process_manage）。
      ⇒ **结果行只用于返回体统计（`skill_body_stats` / `skill_body_breakdown`），不参与调用数**。
    * `sessions.tool_call_count` 与 JSON 条目在快照 41/706 个会话上不一致（最极端 125 vs 1610）⇒ **两套口径不可混用**，报告里必须分开写。
  * 「>10k 返回体按技能分解」用 `skill_body_breakdown()`：归属靠 tool 结果行的 `tool_call_id` 与 assistant 行里每个
    tool_call 的 `id` 配对。**不要用「相邻上一条 assistant 行的第 k 个」猜**——一行 assistant 可含多个 tool_calls，
    猜法会把技能归错（本仓就错过一次：把 `subagent-fanout-delivery` 记成 4 条，实为 0 条）。
  * 窗口 = now - days*86400，UTC 秒语义。
  * 会话数含子会话；父会话 = parent_session_id is null。
  * 墙钟（ended_at-started_at）在挂载/等待型会话里会失真，本脚本不输出它当「时长」。
  * 成本口径：estimated_cost_usd 是整会话累计，不是批次增量。
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import sqlite3
import statistics
import sys

GRIMOIRE = [
    "review-gate", "using-superpowers", "agent-handover-prompts", "subagent-fanout-delivery",
    "pre-commit-verification", "plan", "spike", "finishing-a-development-branch",
    "long-running-progress-monitoring", "test-driven-development", "conversation-progress-report",
]


def db_path() -> str:
    return os.environ.get("HERMES_STATE_DB") or os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "hermes", "state.db")


def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)   # 只读，绝不可写
    con.row_factory = sqlite3.Row
    return con


def iter_calls(con, since):
    """yield (session_id, tool_name, args_dict|None) —— **权威口径：assistant 行的 tool_calls 条目**。

    实测（全库 666 会话）：
      * 一个逻辑调用在库里是两行：assistant 行带 `tool_calls` JSON、tool 结果行带 `tool_name`；
        全库 **0 行**同时带两者（both=0）。两边都数会整整翻倍。
      * `sessions.tool_call_count` 与 JSON 条目数逐会话一致（5/5 抽样；有一例 55 vs 56 是结果行缺失）。
    ⇒ 只数 JSON 条目；结果行只用于返回体统计（`skill_body_stats`）。
    自检见 `json_coverage()`：若有会话只有结果行、没有 JSON 调用，会在这里被点数出来（不静默漏数）。
    """
    q = ("select session_id, tool_calls from messages "
         "where timestamp >= ? and role = 'assistant' and tool_calls is not null")
    for r in con.execute(q, (since,)):
        try:
            arr = json.loads(r["tool_calls"])
        except Exception:                                    # noqa: BLE001
            continue
        if not isinstance(arr, list):
            continue
        for c in arr:
            if not isinstance(c, dict):
                continue
            fn = (c.get("function") or {}).get("name") or c.get("name")
            if not fn:
                continue
            args = (c.get("function") or {}).get("arguments") or c.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:                            # noqa: BLE001
                    args = None
            yield r["session_id"], fn, (args if isinstance(args, dict) else None)


def json_coverage(con, since) -> dict:
    """口径自检：调用记录（JSON）与结果行（tool_name）的会话覆盖是否一致。"""
    a = con.execute("select count(distinct session_id) from messages "
                    "where timestamp >= ? and role = 'tool' and tool_name is not null",
                    (since,)).fetchone()[0]
    b = con.execute("select count(distinct session_id) from messages "
                    "where timestamp >= ? and role = 'assistant' and tool_calls is not null",
                    (since,)).fetchone()[0]
    miss = con.execute(
        "select count(*) from ("
        "  select distinct session_id from messages where timestamp >= ? and role='tool' and tool_name is not null"
        "  except"
        "  select distinct session_id from messages where timestamp >= ? and role='assistant' and tool_calls is not null"
        ")", (since, since)).fetchone()[0]
    return {"sessions_with_tool_rows": a, "sessions_with_json_calls": b, "sessions_missing_json": miss}


def skill_hits(con, since) -> collections.Counter:
    """技能名 -> 被 skill_view 读入的次数。"""
    out = collections.Counter()
    for _sid, name, args in iter_calls(con, since):
        if name != "skill_view" or not args:
            continue
        nm = args.get("name")
        if nm:
            out[nm] += 1
    return out


def parallel_stats(con, since) -> dict:
    per_session = collections.Counter()
    for sid, name, _a in iter_calls(con, since):
        if name == "delegate_task":
            per_session[sid] += 1
    vals = sorted(per_session.values())
    return {
        "calls": sum(vals),
        "sessions_with_parallel": len(per_session),
        "median_per_session": statistics.median(vals) if vals else 0,
        "dist_1": sum(1 for v in vals if v == 1),
        "dist_2": sum(1 for v in vals if v == 2),
        "dist_3_5": sum(1 for v in vals if 3 <= v <= 5),
        "dist_6p": sum(1 for v in vals if v >= 6),
    }


def sessions_summary(con, since) -> dict:
    rows = con.execute(
        "select id,parent_session_id,input_tokens,output_tokens,cache_read_tokens,"
        "tool_call_count,estimated_cost_usd from sessions where started_at >= ?", (since,)).fetchall()
    parents = [r for r in rows if not r["parent_session_id"]]
    med = (lambda xs: statistics.median(xs) if xs else 0)
    return {
        "sessions": len(rows),
        "parents": len(parents),
        "total_input": sum((r["input_tokens"] or 0) for r in rows),
        "total_cache_read": sum((r["cache_read_tokens"] or 0) for r in rows),
        "median_input_parent": med([(r["input_tokens"] or 0) for r in parents]),
        "median_cache_read_parent": med([(r["cache_read_tokens"] or 0) for r in parents]),
        "median_tool_calls_parent": med([(r["tool_call_count"] or 0) for r in parents]),
    }


def skill_body_stats(con, since) -> dict:
    """skill_view 返回体（消息 content = 技能正文）体量统计。"""
    lens = []
    for r in con.execute("select content from messages where timestamp >= ? and tool_name = 'skill_view'",
                         (since,)):
        lens.append(len(r["content"] or ""))
    return {
        "n": len(lens),
        "total_chars": sum(lens),
        "median_chars": statistics.median(lens) if lens else 0,
        "max_chars": max(lens) if lens else 0,
        "over_10k": sum(1 for x in lens if x > 10000),
    }


def skill_body_breakdown(con, since, threshold: int = 10000) -> dict:
    """按技能统计「返回体 > threshold 字符」的读取次数。

    **归属必须用 `tool_call_id` 配对**（tool 结果行的 `tool_call_id` ↔ assistant 行里每个 tool_call 的 `id`）：
    一行 assistant 可能含**多个** tool_calls（同一轮并发多读），按「相邻上一条 assistant 行的第 k 个」猜
    会把技能归错——本仓人工归名时就错过（把 subagent-fanout-delivery 记成 4 条，实为 0 条）。
    无配对 id 的结果行直接丢弃（不猜），宁少不多。
    """
    names = {}
    for r in con.execute("select tool_calls from messages "
                         "where role='assistant' and tool_calls is not null"):
        try:
            arr = json.loads(r["tool_calls"])
        except Exception:                                    # noqa: BLE001
            continue
        if not isinstance(arr, list):
            continue
        for c in arr:
            if not isinstance(c, dict):
                continue
            f = c.get("function") or {}
            if f.get("name") != "skill_view":
                continue
            cid = c.get("id")
            args = f.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:                            # noqa: BLE001
                    args = None
            nm = args.get("name") if isinstance(args, dict) else None
            if cid and nm:
                names[cid] = nm
    out = collections.Counter()
    for r in con.execute("select tool_call_id, length(content) as L from messages "
                         "where timestamp >= ? and tool_name = 'skill_view'", (since,)):
        if (r["L"] or 0) <= threshold:
            continue
        nm = names.get(r["tool_call_id"])
        if nm:
            out[nm] += 1
    return dict(out)


def tool_output_bytes(con, since) -> collections.Counter:
    out = collections.Counter()
    for r in con.execute("select tool_name, content from messages where timestamp >= ? and tool_name is not null",
                         (since,)):
        out[r["tool_name"]] += len(r["content"] or "")
    return out


def report(con, since, days) -> dict:
    hits = skill_hits(con, since)
    par = parallel_stats(con, since)
    ses = sessions_summary(con, since)
    body = skill_body_stats(con, since)
    outb = tool_output_bytes(con, since)
    tot_out = sum(outb.values()) or 1
    readers = con.execute(
        "select count(distinct session_id) from messages where timestamp >= ? and tool_name = 'skill_view'",
        (since,)).fetchone()[0]
    return {
        "window_days": days,
        "since_utc": datetime.datetime.utcfromtimestamp(since).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "M0_caliber_selfcheck": json_coverage(con, since),
        "M1_targets": {
            "sessions": ses["sessions"],
            "parent_sessions": ses["parents"],
            "sessions_with_any_skill_read": readers,
            "grimoire_reads_total": sum(hits.get(k, 0) for k in GRIMOIRE),
            "per_skill": {k: hits.get(k, 0) for k in GRIMOIRE},
            "all_skill_reads": sum(hits.values()),
        },
        "M2_parallel": par,
        "M3_cost": {
            "median_input_parent": ses["median_input_parent"],
            "median_cache_read_parent": ses["median_cache_read_parent"],
            "median_tool_calls_parent": ses["median_tool_calls_parent"],
            "total_input": ses["total_input"],
            "total_cache_read": ses["total_cache_read"],
            "skill_view_body": {**body, "over_10k_by_skill": skill_body_breakdown(con, since),
                                "over_10k_grimoire": sum(
                                    v for k, v in skill_body_breakdown(con, since).items()
                                    if k in GRIMOIRE)},
            "tool_output_share": {k: round(100.0 * v / tot_out, 2) for k, v in outb.most_common(8)},
        },
        "M4_divergence": {
            "router_reads": hits.get("using-superpowers", 0),
            "fanout_reads": hits.get("subagent-fanout-delivery", 0),
        },
    }


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--db", default=None)
    a = ap.parse_args(argv)
    path = a.db or db_path()
    if not os.path.exists(path):
        sys.exit(f"state.db not found: {path} (set HERMES_STATE_DB)")
    since = datetime.datetime.now().timestamp() - a.days * 86400
    res = report(connect(path), since, a.days)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    m1, m2, c = res["M1_targets"], res["M2_parallel"], res["M3_cost"]
    m0 = res["M0_caliber_selfcheck"]
    print(f"窗口 {res['window_days']} 天，自 {res['since_utc']}")
    print(f"M0 口径自检：有结果行的会话 {m0['sessions_with_tool_rows']}；有 JSON 调用的会话 "
          f"{m0['sessions_with_json_calls']}；只有结果行、没有 JSON 调用的会话 "
          f"{m0['sessions_missing_json']}（>0 说明本口径会漏数）")
    print(f"M1 触达：会话 {m1['sessions']}（父 {m1['parent_sessions']}）；"
          f"读过任意技能的会话 {m1['sessions_with_any_skill_read']}；"
          f"grimoire 被读 {m1['grimoire_reads_total']} 次 / 全部技能 {m1['all_skill_reads']} 次")
    for k in GRIMOIRE:
        print(f"     {m1['per_skill'][k]:4d}  {k}")
    print(f"M2 并行：delegate_task {m2['calls']} 次，覆盖 {m2['sessions_with_parallel']} 个会话"
          f"（1次={m2['dist_1']} 2次={m2['dist_2']} 3-5次={m2['dist_3_5']} 6+={m2['dist_6p']}）")
    print(f"M3 成本：父会话中位 工具调用 {c['median_tool_calls_parent']} / 输入 {c['median_input_parent']:,.0f} / "
          f"缓存读 {c['median_cache_read_parent']:,.0f}")
    b = c["skill_view_body"]
    print(f"     skill_view 返回体 {b['n']} 次，中位 {b['median_chars']:,.0f} 字符，"
          f"最大 {b['max_chars']:,}，>10k 字符 {b['over_10k']} 次"
          f"（其中本仓技能 {b.get('over_10k_grimoire', 0)} 次；按技能：{b.get('over_10k_by_skill', {})}）")
    print(f"     工具输出份额：{c['tool_output_share']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
