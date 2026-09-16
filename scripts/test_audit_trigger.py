#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_trigger.py 的单元测试。用内存 SQLite 夹具，不读真库、不碰 HERMES_HOME。

**口径是这份测试的重点**：真库里一个逻辑调用是**两行** ——
  assistant 行带 `tool_calls` JSON（调用本身），tool 结果行带 `tool_name`（执行结果）。
实测全库 0 行同时带两者；`sessions.tool_call_count` 与 JSON 条目数逐会话一致（5/5 抽样）。
⇒ 权威口径 = assistant 行的 JSON 条目数；把结果行也算成调用会整整翻倍。
"""
import importlib.util
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("audit_trigger", os.path.join(HERE, "audit_trigger.py"))
at = importlib.util.module_from_spec(spec)
spec.loader.exec_module(at)

SCHEMA = """
create table sessions (id text primary key, parent_session_id text, started_at real,
  ended_at real, message_count int, tool_call_count int, input_tokens int, output_tokens int,
  cache_read_tokens int, reasoning_tokens int, estimated_cost_usd real, model text, title text);
create table messages (id integer primary key autoincrement, session_id text, role text,
  tool_name text, tool_calls text, content text, timestamp real);
"""


def _calls(*specs):
    """构造 tool_calls JSON：('skill_view', {'name':'review-gate'}) 形式。"""
    return json.dumps([{"id": f"c{i}", "function": {"name": n, "arguments": json.dumps(a)}}
                       for i, (n, a) in enumerate(specs)])


def mkdb():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.execute("insert into sessions values ('p1',null,1000,2000,10,3,10,20,30,0,0,'m','t')")
    con.execute("insert into sessions values ('c1','p1',1001,1100, 3,1, 1, 2, 3,0,0,'m','child')")

    # p1：两次调用，各自的 assistant 行（JSON）+ tool 结果行
    con.execute("insert into messages (session_id,role,tool_name,tool_calls,content,timestamp) values "
                "('p1','assistant',null,?,'',1001)",
                (_calls(("skill_view", {"name": "review-gate"})),))
    con.execute("insert into messages (session_id,role,tool_name,content,timestamp) values "
                "('p1','tool','skill_view',?,1001)", ("z" * 500,))          # 结果行，不是调用
    con.execute("insert into messages (session_id,role,tool_name,tool_calls,content,timestamp) values "
                "('p1','assistant',null,?,'',1002)", (_calls(("delegate_task", {})),))
    con.execute("insert into messages (session_id,role,tool_name,content,timestamp) values "
                "('p1','tool','delegate_task',?,1002)", ("y" * 20,))        # 结果行，不是调用
    # c1（子会话）：一次调用
    con.execute("insert into messages (session_id,role,tool_name,tool_calls,content,timestamp) values "
                "('c1','assistant',null,?,'',1002)", (_calls(("delegate_task", {})),))
    con.execute("insert into messages (session_id,role,tool_name,content,timestamp) values "
                "('c1','tool','delegate_task',?,1002)", ("y" * 20,))
    return con


def test_calls_no_double_count():
    """3 次调用就是 3 次：结果行不得被当成调用（否则 5 次）。"""
    con = mkdb()
    calls = list(at.iter_calls(con, since=0))
    assert len(calls) == 3, calls
    assert sum(1 for c in calls if c[1] == "skill_view") == 1, calls
    dts = [c for c in calls if c[1] == "delegate_task"]
    assert len(dts) == 2 and {c[0] for c in dts} == {"p1", "c1"}, dts


def test_skill_name_from_tool_calls():
    con = mkdb()
    hits = at.skill_hits(con, since=0)
    assert hits["review-gate"] == 1, hits


def test_parent_dedup_totals():
    con = mkdb()
    t = at.sessions_summary(con, since=0)
    assert t["sessions"] == 2 and t["parents"] == 1, t


def test_body_stats_count_tool_rows():
    """返回体统计走 tool 结果行：1 条 skill_view 结果、500 字符。"""
    con = mkdb()
    st = at.skill_body_stats(con, since=0)
    assert st["n"] == 1 and st["max_chars"] == 500, st


def test_json_coverage_flags_missing_json_sessions():
    """口径自检：有结果行但没有任何 JSON 调用的会话必须被点数出来（否则会静默漏数）。"""
    con = mkdb()
    cov = at.json_coverage(con, since=0)
    assert cov["sessions_with_tool_rows"] == 2 and cov["sessions_with_json_calls"] == 2, cov
    assert cov["sessions_missing_json"] == 0, cov
    con.execute("insert into messages (session_id,role,tool_name,content,timestamp) values "
                "('p9','tool','terminal','x',1005)")                       # 只有结果行
    cov2 = at.json_coverage(con, since=0)
    assert cov2["sessions_missing_json"] == 1, cov2


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok", name)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print("FAIL", name, "->", exc)
    print("全部通过" if not failed else f"{failed} 项失败")
    raise SystemExit(1 if failed else 0)
