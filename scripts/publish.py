#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建公开发布区：按白名单采集技能 → 宿主中立化 + 脱敏 → fail-closed 门禁。

用法：
    python scripts/publish.py                   # 同步 + 归一 + 脱敏 + 门禁（不推送）
    python scripts/publish.py --check           # 只检查不写：仓内内容 + 整行规则塌缩 + 发布副本是否落后 live
                                                # （pre-push 钩子调用这个；它依赖本机私有脱敏表与 live 技能树）
    python scripts/publish.py --check-repo-only # 只扫仓内内容：拿不到 live 技能树时用（仍需要私有脱敏表）

设计要点：
- **live 技能一律不动**（保留真实路径与宿主工具名）；只清洗本仓库里的发布副本。
- 白名单在 SOURCES 里：技能名 → 源目录。技能可从任意本地技能树采集。
- 归一化：frontmatter 去掉 Codex 不认的键（version/author/platforms）、宿主元数据键改名；
  正文里的宿主专有工具名/路径换成中立写法。
- 幂等、fail-closed：命中门禁规则即非零退出，阻止推送。
- 两种「静默丢内容」形态都在门禁里：单条整行规则一次改写多条不同内容（单规则塌缩）、
  以及多条规则把不同内容改成同一句常量（跨规则塌缩）。
- **私有脱敏表是必需的**（`scripts/redact-patterns.local.json`，被 .gitignore 忽略、不随仓发布）：
  缺表即 fail-closed。因此 `--check` 天然是维护者侧命令，克隆者拿不到表也跑不过——这不是缺陷。
