#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建公开发布区：从本地技能目录取白名单技能 → 脱敏 → 门禁扫描。

用法：
    python scripts/publish.py            # 同步 + 脱敏 + 门禁扫描（不推送）
    python scripts/publish.py --check    # 只扫描现有仓库内容（供 pre-push 钩子调用）

设计要点：
- live 技能保留真实路径（自用必需），**只清洗本仓库（发布副本）**。
- 白名单：只有 SKILLS 列出的技能会被发布；仓库里其余目录/文件一律清掉。
- 幂等、fail-closed：命中门禁规则即非零退出，阻止推送。
- scripts/ 自身不参与脱敏与扫描（正则字面量含关键词）。
"""
from __future__ import annotations
import os, re, shutil, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = "C:/Users/KonjacW/.codex/skills"

# 发布白名单（按名字，从 SRC/active/<name> 取）
SKILLS = ["review-gate", "using-superpowers", "agent-handover-prompts", "subagent-fanout-delivery"]
# 仓库里允许存在的顶层条目（其余一律清掉）
KEEP_TOP = {"active", "scripts", "README.md", "LICENSE", ".git", ".gitignore"}

TEXT_EXT = {".md", ".json", ".py", ".js", ".sh", ".ps1", ".dot", ".yaml", ".yml", ".toml", ".txt", ".html", ".css"}
SKIP_DIRS = {".git", "scripts"}

# 1) 逐字替换（长模式在前；含 YAML/JSON 双反斜杠转义形式）
REPLACEMENTS = [
    (r"C:\\\\Users\\\\KonjacW\\\\REDACTED\\\\1\\\\KonjacW Sync", "<OBSIDIAN_VAULT>"),
    (r"C:\\Users\\KonjacW\\REDACTED\\1\\KonjacW Sync", "<OBSIDIAN_VAULT>"),
    ("C:/Users/KonjacW/REDACTED/1/KonjacW Sync", "<OBSIDIAN_VAULT>"),
    (r"D:\\\\REDACTED", "<NOTE_VAULT>"),
    (r"D:\\REDACTED", "<NOTE_VAULT>"),
    ("D:/REDACTED", "<NOTE_VAULT>"),
    (r"C:\\\\Users\\\\KonjacW\\\\.codex\\\\skills\\\\active", "~/.codex/skills/active"),
    (r"C:\\Users\\KonjacW\\.codex\\skills\\active", "~/.codex/skills/active"),
    ("C:/Users/KonjacW/.codex/skills/active", "~/.codex/skills/active"),
    (r"C:\\\\Users\\\\KonjacW\\\\.codex", "~/.codex"),
    (r"C:\\Users\\KonjacW\\.codex", "~/.codex"),
    ("C:/Users/KonjacW/.codex", "~/.codex"),
    (r"C:\\\\Users\\\\KonjacW\\\\AppData\\\\Local", "%LOCALAPPDATA%"),
    (r"C:\\Users\\KonjacW\\AppData\\Local", "%LOCALAPPDATA%"),
    ("C:/Users/KonjacW/AppData/Local", "%LOCALAPPDATA%"),
    (r"C:\\\\Users\\\\KonjacW", "~"),
    (r"C:\\Users\\KonjacW", "~"),
    ("C:/Users/KonjacW", "~"),
]

# 1b) 正则替换：markdown 链接若指向本机绝对路径，改用链接文本里已有的相对路径
REGEX_RULES = [
    (re.compile(r"\[([^\]]+)\]\((?:[A-Za-z]:[\\/]{1,2}Users[\\/]KonjacW[^)]*)\)"),
     lambda m: f"[{m.group(1)}]({m.group(1)})" if re.match(r"^(\.\.?/|[A-Za-z0-9_.-]+/)", m.group(1)) else m.group(0)),
]

# 2) 整行重写：移除含私人项目名的样本行
LINE_RULES = [
    ("active/agent-handover-prompts/SKILL.md", r"REDACTED|REDACTED",
     "- 规范样本（12 节结构 + 数字附录 + 自检命令）：见你本地项目的 `docs/*/*_handover_YYYYMMDD.md`（数字附录唯一规格源的写法）。"),
    ("active/agent-handover-prompts/SKILL.md", r"REDACTED",
     "- 前端/单机调试型交接变体（任务清单 A-F + 测试坑清单 + 不要做的事）：见你本地前端项目的 `docs/debug/*handoff*.md`。"),
]

# 3) 已知非 UTF-8 文件（解码后统一转 UTF-8）
ENCODING_FIX = {}

# 4) 门禁扫描：命中即失败
SCAN = {
    "私人项目名":   re.compile(r"REDACTED|REDACTED|REDACTED|REDACTED|REDACTED|REDACTED|REDACTED", re.I),
    "私人路径":     re.compile(r"REDACTED|REDACTED|" + re.escape("REDACTED") + r"|REDACTED|REDACTED", re.I),
    "本机绝对路径": re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]"),
    "实名":         re.compile(r"REDACTED|REDACTED"),
    "疑似密钥":     re.compile(r"sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|Bearer [A-Za-z0-9._-]{20,}"),
    "服务器凭据":   re.compile(r"REDACTED|REDACTED"),
}


def iter_text_files(root: str):
    for dp, dn, fn in os.walk(root):
        if set(dp.split(os.sep)) & SKIP_DIRS:
            continue
        for f in fn:
            if os.path.splitext(f)[1].lower() in TEXT_EXT:
                yield os.path.join(dp, f)


def read_text(path: str, rel: str):
    b = open(path, "rb").read()
    try:
        return b.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        enc = ENCODING_FIX.get(rel)
        return (b.decode(enc), enc) if enc else (None, "未知编码")


def scrub(text: str):
    n = 0
    for rx, fn in REGEX_RULES:
        text, k = rx.subn(fn, text); n += k
    for old, new in REPLACEMENTS:
        c = text.count(old)
        if c:
            text = text.replace(old, new); n += c
    return text, n


def sync():
    log = []
    # 清掉仓库里不在白名单内的顶层条目
    for item in os.listdir(REPO):
        if item in KEEP_TOP:
            continue
        p = os.path.join(REPO, item)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        log.append(f"移除 {item}（不在白名单）")
    act = os.path.join(REPO, "active")
    if os.path.isdir(act):
        shutil.rmtree(act)
    os.makedirs(act, exist_ok=True)
    for name in SKILLS:
        src = os.path.join(SRC, "active", name)
        if not os.path.isdir(src):
            log.append(f"⚠ 源缺失，跳过: active/{name}"); continue
        shutil.copytree(src, os.path.join(act, name))
        log.append(f"同步 active/{name}/")
    # 脱敏 + 编码归一
    for p in iter_text_files(REPO):
        rel = os.path.relpath(p, REPO).replace("\\", "/")
        t, enc = read_text(p, rel)
        if t is None:
            log.append(f"⚠ 跳过（未知编码）: {rel}"); continue
        t2, c = scrub(t)
        if c:
            log.append(f"脱敏 {rel}: {c} 处")
        if enc != "utf-8":
            log.append(f"编码归一 {rel}: {enc} → utf-8")
        if t2 != t or enc != "utf-8":
            open(p, "w", encoding="utf-8", newline="").write(t2)
    for rel, pat, newline in LINE_RULES:
        p = os.path.join(REPO, rel)
        if not os.path.isfile(p):
            continue
        rx = re.compile(pat, re.I)
        lines = open(p, encoding="utf-8").read().split("\n")
        hit = 0
        for i, l in enumerate(lines):
            if rx.search(l):
                lines[i] = newline; hit += 1
        if hit:
            open(p, "w", encoding="utf-8", newline="").write("\n".join(lines))
            log.append(f"整行重写 {rel}: {hit} 行")
    return log


def check() -> int:
    bad = []
    for p in iter_text_files(REPO):
        rel = os.path.relpath(p, REPO).replace("\\", "/")
        t, enc = read_text(p, rel)
        if t is None:
            bad.append(f"未知编码 | {rel}"); continue
        if enc != "utf-8":
            bad.append(f"非 UTF-8({enc}) | {rel}")
        for i, l in enumerate(t.split("\n"), 1):
            for cat, rx in SCAN.items():
                if rx.search(l):
                    bad.append(f"{cat} | {rel}:{i}")
    if bad:
        print("✗ 门禁未通过，禁止推送：")
        for b in sorted(set(bad)):
            print("   ", b)
        return 1
    print("✓ 门禁通过：无私人路径 / 无私人项目名 / 无实名 / 无密钥 / 全 UTF-8")
    return 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    for line in sync():
        print("  ", line)
    print()
    sys.exit(check())
