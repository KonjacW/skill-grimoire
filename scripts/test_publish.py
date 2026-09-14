#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish.py 的标准库测试（第一套）。

怎么跑（在仓库根执行）：
    python scripts/test_publish.py -v
    python -m unittest discover -s scripts -p "test_*.py"

设计：
- 只用标准库（unittest/tempfile/pathlib/os/shutil）；不改 publish.py。
- 每个测试自带一套临时环境：假仓库（REPO）+ 假 live 技能树（SOURCES）+ 临时私有脱敏表
  （LOCAL_REDACT），全部通过 monkeypatch 注入、addCleanup 恢复，结束后临时目录被删。
- 本仓门禁会拦「盘符 + Users 形式的绝对路径」「某个宿主专有工具名」「宿主目录路径形式」等字面量，
  因此测试里需要的这类字符串一律用拼接构造（见下面 _DRIVE/_BS/_USERS/_HOST_NS_LINE），不写字面量。
- 断言一律指向真实行为（函数返回值 / 打印出的门禁结论 / 磁盘字节），不碰实现细节。
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUBLISH_PATH = HERE / "publish.py"

# —— 门禁敏感串：拼接构造，不写字面量 ——
_DRIVE = "C" + ":"
_DRIVE2 = chr(68) + ":"                 # 另一个盘符：不被 HOME 推导的替换台阶覆盖，用于 fail-closed 断言
_BS = chr(92)
_USERS = "Users"
_KON = "KonjacW"
_PORTABLE = "~/.codex/skills/active"
# REPLACEMENTS 里的路径台阶：4 个反斜杠 / 2 个反斜杠 / 正斜杠（见 publish.REPLACEMENTS 前三对）
_PATH_4BS = (_DRIVE + _BS * 4 + _USERS + _BS * 4 + _KON + _BS * 4 + ".codex"
             + _BS * 4 + "skills" + _BS * 4 + "active")
_PATH_2BS = (_DRIVE + _BS * 2 + _USERS + _BS * 2 + _KON + _BS * 2 + ".codex"
             + _BS * 2 + "skills" + _BS * 2 + "active")
_PATH_FS = _DRIVE + "/" + _USERS + "/" + _KON + "/.codex/skills/active"
_PATH_1BS = _DRIVE + _BS + _USERS + _BS + _KON + _BS + ".codex" + _BS + "skills" + _BS + "active"
_HOST_NS_LINE = "  " + "her" + "mes" + ":"      # metadata 下的宿主命名空间键（发布时会改名）