"""
from __future__ import annotations
import os, re, shutil, sys, json

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 本机路径一律从环境推导：本脚本随公开仓发布，不得硬编码维护者的用户名与目录
# （维护者侧曾把盘符 + 用户目录写成字面量，随公开仓一路发布——ROADMAP G11 的残余形态）。
_HOME = os.path.expanduser("~").replace("\\", "/")
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", f"{_HOME}/AppData/Local").replace("\\", "/")
CODEX = f"{_HOME}/.codex/skills"
HERMES = f"{_LOCALAPPDATA}/hermes/skills"

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
    # 2026-09-12 加入：上游 obra/superpowers 的 MIT 许可已经 GitHub API 实测核实，随包发布（保署名）
    "long-running-progress-monitoring":  f"{CODEX}/active/long-running-progress-monitoring",
    # 2026-09-13 加入：实现期质量路径（测试驱动）。原仅存在于另一宿主的技能树，
    # 已按「一个技能只有一份可发现副本」的规则迁入 active/，Hermes 侧旧副本已 .disabled 退役。
    # 许可：references/writing-good-tests.md 为上游 obra/superpowers 的 MIT 逐字文本（署名见 README
    # 「许可与致谢」与 SKILL.md 的「来源与署名」行）；SKILL.md 为本仓自有整理。改动该 references
    # 文件等于产生上游的修改版，须同步维护三处署名。
    "test-driven-development":           f"{CODEX}/active/test-driven-development",
    # 2026-09-15 加入：同一对话内、面向用户本人的周期性成果汇报（口令「开汇报」启动，双轨更新）。
    "conversation-progress-report":      f"{CODEX}/active/conversation-progress-report",
    # 2026-09-22 加入：对话里「解释 / 说明」类回答的形态规范（结论先行 / 一概念只讲一次 / 类比须有产出）。
    "explanation-style":                 f"{CODEX}/active/explanation-style",
}
KEEP_TOP = {"active", "scripts", "README.md", "ROADMAP.md", "LICENSE", ".git", ".gitignore", ".gitattributes"}
TEXT_EXT = {".md", ".json", ".py", ".js", ".sh", ".ps1", ".dot", ".yaml", ".yml", ".toml", ".txt", ".html", ".css"}
# 只跳过**仓根自己**的这一级目录。发布树里 active/<技能>/scripts/** 属于发布内容，
# 必须归一、必须被 --check 扫；按目录名在任意层级跳过会把它们整片漏掉。
SKIP_DIRS = {".git", "scripts"}

# —— 1) frontmatter 归一化（发布副本专用）——
FRONTMATTER_STRIP = ("version:", "author:", "platforms:", "dependencies:")
FRONTMATTER_KEY_RENAME = [("  hermes:", "  agent:")]   # metadata 下的宿主命名空间

# —— 2) 逐字替换（长模式在前）——


def _win_spellings(prefix: str):
    """同一 Windows 路径的几种字面写法：四 / 双 / 单反斜杠 + 正斜杠。

    四反斜杠那种出现在「被转义过两层的文本」里（例如技能正文里引用的 JSON 片段）。
    **必须先归一到正斜杠再展开**：传进来的前缀本身已是反斜杠形式，直接 `replace("/")` 是空操作，
    实测会让 2/4 反斜杠两档整档消失（T4 用例抓到：三种写法只洗净了一种；仓内容零 diff 掩盖了它）。
    """
    base = prefix.replace(chr(92), "/")
    return [base.replace("/", chr(92) * n) for n in (4, 2, 1)] + [base]


def _home_path_pairs():
    """本机路径 → 可移植占位符的替换对（长模式在前）。

    路径从 HOME / LOCALAPPDATA 推导，不硬编码维护者用户名：克隆者跑同一脚本时替换的是
    **他自己**的本机路径，行为与维护者侧一致；同时补上了原先缺的「单反斜杠」写法档。
    """
    win = _HOME.replace("/", '\\')
    out = []
    for prefix, portable in (
        (win + '\\' + ".codex" + '\\' + "skills" + '\\' + "active", "~/.codex/skills/active"),
        (win + '\\' + ".codex", "~/.codex"),
        (win + '\\' + "AppData" + '\\' + "Local", "%LOCALAPPDATA%"),
        (win, "~"),
    ):
        for s in _win_spellings(prefix):
            out.append((s, portable))
    return out


REPLACEMENTS = [
    *_home_path_pairs(),
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
    (re.compile(r"\[([^\]]+)\]\((?:[A-Za-z]:[\\/]{1,2}Users[\\/]"
                + re.escape(os.path.basename(_HOME)) + r"[^)]*)\)"),
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
_LINE_RULES_CACHE = None      # load_line_rules() 的解析缓存（一次运行内私有表不变）


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
        out[cat] = None
        try:
            out[cat] = re.compile("|".join(pats), flags)
        except re.error as e:
            print(f"✗ 脱敏表类别「{cat}」里有非法正则，门禁无法运行：{e}")
            return None
    if not data.get("line_rules"):
        print("✗ 脱敏表缺 line_rules（整行重写规则；留空会让私人样本行被原样发布）")
        return None
    if not data.get("path_replacements"):
        print("✗ 脱敏表缺 path_replacements（私有路径替换对）")
        return None
    return out


def load_line_rules():
    """整行重写规则：[(相对路径, 已编译正则, 替换整行文本)]，全部来自本机私有表。

    解析结果缓存一次：check()/sync() 会对每个文件重复取用（实测单次 --check 曾解析 46 次）。
    非法正则按 fail-closed 处理——打印归属清楚的错误并非零退出，而不是把 re.error 的
    traceback 直接抛给使用者（traceback 也是非零退出，但信息不可用）。
    """
    global _LINE_RULES_CACHE
    if _LINE_RULES_CACHE is None:
        data = json.load(open(LOCAL_REDACT, encoding="utf-8"))
        out = []
        for rel, pat, rep in data["line_rules"]:
            try:
                out.append((rel, re.compile(pat, re.I), rep))
            except re.error as e:
                print(f"✗ 脱敏表 line_rules 里有非法正则（目标 {rel}），门禁无法运行：{e}")
                raise SystemExit(1)
        _LINE_RULES_CACHE = out
    return _LINE_RULES_CACHE


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


def iter_text_files(root: str, skip_top=SKIP_DIRS):
    """遍历 root 下的文本文件；skip_top 只作用于 root 的**第一层**目录名。

    传 skip_top=None 表示不跳过任何目录（用于技能目录内部：技能自带的 scripts/ 也是发布内容）。
    """
    for dp, dn, fn in os.walk(root):
        if skip_top and os.path.abspath(dp) == os.path.abspath(root):
            dn[:] = [d for d in dn if d not in skip_top]
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


BACKREF = re.compile(r"\\[1-9]|\\g<")


def live_source_file(rel: str):
    """发布区相对路径 → live 源文件绝对路径；不属于 SOURCES 白名单则 None。"""
    parts = rel.replace("\\", "/").split("/")
    if len(parts) >= 3 and parts[0] == "active" and parts[1] in SOURCES:
        return os.path.join(SOURCES[parts[1]], *parts[2:])
    return None


def transform_text(t: str, rel: str) -> str:
    """live 文本 → 发布文本：LF 归一 → frontmatter 归一 → 脱敏 → 私有整行重写 → H1 后插入。

    sync() 对磁盘副本做的是同一套变换、同一顺序；--check 的同步门禁用它算出「发布副本应该是」的内容。
    rel 是发布区相对路径（active/<技能>/<相对路径>），私有整行重写规则按它取用。
    """
    if "\r\n" in t:
        t = t.replace("\r\n", "\n")
    t, _ = normalize_frontmatter(t)
    t, _ = scrub(t)
    for lrel, rx, rep in load_line_rules():
        if lrel.replace("\\", "/") != rel:
            continue
        lines = t.split("\n")
        for i, l in enumerate(lines):
            if rx.search(l):
                lines[i] = rep
        t = "\n".join(lines)
    note = INSERT_AFTER_H1.get(rel)
    if note and note.strip() not in t:
        lines = t.split("\n")
        for i, l in enumerate(lines):
            if l.startswith("# "):
                lines.insert(i + 1, "\n" + note.rstrip("\n"))
                t = "\n".join(lines)
                break
    return t


def check_line_rule_collapse():
    """O1a′：静态检测「整行重写把多条不同内容塌缩成一条常量」。

    判据（不看重复长行这种文本启发式）：**在顺序模拟中**，某条 line_rule 一次改写掉 K 行、
    其中内容互不相同的行有 D 行，而替换文本是不带回引的常量 → D≥2 时构造上必然丢内容。

    必须**顺序模拟**（逐条规则依次落盘、后一条看得到前一条的结果），与 transform_text()/sync()
    的执行顺序一致：否则一条「先命中 A 行、把它改写成不再被后续规则匹配的文本」的规则，
    会被误判成塌缩——实测本例：private 表新增的首条规则先把 live:69 改写掉，后续那条通用规则
    实际只剩 live:80 一行可命中，独立扫描却会看到 69/80 两行而假报。
    """
    bad = []
    by_rel = {}
    for rel, rx, rep in load_line_rules():          # 保持表内顺序
        by_rel.setdefault(rel.replace("\\", "/"), []).append((rx, rep))
    for rel, rules in by_rel.items():
        src = live_source_file(rel)
        if not src or not os.path.isfile(src):
            # 必须是 ERROR 而不是告警：目标文件解析不到时，这条规则在真实发布里同样不生效
            # （transform_text 按同一 rel 键取用），结果是本该被整行重写掉的私人文本静默进发布区，
            # 而 check_publish_sync 比的是同一份有缺陷的变换、也不会报。本文件里其余表错误
            # （缺表/类别留空/非法正则）全是 exit 1，唯独这个「会静默漏脱敏」的形态不能只告警。
            bad.append(f"整行规则的目标文件解析不到（写错路径或技能已改名/移除）| {rel}")
            continue
        lines = (open(src, encoding="utf-8", errors="replace").read()
                 .replace("\r\n", "\n").split("\n"))
        per_const = {}                              # 常量替换文本 → [(规则序号, 行号, 去空白原文)]
        single_reported = set()                     # 已被单规则判据报过的常量，避免同一次违规报两遍
        for k, (rx, rep) in enumerate(rules):
            hit = [(i + 1, lines[i]) for i in range(len(lines)) if rx.search(lines[i])]
            if not hit:
                continue
            distinct = {c.strip() for _, c in hit}
            if len(distinct) >= 2 and not BACKREF.search(rep):
                shown = ", ".join(str(i) for i, _ in hit[:8]) + ("..." if len(hit) > 8 else "")
                bad.append(f"整行重写会丢内容 | {rel} (live 行 {shown}; 命中 {len(hit)} 行 / "
                           f"去重 {len(distinct)} 种内容，替换为常量)")
                single_reported.add(rep)
            if not BACKREF.search(rep):
                for i, c in hit:
                    per_const.setdefault(rep, []).append((k, i, c.strip()))
            for i, _ in hit:                        # 顺序推进，与 sync() 一致
                lines[i - 1] = rep
        # 跨规则塌缩：不同规则把内容互不相同的行改成同一句常量。G10 的实际形态正是这一类——
        # 单看每条规则各命中 1 行时（如一条吃第 69 行、另一条吃第 80 行）单条判据不会暴露。
        for rep, got in per_const.items():
            if rep in single_reported:
                continue
            if len({k for k, _, _ in got}) >= 2 and len({c for _, _, c in got}) >= 2:
                pos = ", ".join(f"规则{k + 1}:行{i}" for k, i, _ in got[:8])
                bad.append(f"多规则把不同内容改成同一常量 | {rel} ({pos}；共 {len(got)} 处 / "
                           f"{len({c for _, _, c in got})} 种原内容 → 同一句)")
    return bad


def check_publish_sync():
    """O4：live ↔ 发布副本同步门禁。

    对每个白名单技能，把 live 文件在内存里走同一套变换（见 transform_text），与仓内
    active/<技能>/ 逐文件比**变换后的文本**（不比字节：live 可能是 CRLF，字节比会假报）。
    """
    bad = []
    for name, src in SOURCES.items():
        dst = os.path.join(REPO, "active", name)
        if not os.path.isdir(src):
            bad.append(f"live 源缺失（非同机维护者环境请改用 --check-repo-only）| {src}")
            continue
        if not os.path.isdir(dst):
            bad.append(f"发布副本缺失 | active/{name}/")
            continue
        live_rels = set()
        for p in iter_text_files(src, skip_top=None):
            rel = os.path.relpath(p, src).replace("\\", "/")
            live_rels.add(rel)
            pub_rel = f"active/{name}/{rel}"
            t, _ = read_text(p, pub_rel)
            if t is None:
                bad.append(f"live 源非 UTF-8 | {pub_rel}")
                continue
            dp = os.path.join(dst, *rel.split("/"))
            if not os.path.isfile(dp):
                bad.append(f"发布副本缺文件 | {pub_rel}")
                continue
            got, enc = read_text(dp, pub_rel)
            if got is None:
                bad.append(f"发布副本非 UTF-8({enc}) | {pub_rel}")
                continue
            if got != transform_text(t, pub_rel):
                bad.append(f"发布副本落后 live | {pub_rel}")
        for p in iter_text_files(dst, skip_top=None):
            rel = os.path.relpath(p, dst).replace("\\", "/")
            if rel not in live_rels:
                bad.append(f"发布副本多出文件（live 已无）| active/{name}/{rel}")
    return bad


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


CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
          "九": 9, "十": 10, "十一": 11, "十二": 12}

# 刻意留在包外的被引用技能（正文已写明「本包不含该技能，按本节文字自行执行」的降级说明）。
# 只豁免这些名字：不在表里的悬空引用是**新引入**的漂移，必须报错。
KNOWN_EXTERNAL_REFS = {"deliverable-checker-suite"}

# 上游技能包惯用的行内限定词（`(superpowers:writing-skills)` 这种）。读者拿不到那个包，
# 所以按「外包装指针」报错，要求改写成自足表述。
EXT_PACK_POINTER = re.compile(r"(superpowers|gsd|obra):[a-z0-9-]{2,}")


def _declared_skill_count(text: str):
    """从文本里读「N 个技能」的中文数字声明。

    返回 `(识别到的数字集合, 无法识别的写法集合)`。**必须把两个集合分开**：
    没法识别的写法（如「十九个技能」）会在下游比较里变成 `None` 与 `int` 混排，
    实测直接抛 `TypeError`（`'<' not supported between instances of 'int' and 'NoneType'`），
    把一个本可读的门禁报错降级成裸 traceback —— 与本模块「报错信息必须可用」的自我要求相反。
    只查第一处也不行：改了「最后核对」行之后，后文里留着旧数字的声明会被漏掉（实测假阴性）。
    """
    nums, unknown = set(), set()
    for x in re.findall(r"(\d+|[一二三四五六七八九十]{1,2})个技能", text):
        if x.isdigit():                 # 阿拉伯数字写法也接受（否则修法建议与判据自相矛盾）
            nums.add(int(x))
        elif x in CN_NUM:
            nums.add(CN_NUM[x])
        else:
            unknown.add(x)
    return nums, unknown


def _strip_comment(s: str) -> str:
    """剥掉 YAML 里引号外的行尾注释（`beta  # 注释` → `beta`）。"""
    out, quote = [], None
    for i, c in enumerate(s):
        if quote:
            if c == quote:
                quote = None
            out.append(c)
        elif c in "'\"":
            quote = c
            out.append(c)
        elif c == "#" and (i == 0 or s[i - 1].isspace()):
            break
        else:
            out.append(c)
    return "".join(out).rstrip()


def _related_skill_names(text: str) -> set:
    """从 **frontmatter** 里取 `related_skills` 的名字集合（不扫正文）。

    支持：行内 `[a, b]`（含跨行 flow 写法）与块式（`- a` / `  - a`）。
    第二轮 Review 抓出的四个缺陷，全部已修（每条都有实跑证据）：
      · 只扫全文 → 正文散文里的 `related_skills:` 被当声明 → 先切出 frontmatter 段；
      · 块式遇空行/注释行即 break → 会**静默漏掉**后面的名字（fail-open）→ 现在跳过再继续；
      · 行尾注释被吞进名字（`[beta]  # 注释` → `beta]  # 注释`）→ 合法文件被误报 → 现在剥注释；
      · 跨行 flow 写法 `[a,\\n b]` 整表丢失 → 现在一直收集到 `]`。
    已知限制：不处理 YAML 折叠/多行字符串与键名大小写变体（本仓不出现；要完备就得引 yaml，而本脚本刻意零依赖）。
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    fm = m.group(1) if m else text.split("\n\n")[0]
    out, lines = set(), fm.split("\n")
    for i, l in enumerate(lines):
        mm = re.search(r"related_skills\s*:\s*(.*)$", l)
        if not mm:
            continue
        rest = mm.group(1).strip()
        items: list = []
        if rest.startswith("["):
            buf, j = rest, i
            while "]" not in buf and j + 1 < len(lines):
                j += 1
                buf += " " + lines[j]
            if "]" in buf:
                items = buf[buf.find("[") + 1:buf.rfind("]")].split(",")
        else:
            for nxt in lines[i + 1:]:
                if not nxt.strip() or nxt.strip().startswith("#"):
                    continue                      # 空行/注释不终止列表
                bm = re.match(r"^\s*-\s*(.+?)\s*$", nxt)
                if not bm:
                    break
                items.append(bm.group(1))
        for x in items:
            nm = _strip_comment(x).strip().strip("'\"").strip()
            if nm:
                out.add(nm)
    return out


