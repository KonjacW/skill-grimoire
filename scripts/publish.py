#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建公开发布区：按白名单采集技能 → 宿主中立化 + 脱敏 → fail-closed 门禁。

用法：
    python scripts/publish.py            # 同步 + 归一 + 脱敏 + 门禁（不推送）
    python scripts/publish.py --check    # 只扫描现有仓库内容（供 pre-push 钩子调用）

设计要点：
- **live 技能一律不动**（保留真实路径与宿主工具名）；只清洗本仓库里的发布副本。
- 白名单在 SOURCES 里：技能名 → 源目录。技能可从任意本地技能树采集。
- 归一化：frontmatter 去掉 Codex 不认的键（version/author/platforms）、宿主元数据键改名；
  正文里的宿主专有工具名/路径换成中立写法。
- 幂等、fail-closed：命中门禁规则即非零退出，阻止推送。
"""
from __future__ import annotations
import os, re, shutil, sys, json

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODEX = "C:/Users/KonjacW/.codex/skills"
HERMES = "C:/Users/KonjacW/AppData/Local/hermes/skills"

# 白名单：发布哪些技能，以及它们的源目录（唯一权威副本 = CODEX/active）
SOURCES = {
    "review-gate":                       f"{CODEX}/active/review-gate",
    "using-superpowers":                 f"{CODEX}/active/using-superpowers",
    "agent-handover-prompts":            f"{CODEX}/active/agent-handover-prompts",
    "subagent-fanout-delivery":          f"{CODEX}/active/subagent-fanout-delivery",
    "pre-commit-verification":           f"{CODEX}/active/pre-commit-verification",
    "plan":                              f"{CODEX}/active/plan",
    "spike":                             f"{CODEX}/active/spike",
    "finishing-a-development-branch":    f"{CODEX}/active/finishing-a-development-branch",
}
KEEP_TOP = {"active", "scripts", "README.md", "LICENSE", ".git", ".gitignore", ".gitattributes"}
TEXT_EXT = {".md", ".json", ".py", ".js", ".sh", ".ps1", ".dot", ".yaml", ".yml", ".toml", ".txt", ".html", ".css"}
SKIP_DIRS = {".git", "scripts"}

# —— 1) frontmatter 归一化（发布副本专用）——
FRONTMATTER_STRIP = ("version:", "author:", "platforms:", "dependencies:")
FRONTMATTER_KEY_RENAME = [("  hermes:", "  agent:")]   # metadata 下的宿主命名空间

# —— 2) 逐字替换（长模式在前）——
REPLACEMENTS = [
    # 私人库路径 → 占位符：这些原串本身含私人路径，已移入本机私有表，见 path_replacements()
    # 本机绝对路径 → 可移植形式
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
    # 宿主专有写法 → 中立写法
    ("delegate_task", "spawn_subagent"),
    (".hermes/plans", "docs/plans"),
    ("Hermes file tools are backend-aware", "file tools are workspace-aware"),
    ("Use Hermes tools", "Use your file/search tools"),
    ("npx get-shit-done-cc --hermes", "npx get-shit-done-cc"),
    ("**For Hermes:**", "**执行提示：**"),
    ("（Hermes 读不到", "（子代理读不到"),
    # 发布副本里全部路径已被替换成 docs/plans/，这行注解在此语境下会自相矛盾（暗示 Hermes 用别的目录）
    ("> 非 Hermes 宿主（Codex 等）：计划目录改用 `docs/plans/`。", "> 计划目录：`docs/plans/`。"),
]

# 3) 正则替换：markdown 链接若指向本机绝对路径，改用链接文本里已有的相对路径
REGEX_RULES = [
    (re.compile(r"\[([^\]]+)\]\((?:[A-Za-z]:[\\/]{1,2}Users[\\/]KonjacW[^)]*)\)"),
     lambda m: f"[{m.group(1)}]({m.group(1)})" if re.match(r"^(\.\.?/|[A-Za-z0-9_.-]+/)", m.group(1)) else m.group(0)),
]

# 4) 整行重写：移除含私人项目名的样本行。
#    规则本身（匹配式 + 替换文本）就带私人信息，故整表落在本机私有表里，见 load_line_rules()。

# 5) 在 H1 之后插入一行说明（每文件最多一次）
INSERT_AFTER_H1 = {
    "active/pre-commit-verification/SKILL.md": "> 文中的 `spawn_subagent` 指**宿主提供的子代理派发工具**——换成你自己宿主的工具名即可。\n",
    "active/spike/SKILL.md": "> 文中的 `spawn_subagent` 指**宿主提供的子代理派发工具**——换成你自己宿主的工具名即可。\n",
    "active/subagent-fanout-delivery/references/overlap-classification.md": "> 文中的 `spawn_subagent`（含控制动作 `action='stop'`）指**宿主提供的子代理工具**——换成你自己宿主的工具名即可。\n",
}

# 6) 门禁扫描（命中即失败）
# 通用规则不含任何私人信息，直接内置；含私人信息的四类从**本机私有表**读取——
# 该表被 .gitignore 忽略，不随公开仓发布（否则「脱敏词表」本身就成了私人信息泄露）。
SCAN_GENERIC = {
    "本机绝对路径":   re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]"),
    "疑似密钥":       re.compile(r"sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|Bearer [A-Za-z0-9._-]{20,}"),
    "宿主专有工具":   re.compile(r"delegate_task|\.hermes/"),
    "非法 frontmatter": re.compile(r"^(version|author|platforms|dependencies):"),
    "宿主元数据键":   re.compile(r"^\s+hermes:\s*$"),
    "CRLF 行尾":      re.compile(r"\r$"),
}
SENSITIVE_CATEGORIES = {"私人项目名": re.I, "私人路径": re.I, "实名": 0, "服务器凭据": 0}
LOCAL_REDACT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "redact-patterns.local.json")


def load_sensitive():
    """读本机私有脱敏表。缺文件 / 缺类别 / 解析失败一律返回 None（fail-closed）。"""
    if not os.path.isfile(LOCAL_REDACT):
        print(f"✗ 缺少本机私有脱敏表：{LOCAL_REDACT}")
        return None
    try:
        data = json.load(open(LOCAL_REDACT, encoding="utf-8"))
    except Exception as e:
        print(f"✗ 脱敏表无法解析：{e}")
        return None
    out = {}
    for cat, flags in SENSITIVE_CATEGORIES.items():
        pats = data.get(cat)
        if not pats:
            print(f"✗ 脱敏表缺类别：{cat}（不允许留空，否则该类形同未脱敏）")
            return None
        out[cat] = re.compile("|".join(pats), flags)
    if not data.get("line_rules"):
        print("✗ 脱敏表缺 line_rules（整行重写规则；留空会让私人样本行被原样发布）")
        return None
    if not data.get("path_replacements"):
        print("✗ 脱敏表缺 path_replacements（私有路径替换对）")
        return None
    return out


def load_line_rules():
    """整行重写规则：[(相对路径, 已编译正则, 替换整行文本)]，全部来自本机私有表。"""
    data = json.load(open(LOCAL_REDACT, encoding="utf-8"))
    return [(rel, re.compile(pat, re.I), rep) for rel, pat, rep in data["line_rules"]]


def path_replacements():
    """私有路径的字面串替换对 [(原串, 占位符)]，同样来自本机私有表。

    注意这些是**字面串**（scrub 用 count/replace），不是正则——别写成 re。
    """
    data = json.load(open(LOCAL_REDACT, encoding="utf-8"))
    return [(o, n) for o, n in data["path_replacements"]]


def scan_rules():
    """通用规则 + 私有规则。私有表不可用时返回 None，调用方须按 fail-closed 处理。"""
    sens = load_sensitive()
    if sens is None:
        return None
    rules = dict(SCAN_GENERIC)
    rules.update(sens)
    return rules


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
        return None, "未知编码"


def normalize_frontmatter(text: str) -> tuple[str, int]:
    """去掉 Codex 不认的顶层键、把宿主元数据键改名。只处理文件开头的 frontmatter。"""
    if not text.startswith("---"):
        return text, 0
    end = text.find("\n---", 3)
    if end < 0:
        return text, 0
    head, rest = text[3:end], text[end:]
    out, n = [], 0
    for line in head.split("\n"):
        if line.startswith(FRONTMATTER_STRIP):
            n += 1; continue
        new = line
        for old, rep in FRONTMATTER_KEY_RENAME:
            if new == old:
                new = rep; n += 1
        out.append(new)
    return "---" + "\n".join(out) + rest, n


def scrub(text: str):
    n = 0
    for rx, fn in REGEX_RULES:
        text, k = rx.subn(fn, text); n += k
    for old, new in path_replacements() + REPLACEMENTS:
        c = text.count(old)
        if c:
            text = text.replace(old, new); n += c
    return text, n


def sync():
    log = []
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
    for name, src in SOURCES.items():
        if not os.path.isdir(src):
            log.append(f"⚠ 源缺失，跳过: {name} ({src})"); continue
        shutil.copytree(src, os.path.join(act, name))
        log.append(f"同步 active/{name}/")
    for p in iter_text_files(REPO):
        rel = os.path.relpath(p, REPO).replace("\\", "/")
        raw = open(p, "rb").read()                     # 按字节比较：文本模式重读会把 CRLF 翻成 LF，误判「未变」
        try:
            t = raw.decode("utf-8")
        except UnicodeDecodeError:
            log.append(f"⚠ 跳过（未知编码）: {rel}"); continue
        orig = t
        if "\r\n" in t:                               # 发布树统一 LF（否则 git 每次翻转 → 整文件 diff）
            t = t.replace("\r\n", "\n")
            log.append(f"行尾归一 → LF: {rel}")
        t, n_fm = normalize_frontmatter(t)
        t, n_txt = scrub(t)
        if n_fm or n_txt:
            log.append(f"归一 {rel}: frontmatter {n_fm} 项 / 正文 {n_txt} 处")
        if t != orig or t.encode("utf-8") != raw:
            open(p, "wb").write(t.encode("utf-8"))
    for rel, rx, newline in load_line_rules():
        p = os.path.join(REPO, rel)
        if not os.path.isfile(p):
            continue
        lines = open(p, encoding="utf-8").read().split("\n")
        hit = 0
        for i, l in enumerate(lines):
            if rx.search(l):
                lines[i] = newline; hit += 1
        if hit:
            open(p, "w", encoding="utf-8", newline="").write("\n".join(lines))
            log.append(f"整行重写 {rel}: {hit} 行")
    for rel, note in INSERT_AFTER_H1.items():
        p = os.path.join(REPO, rel)
        if not os.path.isfile(p):
            continue
        lines = open(p, encoding="utf-8").read().split("\n")
        if note.strip() in "\n".join(lines):
            continue
        for i, l in enumerate(lines):
            if l.startswith("# "):
                lines.insert(i + 1, "\n" + note.rstrip("\n"))
                open(p, "w", encoding="utf-8", newline="").write("\n".join(lines))
                log.append(f"插入使用说明 {rel}")
                break
    return log


def check() -> int:
    rules = scan_rules()
    if rules is None:
        print("✗ 门禁未能运行（私有脱敏表不可用）→ 按 fail-closed 处理，禁止推送。")
        return 1
    bad = []
    for p in iter_text_files(REPO):
        rel = os.path.relpath(p, REPO).replace("\\", "/")
        t, enc = read_text(p, rel)
        if t is None:
            bad.append(f"未知编码 | {rel}"); continue
        if enc != "utf-8":
            bad.append(f"非 UTF-8({enc}) | {rel}")
        for i, l in enumerate(t.split("\n"), 1):
            for cat, rx in rules.items():
                if rx.search(l):
                    bad.append(f"{cat} | {rel}:{i}")
    if bad:
        print("✗ 门禁未通过，禁止推送：")
        for b in sorted(set(bad)):
            print("   ", b)
        return 1
    print(f"✓ 门禁通过：{len(SOURCES)} 个技能；无私人路径/项目名/实名/密钥/宿主专有写法；frontmatter 合法；全 UTF-8")
    return 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    for line in sync():
        print("  ", line)
    print()
    sys.exit(check())