def _load_publish():
    """按路径重新加载被测模块，让每个测试都拿到一份干净模块状态。"""
    spec = importlib.util.spec_from_file_location("sg_publish_under_test", PUBLISH_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Base(unittest.TestCase):
    SKILLS = ("alpha", "beta")

    def setUp(self):
        self.pub = _load_publish()
        self.root = tempfile.mkdtemp(prefix="sg-publish-test-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.repo = os.path.join(self.root, "repo")
        self.live = os.path.join(self.root, "live")
        self.table_path = os.path.join(self.root, "redact-patterns.local.json")
        self.set_const("REPO", self.repo)
        self.set_const("LOCAL_REDACT", self.table_path)
        # 仓根 scripts/（放着被 .gitignore 忽略的私有表）与 .git/ 属于必须跳过的那一层
        self.write(os.path.join(self.repo, "scripts", "publish.py"), "# 占位脚本\n")
        self.use_table()
        self.build()

    # —— 基建 ——
    def set_const(self, name, value):
        old = getattr(self.pub, name)
        setattr(self.pub, name, value)
        self.addCleanup(setattr, self.pub, name, old)

    def write(self, path, text):
        self.write_bytes(path, text.encode("utf-8"))

    def write_bytes(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)

    def read_bytes(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def skill_text(self, name, body="正文示例。\n"):
        return ("---\n"
                f"description: {name} 测试技能\n"
                "related_skills: []\n"
                "---\n\n"
                f"# {name}\n\n{body}")

    def readme_text(self, skills, rows=None, declared=None, omit_decl=False):
        rows = len(skills) if rows is None else rows
        declared = len(skills) if declared is None else declared
        cn = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}[declared]
        row_txt = "\n".join(
            f"| `{skills[i] if i < len(skills) else 'ghost%d' % i}` | 说明 {i} |" for i in range(rows))
        head = "" if omit_decl else f"本包共{cn}个技能。\n\n"
        return (f"# 假仓库\n\n{head}## 技能一览\n\n| 技能 | 说明 |\n|---|---|\n{row_txt}\n\n## 安装\n\n略。\n")

    def roadmap_text(self, n, omit=False):
        if omit:
            return "**最后核对**：2026-01-01。\n"
        return f"**最后核对**：2026-01-01（包内 {n} 个技能）。\n"

    def default_table(self):
        return {
            "私人项目名": [r"NEVER_PROJECT_[0-9]{3}"],
            "私人路径": [r"NEVERPATH_[0-9]{3}"],
            "实名": [r"NEVER_REALNAME"],
            "服务器凭据": [r"NEVER_TOKEN_[0-9a-f]{4}"],
            "line_rules": [["active/alpha/SKILL.md", "NEVER_MATCH_ZZZ", "常量文本"]],
            "path_replacements": [["PRIVATE_VAULT_DIR", "<OBSIDIAN_VAULT>"]],
        }

    def use_table(self, data=None, exists=True):
        if exists:
            with open(self.table_path, "w", encoding="utf-8") as fh:
                json.dump(data if data is not None else self.default_table(), fh, ensure_ascii=False)
        elif os.path.isfile(self.table_path):
            os.remove(self.table_path)
        self.pub._LINE_RULES_CACHE = None      # 私有表有模块级解析缓存，换表后必须失效

    def build(self, skills=None, nested_scripts=(), with_live=True):
        skills = tuple(self.SKILLS if skills is None else skills)
        self.set_const("SOURCES", {s: os.path.join(self.live, "active", s) for s in skills})
        for s in skills:
            text = self.skill_text(s)
            self.write(os.path.join(self.repo, "active", s, "SKILL.md"), text)
            if with_live:
                self.write(os.path.join(self.live, "active", s, "SKILL.md"), text)
            if s in nested_scripts:
                self.write(os.path.join(self.repo, "active", s, "scripts", "helper.py"), "# 技能自带脚本\n")
                if with_live:
                    self.write(os.path.join(self.live, "active", s, "scripts", "helper.py"), "# 技能自带脚本\n")
        self.write(os.path.join(self.repo, "README.md"), self.readme_text(skills))
        self.write(os.path.join(self.repo, "ROADMAP.md"), self.roadmap_text(len(skills)))
        return skills

    def write_live_body(self, name, body):
        self.write(os.path.join(self.live, "active", name, "SKILL.md"), self.skill_text(name, body))

    def run_check(self, with_live=True):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.pub.check(with_live=with_live)
        return rc, buf.getvalue()


class PublishGateTests(_Base):

    # —— T1：仓根第一层跳过，但 active/<技能>/scripts/** 必须被扫（G11 回归）——
    def test_T1_iter_text_files_skips_only_repo_root_dirs(self):
        self.build(nested_scripts=("alpha", "beta"))
        self.write(os.path.join(self.repo, ".git", "config.txt"), "private\n")
        self.write(os.path.join(self.repo, "scripts", "secret.md"), "private\n")
        got = sorted(os.path.relpath(p, self.repo).replace("\\", "/")
                     for p in self.pub.iter_text_files(self.pub.REPO))
        self.assertIn("active/alpha/scripts/helper.py", got)
        self.assertIn("active/beta/scripts/helper.py", got)
        self.assertIn("README.md", got)
        self.assertEqual([r for r in got if r.startswith("scripts/")], [], got)
        self.assertEqual([r for r in got if r.startswith(".git/")], [], got)

    # —— T2：CRLF 被 SCAN_GENERIC 报出；sync() 按字节归一成 LF ——
    def test_T2_crlf_flagged_and_sync_normalizes_by_bytes(self):
        self.build(nested_scripts=("alpha",))
        lf = self.skill_text("alpha")
        crlf = lf.replace("\n", "\r\n").encode("utf-8")
        self.write_bytes(os.path.join(self.repo, "active", "alpha", "SKILL.md"), crlf)
        rc, out = self.run_check(with_live=False)
        self.assertEqual(rc, 1, out)
        self.assertIn("CRLF 行尾 | active/alpha/SKILL.md:1", out)

        # sync() 侧：live 是 CRLF，落盘后必须按字节归一（含技能自带的深层 scripts/）
        self.write_bytes(os.path.join(self.live, "active", "alpha", "SKILL.md"), crlf)
        self.write_bytes(os.path.join(self.live, "active", "alpha", "scripts", "helper.py"),
                         b"print(1)\r\nprint(2)\r\n")
        self.pub.sync()
        raw = self.read_bytes(os.path.join(self.repo, "active", "alpha", "SKILL.md"))
        self.assertNotIn(b"\r\n", raw)
        self.assertEqual(raw, lf.encode("utf-8"))
        raw_py = self.read_bytes(os.path.join(self.repo, "active", "alpha", "scripts", "helper.py"))
        self.assertNotIn(b"\r\n", raw_py)
        self.assertEqual(raw_py, b"print(1)\nprint(2)\n")

    # —— T3：非法 frontmatter 键 + 宿主元数据键被报出；归一化侧删除/改名 ——
    def test_T3_frontmatter_illegal_keys_and_host_namespace(self):
        self.build()
        fm = ("---\n"
              "version: 1.0.0\n"
              "author: 某作者\n"
              "platforms: [windows]\n"
              "dependencies: []\n"
              "metadata:\n"
              f"{_HOST_NS_LINE}\n"
              "---\n\n# alpha\n\n正文。\n")
        self.write(os.path.join(self.repo, "active", "alpha", "SKILL.md"), fm)
        rc, out = self.run_check(with_live=False)
        self.assertEqual(rc, 1, out)
        self.assertIn("非法 frontmatter | active/alpha/SKILL.md:2", out)
        self.assertIn("非法 frontmatter | active/alpha/SKILL.md:5", out)
        self.assertIn("宿主元数据键 | active/alpha/SKILL.md:7", out)

        fixed, n = self.pub.normalize_frontmatter(fm)
        self.assertEqual(n, 5)
        for gone in ("version:", "author:", "platforms:", "dependencies:", _HOST_NS_LINE):
            self.assertNotIn(gone, fixed)
        self.assertIn("  agent:", fixed)

    # —— T4：同一含义的多种路径拼写都被归一成同一可移植形式；单反斜杠档走门禁兜底 ——
    def test_T4_path_spelling_variants_scrub_to_same_portable_form(self):
        # 四 / 双 / 单反斜杠 + 正斜杠四种写法都要归一成同一个可移植形式
        text = f"a {_PATH_4BS} b {_PATH_2BS} c {_PATH_FS} d {_PATH_1BS} e"
        out, n = self.pub.scrub(text)
        self.assertEqual(n, 4)
        self.assertEqual(out, f"a {_PORTABLE} b {_PORTABLE} c {_PORTABLE} d {_PORTABLE} e")

        # HOME 之外的同形态路径（换个盘符）不被替换台阶覆盖：scrub 原样放过……
        raw = f"见 {_DRIVE2}/" + _USERS + "/" + _KON + "/.codex/skills/active 目录"
        out2, n2 = self.pub.scrub(raw)
        self.assertEqual((n2, out2), (0, raw))
        # ……但通用扫描规则会拦下它（fail-closed，不是静默放行）
        self.write(os.path.join(self.repo, "active", "beta", "notes.md"), raw + "\n")
        rc, out3 = self.run_check(with_live=False)
        self.assertEqual(rc, 1, out3)
        self.assertIn("本机绝对路径 | active/beta/notes.md:1", out3)


    # —— T25/T26/T27：仓根 scripts/ 的泄露面自检（O6）——
    def test_T25_scripts_leak_self_check_true_positive(self):
        """scripts/ 下的脚本里出现本机绝对路径 → 必须报错（公开仓能一路发布就是漏了这条）。"""
        self.write(os.path.join(self.repo, "scripts", "helper.py"),
                   "P = " + repr(_PATH_FS) + "\n")
        msg = " | ".join(self.pub.check_scripts_leak())
        self.assertIn("本机绝对路径", msg)
        self.assertIn("scripts/helper.py:1", msg)
        rc, out = self.run_check(with_live=False)
        self.assertEqual(rc, 1, out)
        self.assertIn("本机绝对路径 | scripts/helper.py:1", out)

    def test_T26_scripts_private_table_is_exempt_but_shape_matters(self):
        """私有脱敏表（*.local.json）豁免——它按设计装着私人词表；同目录其它文件不豁免。"""
        self.write(os.path.join(self.repo, "scripts", "redact-patterns.local.json"),
                   json.dumps({"私人路径": [_PATH_FS]}, ensure_ascii=False) + "\n")
        self.assertEqual(self.pub.check_scripts_leak(), [])
        # 同目录、换个扩展名的同一内容仍然会被扫到（豁免按表名/表本身，不是按目录整片跳过）
        self.write(os.path.join(self.repo, "scripts", "notes.md"), _PATH_FS + "\n")
        msg = " | ".join(self.pub.check_scripts_leak())
        self.assertIn("scripts/notes.md:1", msg)

    def test_T27_scripts_host_tool_name_is_not_a_leak_but_path_is(self):
        """O6 只查泄露类：脚本里的宿主专有工具名属构造需要（它正是定义替换表的地方），不报；路径照样报。"""
        self.write(os.path.join(self.repo, "scripts", "tool.py"),
                   'R = [("' + "delegate" + "_task" + '", "spawn_subagent")]\n')
        self.assertEqual([b for b in self.pub.check_scripts_leak() if "tool.py" in b], [])
        self.write(os.path.join(self.repo, "scripts", "tool.py"),
                   'R = [("' + "delegate" + "_task" + '", "spawn_subagent")]\n# ' + _PATH_FS + "\n")
        msg = " | ".join(self.pub.check_scripts_leak())
        self.assertIn("scripts/tool.py:2", msg)

    # —— T5：单规则塌缩真阳性 ——
    def test_T5_single_rule_collapse_true_positive(self):
        self.build()
        self.write_live_body("alpha", "LINE_A 原始内容甲，长度与乙不同\nLINE_B 原始内容乙，也不一样\n")
        data = self.default_table()
        data["line_rules"] = [["active/alpha/SKILL.md", r"^(LINE_A|LINE_B)", "统一成一句常量文本"]]
        self.use_table(data)
        msg = " | ".join(self.pub.check_line_rule_collapse())
        self.assertIn("整行重写会丢内容", msg)
        self.assertIn("命中 2 行 / 去重 2 种内容", msg)

    # —— T6：多条内容完全相同的行不得被误报（live 里合法重复长行是常态）——
    def test_T6_repeated_identical_lines_are_not_reported(self):
        self.build()
        dup = "DUP_LINE 完全相同的长行内容，在 live 里重复出现是常态\n"
        self.write_live_body("alpha", dup * 3)
        data = self.default_table()
        data["line_rules"] = [["active/alpha/SKILL.md", r"^DUP_LINE", "统一成一句常量文本"]]
        self.use_table(data)
        self.assertEqual(self.pub.check_line_rule_collapse(), [])

    # —— T7：顺序模拟（G10 实修）——前一条规则改写过、后一条不再匹配的行不得被误判 ——
    def test_T7_sequential_simulation_avoids_false_positive(self):
        self.build()
        self.write_live_body("alpha",
                            "TARGET_69 原文甲：前一条规则会把它整行改写掉\n"
                            "TARGET_80 原文乙：只有这条该被后一条规则命中\n")
        data = self.default_table()
        data["line_rules"] = [
            ["active/alpha/SKILL.md", r"^TARGET_69", "改写后的一句常量"],
            ["active/alpha/SKILL.md", r"^TARGET_(69|80)", "后一条规则的常量句"],
        ]
        self.use_table(data)
        self.assertEqual(self.pub.check_line_rule_collapse(), [])

    # —— T8：跨规则塌缩（不同规则把不同内容改成同一句常量）——
    def test_T8_cross_rule_same_constant_reported(self):
        self.build()
        self.write_live_body("alpha", "ONE_ 内容甲\nTWO_ 内容乙\n")
        data = self.default_table()
        data["line_rules"] = [
            ["active/alpha/SKILL.md", r"^ONE_", "两条规则共用的同一句常量"],
            ["active/alpha/SKILL.md", r"^TWO_", "两条规则共用的同一句常量"],
        ]
        self.use_table(data)
        msg = " | ".join(self.pub.check_line_rule_collapse())
        self.assertIn("多规则把不同内容改成同一常量", msg)
        self.assertIn("2 种原内容 → 同一句", msg)

    # —— T9：文档一致性（三个计数 + 悬空引用 + KNOWN_EXTERNAL_REFS 豁免）——
    def test_T9_doc_consistency_counts_and_dangling_refs(self):
        self.build()
        readme = os.path.join(self.repo, "README.md")
        road = os.path.join(self.repo, "ROADMAP.md")
        self.assertEqual(self.pub.check_doc_consistency(), [])

        self.write(readme, self.readme_text(["alpha", "beta"], rows=3))
        self.assertIn("README「技能一览」表 3 行 vs active/ 实际 2 个技能",
                      " | ".join(self.pub.check_doc_consistency()))
        self.write(readme, self.readme_text(["alpha", "beta"], declared=3))
        self.assertIn("README 正文声明 3 个技能 vs active/ 实际 2 个",
                      " | ".join(self.pub.check_doc_consistency()))
        self.write(readme, self.readme_text(["alpha", "beta"], omit_decl=True))
        self.assertIn("README 正文找不到「N 个技能」声明",
                      " | ".join(self.pub.check_doc_consistency()))
        self.write(readme, self.readme_text(["alpha", "beta"]))

        self.write(road, self.roadmap_text(3))
        self.assertIn("ROADMAP 声明 3 个技能 vs active/ 实际 2 个",
                      " | ".join(self.pub.check_doc_consistency()))
        self.write(road, self.roadmap_text(2, omit=True))
        self.assertIn("ROADMAP 找不到「包内 N 个技能」声明",
                      " | ".join(self.pub.check_doc_consistency()))
        self.write(road, self.roadmap_text(2))

        ext = sorted(self.pub.KNOWN_EXTERNAL_REFS)[0]
        skill = os.path.join(self.repo, "active", "alpha", "SKILL.md")
        self.write(skill, self.skill_text("alpha", "见 `ghost-skill/scripts/run.py` 与 `beta/references/notes.md`。\n")
                   .replace("related_skills: []", f"related_skills: [beta, ghost-skill, {ext}]"))
        msg = " | ".join(self.pub.check_doc_consistency())
        self.assertIn("悬空引用（目标不在包内）", msg)
        self.assertIn("ghost-skill", msg)
        self.assertNotIn("→ beta", msg)
        self.assertNotIn(ext, msg)

        self.write(skill, self.skill_text("alpha", "见 `beta/references/notes.md`。\n")
                   .replace("related_skills: []", f"related_skills: [beta, {ext}]"))
        self.assertEqual(self.pub.check_doc_consistency(), [])

    # —— T10：fail-closed：私有脱敏表不在 → exit 1；表在位 → exit 0 ——
    def test_T10_fail_closed_without_private_table(self):
        self.build()
        self.use_table(exists=False)
        rc, out = self.run_check()
        self.assertEqual(rc, 1, out)
        self.assertIn("缺少本机私有脱敏表", out)
        self.assertIn("fail-closed", out)
        self.use_table()
        rc, out = self.run_check()
        self.assertEqual(rc, 0, out)
        self.assertIn("门禁通过", out)

    # —— T11：发布副本同步门禁（落后 / 缺文件 / 多文件 / live 源整棵缺失）——
    def test_T11_publish_sync_detects_drift_missing_and_extra(self):
        self.build()
        self.assertEqual(self.pub.check_publish_sync(), [])

        self.write_live_body("alpha", "live 新增的一行。\n")
        self.assertIn("发布副本落后 live | active/alpha/SKILL.md",
                      " | ".join(self.pub.check_publish_sync()))

        self.build()
        os.remove(os.path.join(self.repo, "active", "beta", "SKILL.md"))
        self.assertIn("发布副本缺文件 | active/beta/SKILL.md",
                      " | ".join(self.pub.check_publish_sync()))

        self.build()
        self.write(os.path.join(self.repo, "active", "beta", "references", "stale.md"), "旧内容\n")
        self.assertIn("发布副本多出文件（live 已无）| active/beta/references/stale.md",
                      " | ".join(self.pub.check_publish_sync()))

        self.set_const("SOURCES", dict(list(self.pub.SOURCES.items())
                                       + [("ghost", os.path.join(self.live, "active", "ghost"))]))
        self.assertIn("live 源缺失", " | ".join(self.pub.check_publish_sync()))

    # —— T12：同步门禁比的是「变换后的文本」而非字节（live 是 CRLF 不该假报）——
    def test_T12_sync_gate_compares_transformed_text_not_bytes(self):
        self.build()
        lf = self.skill_text("alpha")
        self.write_bytes(os.path.join(self.live, "active", "alpha", "SKILL.md"),
                         lf.replace("\n", "\r\n").encode("utf-8"))
        self.assertEqual(self.pub.check_publish_sync(), [])
        self.write_bytes(os.path.join(self.live, "active", "alpha", "SKILL.md"),
                         (lf + "\n新增一节\n").replace("\n", "\r\n").encode("utf-8"))
        self.assertIn("发布副本落后 live", " | ".join(self.pub.check_publish_sync()))

    # —— T13：私有表形态残缺 / 非法正则都必须 fail-closed ——
    def test_T13_malformed_private_table_is_fail_closed(self):
        self.build()
        for missing in ("私人项目名", "实名", "line_rules", "path_replacements"):
            data = self.default_table()
            data.pop(missing)
            self.use_table(data)
            with contextlib.redirect_stdout(io.StringIO()):
                got = self.pub.load_sensitive()
            self.assertIsNone(got, f"缺「{missing}」必须 fail-closed")
        data = self.default_table()
        data["line_rules"] = [["active/alpha/SKILL.md", "([未闭合", "x"]]
        self.use_table(data)
        with self.assertRaises(SystemExit) as cm:
            with contextlib.redirect_stdout(io.StringIO()):
                self.pub.load_line_rules()
        self.assertEqual(cm.exception.code, 1)


    # —— T14：无法映射的中文数字写法必须报可读错误，而不是抛 TypeError ——
    # 回归（主对话实测复现）：`_declared_skill_count` 曾返回含 None 的集合，
    # 下游 `sorted(...)` 里 int/None 混排 → TypeError，把门禁的可用报错降级成裸 traceback。
    def test_T14_unmappable_cn_numeral_reports_instead_of_crashing(self):
        self.build()
        # 夹具必须**同时**含「一个可解析 + 一个不可解析」的声明：这才是当初崩掉的形态——
        # 只有一个不可解析声明时不会走到 int/None 混排的排序分支，用例会假绿。
        self.write(os.path.join(self.repo, "README.md"),
                   self.readme_text(self.SKILLS).replace(
                       "本包共二个技能。", "本包共二个技能。\n\n（旧版曾写作十九个技能。）"))
        got = self.pub.check_doc_consistency()          # 不得抛异常
        self.assertTrue(any("无法解析" in b for b in got), got)

    # —— T15：ROADMAP 里**第二处**陈旧声明也必须被抓到（只查第一处是实测过的假阴性）——
    def test_T15_stale_second_declaration_is_caught(self):
        self.build()
        self.write(os.path.join(self.repo, "ROADMAP.md"),
                   "**最后核对**：包内 2 个技能。\n\n## 2. 差距\n\n"
                   "\u800c包内 9 个技能与 README 的「工作流全景」都没有对应节点。\n")
        got = self.pub.check_doc_consistency()
        self.assertTrue(any("ROADMAP 声明 9 个技能" in b for b in got), got)

    # —— T16：上游技能包惯用的 `(包名:技能名)` 行内指针必须被报为外包装指针 ——
    # 前两条指针规则（related_skills / 反引号路径）都匹配不到这个形态：实测有上游文本
    # 带着 `(superpowers:writing-skills)` 一路通过了旧门禁。
    def test_T16_external_pack_pointer_is_reported(self):
        self.build()
        self.write(os.path.join(self.repo, "active", "alpha", "SKILL.md"),
                   self.skill_text("alpha", body="参见 (superpowers:writing-skills) 的写法。\n"))
        got = self.pub.check_doc_consistency()
        self.assertTrue(any("外包装指针" in b for b in got), got)


    # —— T17：README 侧的**第二处**陈旧声明也必须被抓到（T15 只护住了 ROADMAP 侧）——
    # 回归：把 README 的「遍历全部声明」改回只取第一处时，本用例必须变红。
    # ⚠ 夹具两条声明都必须是**紧接写法**（数字与「个技能」之间不留空格）——第一版夹具写成
    #   「本包共 2 个技能。」，那个声明根本没被正则匹配上 → 用例在变异下仍绿（空转），被第二轮 Review 抓出。
    def test_T17_stale_second_readme_declaration_is_caught(self):
        self.build()
        self.write(os.path.join(self.repo, "README.md"),
                   "本包共二个技能。\n\n## 技能一览\n\n| 技能 | 说明 |\n|---|---|\n"
                   "| `alpha` | 说明 0 |\n| `beta` | 说明 1 |\n\n## 安装\n\n"
                   "\u65e7版说明：本包共九个技能。\n")
        got = self.pub.check_doc_consistency()
        self.assertTrue(any("README 正文声明 9 个技能" in b for b in got), got)

    # —— T20：带空格的叙述句**不得**被当成声明（防误报护栏）——
    # 判据是指「数字紧接『个技能』」；把这一点放宽会让「这 29 个技能里…」这类正常行变成假声明。
    def test_T20_prose_with_space_is_not_a_declaration(self):
        self.build()
        self.write(os.path.join(self.repo, "README.md"),
                   "本包共二个技能。\n\n## 技能一览\n\n| 技能 | 说明 |\n|---|---|\n"
                   "| `alpha` | 说明 0 |\n| `beta` | 说明 1 |\n\n## 安装\n\n"
                   "注意：这 29 个技能里有一半从没被读过。\n")
        self.assertEqual(self.pub.check_doc_consistency(), [])

    # —— T21：阿拉伯数字声明必须被接受（否则门禁的修法建议与判据自相矛盾）——
    def test_T21_arabic_digit_declaration_is_accepted(self):
        self.build()
        self.write(os.path.join(self.repo, "README.md"),
                   "本包共2个技能。\n\n## 技能一览\n\n| 技能 | 说明 |\n|---|---|\n"
                   "| `alpha` | 说明 0 |\n| `beta` | 说明 1 |\n\n## 安装\n\n略。\n")
        self.assertEqual(self.pub.check_doc_consistency(), [])

    # —— T22：缺「技能一览」小节只报一条；小节在文末不得被判为缺失 ——
    def test_T22_missing_section_reports_once_and_eof_section_is_ok(self):
        self.build()
        self.write(os.path.join(self.repo, "README.md"), "本包共二个技能。\n\n## 安装\n\n略。\n")
        got = self.pub.check_doc_consistency()
        self.assertTrue(any("找不到「## 技能一览」小节" in b for b in got), got)
        self.assertFalse(any("表缺" in b for b in got), "小节缺失时不该逐技能刷噪声")
        self.write(os.path.join(self.repo, "README.md"),
                   "本包共二个技能。\n\n## 技能一览\n\n| 技能 | 说明 |\n|---|---|\n"
                   "| `alpha` | 说明 0 |\n| `beta` | 说明 1 |\n")
        self.assertFalse(any("找不到" in b for b in self.pub.check_doc_consistency()))

    # —— T23：related_skills 的四种写法（第二轮 Review 抓出的 fail-open 与误报面）——
    def test_T23_related_skills_forms_are_parsed_correctly(self):
        self.build()
        path = os.path.join(self.repo, "active", "alpha", "SKILL.md")
        # (a) 块式列表里有空行 + 注释行：后面的悬空名不能漏（否则 = fail-open）
        self.write(path, self.skill_text("alpha").replace(
            "related_skills: []", "related_skills:\n  - beta\n\n  # 注释行\n  - ghost-zzz"))
        self.assertTrue(any("ghost-zzz" in b for b in self.pub.check_doc_consistency()))
        # (b) 行尾注释不得被吞进名字（否则合法文件被误报 ERROR）
        self.write(path, self.skill_text("alpha").replace(
            "related_skills: []", "related_skills: [beta]  # 只要包内的"))
        self.assertEqual(self.pub.check_doc_consistency(), [])
        # (c) 跨行 flow 写法：折行里的悬空名不能丢
        self.write(path, self.skill_text("alpha").replace(
            "related_skills: []", "related_skills: [beta,\n  ghost-zzz]"))
        self.assertTrue(any("ghost-zzz" in b for b in self.pub.check_doc_consistency()))
        # (d) 正文散文里的 related_skills: 不得当成 frontmatter 声明
        self.write(path, self.skill_text("alpha", body="正文示例。\n\nrelated_skills:\n- ghost-zzz\n"))
        self.assertEqual(self.pub.check_doc_consistency(), [])


    # —— T18：表里把技能名写错一个字母，行数不变 → 必须靠名字集合比对抓到 ——
    def test_T18_skill_name_typo_in_table_is_caught(self):
        self.build()
        self.write(os.path.join(self.repo, "README.md"),
                   self.readme_text(self.SKILLS).replace("| `beta` |", "| `btea` |"))
        joined = " | ".join(self.pub.check_doc_consistency())
        self.assertIn("表缺 beta", joined)
        self.assertIn("表多出 btea", joined)

    # —— T19：related_skills 的引号与块式两种写法 ——
    def test_T19_related_skills_quotes_and_block_style(self):
        self.build()
        # (a) 带引号的合法名字不得误报（否则合法写法会被当成悬空引用 ERROR）
        self.write(os.path.join(self.repo, "active", "alpha", "SKILL.md"),
                   self.skill_text("alpha").replace("related_skills: []",
                                                    'related_skills: ["beta"]'))
        self.assertEqual(self.pub.check_doc_consistency(), [])
        # (b) 块式写法里的悬空引用必须报出（旧实现静默放行 = fail-open）
        self.write(os.path.join(self.repo, "active", "alpha", "SKILL.md"),
                   self.skill_text("alpha").replace("related_skills: []",
                                                    "related_skills:\n  - beta\n  - ghost-zzz"))
        got = self.pub.check_doc_consistency()
        self.assertTrue(any("ghost-zzz" in b for b in got), got)


    # —— T24：第五处计数（SOURCES 白名单条目数）也要在比对里 ——
    def test_T24_sources_whitelist_count_is_compared(self):
        self.build()
        self.set_const("SOURCES", dict(list(self.pub.SOURCES.items())
                                       + [("ghost-wl", os.path.join(self.live, "active", "ghost-wl"))]))
        got = self.pub.check_doc_consistency()
        self.assertTrue(any("SOURCES 白名单" in b for b in got), got)


if __name__ == "__main__":
    unittest.main(verbosity=2)