def check_doc_consistency():
    """O5：文档一致性门禁（ROADMAP G8）。

    三类漂移在发布流程里曾经完全无人拦（实测：加第 10 个技能时，README 的
    「九个技能」/一览表行数/ROADMAP 覆盖度表/声明数全靠人肉手抄，门禁一处没拦住）：
      ① active/<技能>/ 目录数 vs README「技能一览」表的数据行数；
      ② 同一数字 vs README 正文**所有**「N 个技能」的中文数字声明；
      ③ 同一数字 vs ROADMAP 里**所有**「包内 N 个技能」声明。
    （②③ 必须遍历全部出现位置：只查第一处会让后文的陈旧声明蒙混过关。）
    另加两条指针检查：
      · `related_skills` 与反引号 `<技能>/references|scripts/...` 的目标必须能在 active/ 内解析
        （KNOWN_EXTERNAL_REFS 里的名字豁免——那是刻意的降级形态）；
      · 上游技能包惯用的 `(包名:技能名)` 行内指针视为「外包装指针」报错（前两条规则都匹配不到它）。
    """
    bad = []
    act = os.path.join(REPO, "active")
    n_dirs = len([d for d in os.listdir(act) if os.path.isdir(os.path.join(act, d))]) \
        if os.path.isdir(act) else 0

    rp = os.path.join(REPO, "README.md")
    readme = open(rp, encoding="utf-8", errors="replace").read() if os.path.isfile(rp) else ""
    seg = re.search(r"^## 技能一览(.*?)(?:^## |\Z)", readme, re.S | re.M)
    if seg is None:
        bad.append("文档计数不一致 | README 里找不到「## 技能一览」小节（无法比对技能清单）")
        n_rows, tbl_names = None, set()
    else:
        n_rows = len(re.findall(r"^\| `", seg.group(1), re.M))
        tbl_names = {m.group(1).strip() for m in re.finditer(r"^\| `([^`]+)`", seg.group(1), re.M)}
    decl, decl_unknown = _declared_skill_count(readme)

    gp = os.path.join(REPO, "ROADMAP.md")
    road = open(gp, encoding="utf-8", errors="replace").read() if os.path.isfile(gp) else ""
    road_nums = {int(x) for x in re.findall(r"包内\s*(\d+)\s*个技能", road)}

    if n_rows is not None and n_rows != n_dirs:
        bad.append(f"文档计数不一致 | README「技能一览」表 {n_rows} 行 vs active/ 实际 {n_dirs} 个技能")
    if not decl and not decl_unknown:
        bad.append("文档计数不一致 | README 正文找不到「N 个技能」声明"
                   "（接受的写法：数字紧接「个技能」，如「十个技能」；数字与「个技能」之间**不要留空格**，"
                   "否则会被当成叙述句而不是声明）")
    for u in sorted(decl_unknown):
        bad.append(f"文档计数不一致 | README 出现无法解析的技能数写法「{u}个技能」"
                   f"（CN_NUM 只覆盖一至十二；请改用阿拉伯数字写法或补映射）")
    for d in sorted(x for x in decl if x != n_dirs):
        bad.append(f"文档计数不一致 | README 正文声明 {d} 个技能 vs active/ 实际 {n_dirs} 个")
    if not road_nums:
        bad.append("文档计数不一致 | ROADMAP 找不到「包内 N 个技能」声明")
    for d in sorted(x for x in road_nums if x != n_dirs):
        bad.append(f"文档计数不一致 | ROADMAP 声明 {d} 个技能 vs active/ 实际 {n_dirs} 个"
                   f"（叙述性引用旧计数请写成 N={d}，不要复述声明句式，否则本门禁会把它一并拦下）")

    if len(SOURCES) != n_dirs:
        bad.append(f"文档计数不一致 | publish.py 的 SOURCES 白名单 {len(SOURCES)} 条 vs active/ 实际 {n_dirs} 个技能")
    pkg = {d for d in os.listdir(act) if os.path.isdir(os.path.join(act, d))} if os.path.isdir(act) else set()
    # 只比行数不够：表里把技能名写错一个字母时行数不变（G5 的残余漂移通道）。名字必须逐字一致。
    if seg is not None:                     # 小节缺失时上面已单独报过，不再逐条刷「表缺 X」噪声
        for nm in sorted(pkg - tbl_names):
            bad.append(f"文档计数不一致 | README「技能一览」表缺 {nm}（active/ 里有它）")
        for nm in sorted(tbl_names - pkg):
            bad.append(f"文档计数不一致 | README「技能一览」表多出 {nm}（active/ 里没有它；名字要逐字一致）")
    for sk in sorted(pkg):
        for r, _, fs in os.walk(os.path.join(act, sk)):
            for f in fs:
                if not f.endswith((".md", ".yaml")):
                    continue
                t = open(os.path.join(r, f), encoding="utf-8", errors="ignore").read()
                names = set(re.findall(r"`([a-z0-9][a-z0-9-]{2,})/(?:references|scripts|templates|assets)/", t))
                names |= _related_skill_names(t)
                for n in sorted(names):
                    if n == sk or n in pkg or n in KNOWN_EXTERNAL_REFS:
                        continue
                    rel = os.path.relpath(os.path.join(r, f), REPO).replace("\\", "/")
                    bad.append(f"悬空引用（目标不在包内）| {rel}: {sk} → {n}")
                # 第三种形态：上游技能包惯用的「(包名:技能名)」行内指针——既不匹配 related_skills，
                # 也不匹配反引号路径，所以前两条规则漏得过（实测：迁入的上游文本里就有
                # `(superpowers:writing-skills)`，一路通过旧门禁）。这里按已知的上游包限定词拦截，
                # 要求改写成自足表述。
                for m2 in EXT_PACK_POINTER.finditer(t):
                    rel = os.path.relpath(os.path.join(r, f), REPO).replace("\\", "/")
                    bad.append(f"外包装指针（读者无法解析，请改自足表述）| {rel}: {m2.group(0)}")
    return bad


# O6 用的规则子集：只查「泄露类」。**不查「宿主专有工具」**——publish.py 的职责就是定义
# delegate_task → spawn_subagent 这类替换与禁则，含那个名字是构造需要，不是泄露
# （该规则仍照常覆盖 active/ 与仓根文档）。
LEAK_CATEGORIES = ("本机绝对路径", "疑似密钥", "私人项目名", "私人路径", "实名", "服务器凭据")


def check_scripts_leak():
    """O6：仓根 scripts/ 的泄露面自检（ROADMAP G11 的残余形态）。

    `iter_text_files(REPO)` 只跳过**仓根第一层**的 `.git/` 与 `scripts/`——后者是必需的，因为本机
    私有脱敏表就放在那儿（门禁不能自扫自己的脱敏词表）。代价是 `scripts/` 下的脚本既不被脱敏、
    也不被扫：实测 `publish.py` 把盘符与用户名写成字面量，随公开仓一路发布，而 `--check` 报「无私人路径」。

    本检查把「泄露类」规则单独套到仓根 `scripts/` 的文本文件上：
      · 私有脱敏表（`*.local.json` / LOCAL_REDACT 本身）豁免——它按设计装着私人词表，扫它必然自报；
      · 不套「宿主专有工具」规则（理由见 LEAK_CATEGORIES 上方注释）。
    """
    rules = scan_rules()
    if rules is None:
        return ["门禁未能运行（私有脱敏表不可用）| scripts/ 泄露面自检"]
    bad = []
    root = os.path.join(REPO, "scripts")
    if not os.path.isdir(root):
        return bad
    skip = os.path.abspath(LOCAL_REDACT)
    for p in iter_text_files(root, skip_top=None):
        if os.path.abspath(p) == skip or p.endswith(".local.json"):
            continue
        rel = os.path.relpath(p, REPO).replace("\\", "/")
        t, _ = read_text(p, rel)
        if t is None:
            bad.append(f"未知编码 | {rel}")
            continue
        for i, l in enumerate(t.split("\n"), 1):
            for cat in LEAK_CATEGORIES:
                rx = rules.get(cat)
                if rx is not None and rx.search(l):
                    bad.append(f"{cat} | {rel}:{i}")
    return bad


def check(with_live: bool = True) -> int:
    rules = scan_rules()
    if rules is None:
        print("✗ 门禁未能运行（私有脱敏表不可用）→ 按 fail-closed 处理，禁止推送。")
        return 1
    bad = []
    bad += check_doc_consistency()      # O5：文档计数一致 + 悬空引用（不依赖 live 源树，克隆侧可跑）
    bad += check_scripts_leak()         # O6：仓根 scripts/ 的泄露面自检（同样不依赖 live 源树）
    if with_live:
        bad += check_line_rule_collapse()   # O1a′：整行重写塌缩（构造上丢内容）
        bad += check_publish_sync()         # O4：发布副本是否落后 live
    else:
        print("  ⚠ --check-repo-only：已跳过两项依赖 live 源树的门禁（整行规则塌缩 / 发布副本同步），"
              "本次只验证仓内内容。")
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
    print(f"✓ 门禁通过：{len(SOURCES)} 个技能；文档计数一致；无私人路径/项目名/实名/密钥/宿主专有写法；frontmatter 合法；全 UTF-8")
    return 0


if __name__ == "__main__":
    if "--check-repo-only" in sys.argv:
        sys.exit(check(with_live=False))
    if "--check" in sys.argv:
        sys.exit(check())
    for line in sync():
        print("  ", line)
    print()
    sys.exit(check())
