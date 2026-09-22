#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交接文档机检 —— 一次调用给出技能《生成流程》第 4 条的全部检查结果。

为什么存在：这些检查以前是逐项 terminal 执行的。实测三次交接会话（2026-09）里，
一次交接跑了 162~235 轮，绝大多数轮次消耗在逐条现场取证与逐项自检上，而每一轮
都要在 26 万 token 的会话末尾重发一次上下文。合并成一次调用是本技能最直接的成本杠杆。

只读：不修改被检文档，不写仓库、不产生任何文件。

覆盖技能《生成流程》第 4 条的九项检查（技能原来的手搓清单里没有任何 Goal 相关检查）：
「Goal 段四字段齐全」与「启动语句含设置 goal 模式的指令」随《Goal 段》规则一并加入；
另有编码 / 启动语句段 / 正文路径 / hex 可解析性等辅助项。goal 指令缺了，下一棒不会进入持续自驱，
卡就只是「读过一遍」。


用法：
    python check_handover.py <文档路径> [--repo R] [--allow-dirty P]...
                            [--section S]... [--expect-hash H]...
                            [--must-contain FILE] [--strict-paths] [--json]

退出码：0 = 无 FAIL（WARN 不阻断）；1 = 存在 FAIL；2 = 用法错误。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

# 技能《生成流程》第 2 条：可裁剪，但这六节必须有（任务卡交接形态）。
# Goal 段是硬要求：goal 模式（Codex /goal、Hermes /goal）每回合判「达成没」，判据就写在 goal 文本里，
# 没有 Goal 段的交接卡投给 goal 模式，等于把「什么算完成」交给接手者自己猜。
# 每项给一组同义词：真实文档常把内容并进别的节或用近义措辞，只认单一词会误报
# （实测：一份合格交接把「禁碰」写成了「口径与硬门禁」里的内容）。
DEFAULT_SECTIONS = (
    ("Goal", ("Goal", "goal", "GOAL")),
    ("状态恢复", ("状态恢复", "状态与环境", "恢复清单")),
    ("禁碰", ("禁碰", "负面知识", "禁改", "已证伪", "不可触碰", "红线")),
    ("口径", ("口径",)),
    ("门禁", ("门禁", "验收", "质检", "校验")),
    ("任务卡", ("任务卡", "任务清单", "下一步", "执行清单")),
)

# 服务器/远端的路径不可能存在于本机磁盘：不计入 FAIL，只提示（技能允许交接物写服务器路径）。
REMOTE_PREFIX = ("/home/", "/tmp/", "/mnt/", "/opt/", "/var/", "/root/",
                 "/data/", "/srv/", "/etc/", "/usr/")

PLACEHOLDER_RES = (re.compile(r"<<[^>]{0,120}>>"), re.compile(r"待填"))
URL_RX = re.compile(r"https?://\S+")
PATH_RX = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s`'\"()\[\]，。；：、,;]*"
    r"|~[\\/][^\s`'\"()\[\]，。；：、,;]*"
    r"|/(?:Users|home|mnt|opt|tmp|var)/[^\s`'\"()\[\]，。；：、,;]*)"
)
# 词边界用「前后不是字母数字」而不是 \b：汉字与十六进制字符在 Python 里都属 \w，
# 于是「提交5f3a9c1」这种紧贴汉字的 hash 会被 \b 漏掉（实测）。
HASH_RX = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{7,40}(?![0-9A-Za-z])")
# 《Goal 段》四字段（同义词命中即算，宽容优先：宁可漏报也不要逼人改字段名）
# 标题定义：只认 1-3 级标题（`(?!#)` 排掉 #### 及更深层级），切段与判标题共用一份 ——
# 两套定义会漂移：实测过 `#### 备注` 被当成标题、还混进「顶层节标题」检查。
HEAD_LINE_RX = re.compile(r"^#{1,3}(?!#)[ \t]*(?=\S)")   # 裸 `##`（无标题文本）不算标题，与 HEAD_RX 一致
HEAD_RX = re.compile(r"^#{1,3}(?!#)[ \t]*(?:\d+[.、)]\s*)?(?=\S)(.+)$", re.M)   # (?=\S) 与 HEAD_LINE_RX 同口径：裸 `## ` / `##\t` 也不算标题，否则两套定义漂移
# 《Goal 段》四字段（同义词命中即算，宽容优先：宁可漏报也不要逼人改字段名；
# 中英文冒号写法都收，因为「目标：…」「第一步：…」是自然写法）
# 《Goal 段》四字段：**键值行**口径 —— 行首是字段名（可带 -、*、**、` 前缀）后紧跟冒号才算命中。
# 为什么不用「段内任意子串命中」：一句「本段只是说明：Goal（objective）/ done_when / … 这四个字段」的
# 说明段会整段假通过（实测）。英文与中文写法（目标：/完成判据：/第一步：）同等对待。
GOAL_FIELDS = (
    ("objective", ("goal（objective）", "goal(objective)", "objective", "目标")),
    ("done_when", ("done_when", "done when", "完成判据", "完成条件", "达成判据", "验收判据")),
    ("boundaries", ("boundaries", "边界", "不做", "不许", "禁")),
    ("first_action", ("first_action", "第一个动作", "首个动作", "起手动作", "第一步动作",
                      "第一步", "接手动作", "第一动作")),
)
# 「设置 goal 模式」的**命令式**表述。描述式（「本段由 goal 模式逐回合判定」）与否定式
# （「不要打开 goal 模式」）都不算 —— 两者实测都能骗过宽松匹配。语序双向收：`/goal X`、
# `打开 goal 模式`、`goal 模式已打开`。
GOAL_CMD_RX = re.compile(
    r"(/\s*goal\b"
    r"|(?:打开|开启|进入|设置|设为|注册|启动|先开)\s*goal"
    r"|goal\s*(?:模式|state|状态)?\s*(?:已|现在|也)?\s*(?:打开|开启|设置|设为|注册|启动|生效))",
    re.I)
# 否定词与 goal 之间若出现「忘/忘记/遗漏」，那是**提醒式**要求（「别忘了打开 goal 模式」），
# 不是否定 —— 用负向断言把它排除，否则这三句会被误判成「没有设置 goal 的指令」（实测）。
GOAL_NEG_RX = re.compile(
    r"(不要|不用|无需|别|禁止|勿|不需要)"
    r"(?![^。；\n]{0,8}(?:忘|遗漏|漏|跳过)[^。；\n]{0,10}goal)"
    r"[^。；\n]{0,10}goal", re.I)


def _goal_cmd(text: str):
    """找「设置 goal 模式」的命令式表述（先剔掉否定式片段，避免「不要打开 goal 模式」假通过）。"""
    return GOAL_CMD_RX.search(GOAL_NEG_RX.sub(" ", text))


def _goal_field_hits(block: str) -> tuple[int, list[str]]:
    """按「行首 = 字段名 + 冒号」数四字段 → (命中数, 缺失字段名)。"""
    hit: set[str] = set()
    for line in block.splitlines():
        s = line.strip().lstrip("-*>#` \t").strip()
        if not s:
            continue
        for name, syns in GOAL_FIELDS:
            if name in hit:
                continue
            for syn in syns:
                if s.lower().startswith(syn.lower()):
                    rest = s[len(syn):].lstrip("）)(").lstrip("*` \t").strip()
                    if rest[:1] in (":", "："):
                        hit.add(name)
                        break
    return len(hit), [n for n, _ in GOAL_FIELDS if n not in hit]
START_HINT = re.compile(
    r"(启动语句|可粘贴|单条消息|交给下一|给下一棒|给下一个|下一步指令|接手指令|待粘贴|给 Codex)"
)
SECTION_RX = HEAD_RX        # 同一份标题定义（两套会漂移，见上）


class Report:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []      # (level, name, detail)

    def add(self, level: str, name: str, detail: str = "") -> None:
        self.items.append((level, name, detail))

    def show(self, as_json: bool) -> int:
        fails = [i for i in self.items if i[0] == "FAIL"]
        if as_json:
            print(json.dumps({
                "fails": len(fails),
                "items": [{"level": l, "check": n, "detail": d} for l, n, d in self.items],
            }, ensure_ascii=False, indent=2))
        else:
            for level, name, detail in self.items:
                mark = {"PASS": "  PASS", "FAIL": "  FAIL", "WARN": "  WARN", "INFO": "  info"}[level]
                print(f"{mark}  {name}" + (f"\n         {detail}" if detail else ""))
            print(f"\n机检: {'OK（无 FAIL）' if not fails else f'{len(fails)} 项 FAIL'}"
                  f"  [{sum(1 for i in self.items if i[0] == 'WARN')} warn]")
        return 1 if fails else 0


def _sh(cmd: list[str], cwd: str | None = None):
    """跑命令，**固定按 UTF-8 解码**。

    为什么必须写死 encoding：Windows 中文 locale 下 Python 默认用 cp936 解码子进程输出，
    而 git 输出的是 UTF-8（仓库里有中文名文件就解不开）⇒ p.stdout 变 None ⇒ 后面 split 崩溃，
    九项检查一项都出不来（实测）。errors="replace" 保证永不因解码失败炸掉整次机检。
    """
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as exc:                                  # noqa: BLE001
        return 1, "", str(exc)


def _start_block(text: str) -> str | None:
    """取「启动语句」段。

    为什么是「全体候选 + 资格判定 + 打分」而不是「取第一个含提示词的行 / 标题优先」：
    正文里一句「陷阱：启动语句里的路径必须逐字一致」、或一个更靠后的「## 12 给下一个 agent 的
    任务卡」标题，都能把段身份抢走，进而误报「启动语句段不含路径 / 不含 goal 指令」；
    反过来，真段标题只写「## 起步」时又会被彻底漏掉（三类都实测过）。

    资格：含提示词（启动语句/可粘贴/给下一棒…）的段 → 需含 goal 命令或含**存在的**本地路径；
          不含提示词的标题段 → 必须含 goal 命令（才不会被「状态恢复」这类含路径的节冒充）。
    打分排序：含 goal 命令 +4 / 含存在本地路径 +2 / 含提示词 +2 / 段长 > 40 +1 / 本身是标题 +1，同分取靠前者。

    无任何合格候选时返回 None —— **不回退到全文**：回退会让「启动语句路径检查」退化成
    全文档路径检查，把示例路径误判成缺失。
    """
    lines = text.splitlines()
    mask_lines = _mask_fences(text).splitlines()
    heads: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        if not HEAD_LINE_RX.match(mask_lines[i]):
            continue
        end = len(lines)
        for j in range(i + 1, len(lines)):
            if HEAD_LINE_RX.match(mask_lines[j]):
                end = j
                break
        heads.append((i, end, "\n".join(lines[i:end])))

    def parts(block: str) -> tuple[bool, bool]:
        has_cmd = bool(_goal_cmd(block))
        has_path = bool([x for x in _paths_in(block)
                         if not x.startswith(REMOTE_PREFIX)
                         and os.path.exists(os.path.expanduser(x))])
        return has_cmd, has_path

    scored: list[tuple[int, int, str]] = []
    for i, _end, block in heads:
        has_cmd, has_path = parts(block)
        if not (has_cmd or has_path):
            continue
        if not (START_HINT.search(lines[i]) or has_cmd):
            continue
        s = 0
        s += 4 if has_cmd else 0
        s += 2 if has_path else 0
        s += 2 if START_HINT.search(lines[i]) else 0
        s += 1 if len(block) > 40 else 0
        # 标题就是「启动语句 / 可粘贴 / 接手指令…」的段才是真段；「陷阱/说明/注意/反例」类标题
        # 常只是**引用** /goal 举例（实测：陷阱节 + 存在路径 + 提到 /goal 能与真段同分并靠前抢先，
        # 于是四项启动语句检查全评在错段上）——一个加权、一个降权把它压下去。
        # 编号可能写作「## 12 启动语句」（空格分隔，SKILL.md 骨架自己的风格）或「## 12. 启动语句」，
        # 标点必须是可选的 —— 旧写法要求编号带 . 、 ) ，导致真段的 +3 从不触发（实测）。
        is_start = bool(re.match(
            r"^#{1,3}[ \t]*(?:\d+[.、)]?[ \t]*)?(启动语句|可粘贴|接手指令|给下一棒|给下一个)", lines[i]))
        s += 3 if is_start else 0
        # 降权只针对「本身不是启动语句段」的标题：真段标题里写「（注意：路径逐字核对）」是正常的，
        # 不该被扣分（否则与陷阱节同分、又靠前胜，回到错段）。
        # 降权分两档：不是启动语句段的标题 → 任一陷阱类词都扣；
        # 标题本身以启动语句开头 → 只扣强反例标记（「## 3 启动语句反例（勿照抄）」这种段会
        # 自己含 /goal 举例 + 存在路径，不扣就会与真段同分靠前胜，把检查评在错段上）；
        # 「（注意：路径需逐字核对）」这类正常限定不扣。
        if re.search(r"(陷阱|反例|说明|不要做|别照抄)" if is_start
                     else r"(陷阱|说明|注意|反例|不要做|别照抄)", lines[i]):
            s -= 3
        scored.append((s, i, block))
    scored.sort(key=lambda c: (-c[0], c[1]))
    if scored:
        return scored[0][2]

    # 无标题可用：退回含提示词的正文行（老口径），同样要求含 goal 命令或存在的本地路径
    for i, line in enumerate(lines):
        if not START_HINT.search(line) or HEAD_LINE_RX.match(line):
            continue
        has_cmd, has_path = parts("\n".join(lines[i:]))
        if has_cmd or has_path:
            return "\n".join(lines[i:])
    return None



def _mask_fences(text: str) -> str:
    """把 ``` / ~~~ 围栏内的行替换成等长空白（保留换行与偏移）。

    为什么：围栏里的 `# 核验命令` 是一行 bash 注释，不是标题。不掩码的话它会被当标题，
    把所在段拦腰截断（Goal 段里嵌一个 bash 示例就足以让四字段判缺，实测假 FAIL），
    SECTION_RX 还会把注释算进「文档节标题」。等长替换保证标题搜索的偏移仍对应原文。
    """
    out = list(text)
    in_fence = False
    pos = 0
    for line in text.splitlines(keepends=True):
        marker = line.lstrip().startswith("```") or line.lstrip().startswith("~~~")
        if marker:
            in_fence = not in_fence
        if marker or in_fence:
            for k in range(pos, pos + len(line)):
                if out[k] not in ("\n", "\r"):
                    out[k] = " "
        pos += len(line)
    return "".join(out)


def _goal_sections(text: str) -> list[tuple[str, str, int]]:
    """切出所有「标题含 goal」的候选段 → [(标题, 段文本, 键值字段命中数)]。

    为什么不是「取第一个命中」：标题只是含 goal 的说明段（如「## 0 关于 goal 模式的说明」）
    会截走 Goal 段身份，把真 Goal 段的四字段判成全缺（实测假 FAIL）。改成全体候选打分、
    取命中最多者，并列时标题里 goal 位置最靠前者优先。
    """
    heads = [(m.start(), m.group(1)) for m in HEAD_RX.finditer(_mask_fences(text))]
    out: list[tuple[str, str, int]] = []
    for i, (pos, title) in enumerate(heads):
        if not re.search(r"[Gg]oal", title):
            continue
        end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        block = text[pos:end]
        out.append((title, block, _goal_field_hits(block)[0]))
    return out



def _paths_in(block: str) -> list[str]:
    out = []
    for m in PATH_RX.finditer(block):
        s = m.group(0).rstrip(".,;:`'\"）)】")
        if s and not URL_RX.match(s):
            out.append(s)
    return sorted(set(out))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="交接文档机检（只读）")
    ap.add_argument("doc", help="交接文档路径")
    ap.add_argument("--repo", help="git 仓库路径：核验 hash 存在性 + dirty 白名单")
    ap.add_argument("--allow-dirty", action="append", default=[], metavar="PATH",
                    help="允许出现的仓库相对路径：文件须精确匹配，目录名可覆盖其下级，可重复")
    ap.add_argument("--section", action="append", default=[], metavar="KW",
                    help="必需的顶层节标题关键词，可重复（默认：Goal/状态恢复/禁碰/口径/门禁/任务卡）")
    ap.add_argument("--expect-hash", action="append", default=[], metavar="HASH",
                    help="必须存在于 --repo 的 commit hash，可重复")
    ap.add_argument("--must-contain", metavar="FILE",
                    help="文本文件，每行一个必须出现在文档里的字面串（关键数字清单）")
    ap.add_argument("--strict-paths", action="store_true",
                    help="启动语句之外的路径不存在也判 FAIL（默认只 WARN）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    r = Report()
    p = pathlib.Path(args.doc)
    if not p.is_file():
        print(f"错误：文档不存在 {p}", file=sys.stderr)
        return 2
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        r.add("FAIL", "编码可读（UTF-8）", str(exc))
        return r.show(args.json)
    r.add("PASS", "编码可读（UTF-8）")

    # 1) 行尾：交接物统一 LF
    n_crlf = raw.count(b"\r\n")
    r.add("PASS" if n_crlf == 0 else "FAIL", "行尾 CRLF = 0",
          "" if n_crlf == 0 else f"发现 {n_crlf} 处 CRLF")

    # 2) 占位符 / 待填残量
    left = [m.group(0) for rx in PLACEHOLDER_RES for m in rx.finditer(text)]
    r.add("PASS" if not left else "FAIL", "占位符 / 「待填」残量 = 0",
          "" if not left else f"{len(left)} 处：" + ", ".join(left[:8]))

    # 3) 必需节标题（同义词命中即算，见 DEFAULT_SECTIONS 注释）
    titles = [m.group(1) for m in SECTION_RX.finditer(_mask_fences(text))]
    syn = dict(DEFAULT_SECTIONS)
    want = list(args.section) or [k for k, _ in DEFAULT_SECTIONS]
    missing = [w for w in want
               if not any(any(s in t for s in syn.get(w, (w,))) for t in titles)]
    r.add("PASS" if not missing else "FAIL", f"顶层节标题齐全（{len(want)} 项）",
          "" if not missing else "缺：" + ", ".join(missing)
          + "（若该内容已并入其他节，用 --section 指定实际标题关键词）")
    r.add("INFO", f"文档节标题 {len(titles)} 个", " / ".join(t[:28] for t in titles[:14]))

    # 4) 启动语句里的路径必须逐字存在于磁盘
    sb = _start_block(text)
    if sb is None:
        r.add("FAIL", "启动语句段存在（含绝对路径）",
              "未识别到启动语句段。技能《内容必备》第 8 条要求文首给一段可粘贴的单条消息"
              "（含交接文档与规格文件的绝对路径）。若措辞不同，请让该小节标题或首行含"
              "「启动语句 / 可粘贴 / 给下一棒」等词，或在本脚本 START_HINT 里补词。")
        in_block = []
    else:
        all_p = _paths_in(sb)
        remote = [x for x in all_p if x.startswith(REMOTE_PREFIX)]
        in_block = [x for x in all_p if not x.startswith(REMOTE_PREFIX)]
        if not all_p:
            r.add("FAIL", "启动语句段含绝对路径",
                  "识别到启动语句段，但里面没有任何路径——新执行者据此无法定位文件。")
        else:
            gone = [x for x in in_block if not os.path.exists(os.path.expanduser(x))]
            r.add("PASS" if not gone else "FAIL", "启动语句里的本地路径在磁盘上存在",
                  f"检查 {len(in_block)} 条" + ("" if not gone else "；不存在：" + ", ".join(gone[:6])))
            if remote:
                r.add("INFO", f"启动语句段里的服务器/远端路径（{len(remote)} 条，不在本机核验）",
                      ", ".join(remote[:6]))

    # 4b) Goal 段：标题含 Goal（候选打分，见 _goal_sections）+ 四字段按**键值行**命中
    cands = _goal_sections(text)
    goal_block = ""
    if not cands:
        r.add("FAIL", "Goal 段存在（标题含 Goal）",
              "技能《Goal 段》要求文首给一个标题含 Goal 的段，四字段照写："
              "Goal（objective）/ done_when / boundaries / first_action（键值行：字段名 + 冒号）。"
              "缺了它，goal 模式判不出「什么算完成」。")
    else:
        _, (title, goal_block, _score) = sorted(
            enumerate(cands),
            key=lambda kv: (-kv[1][2], kv[1][0].lower().find("goal"), kv[0]))[0]
        n_hit, miss = _goal_field_hits(goal_block)
        detail = "" if not miss else ("缺：" + ", ".join(miss)
                                      + "；选定段「" + title.strip() + "」（候选 " + str(len(cands)) + " 段）")
        r.add("PASS" if n_hit == len(GOAL_FIELDS) else "FAIL",
              "Goal 段四字段齐全（objective / done_when / boundaries / first_action）", detail)

    # 4c) 启动语句里必须有「设置 goal 模式」的**命令式**指令（描述式 / 否定式 / 写在别节都不算）
    if sb is not None:
        scope, where, lvl = sb, "启动语句段", "PASS"
    else:
        scope, where, lvl = goal_block, "Goal 段（启动语句段未识别，位置无法确认）", "WARN"
    if _goal_cmd(scope):
        r.add(lvl, "启动语句含设置 goal 模式的指令（" + where + "）")
    else:
        r.add("FAIL", "启动语句含设置 goal 模式的指令",
              "启动语句里要写「把《Goal 段》的 objective 原文设为 goal」这个动作：Codex 发 "
              "`/goal <objective 原文>`；Hermes 用 `/goal` 或写 goal 状态（contract 五字段）。"
              "只在正文里描述「goal 模式会逐回合判定」不算。")


    # 5) 其余位置的路径：默认只提醒
    others = [x for x in _paths_in(text)
              if x not in set(in_block) and not x.startswith(REMOTE_PREFIX)]
    gone_o = [x for x in others if not os.path.exists(os.path.expanduser(x))]
    if gone_o:
        r.add("FAIL" if args.strict_paths else "WARN",
              "正文其余路径（非启动语句）", f"{len(gone_o)} 条不存在：" + ", ".join(gone_o[:6]))

    # 6) git：hash 语义 + dirty 白名单
    if args.repo:
        rp = pathlib.Path(args.repo)
        if not (rp / ".git").exists():
            r.add("FAIL", "git 仓库可用", f"{rp} 不是仓库根（缺 .git）")
        else:
            r.add("PASS", "git 仓库可用")
            for h in args.expect_hash:
                rc, _, _ = _sh(["git", "cat-file", "-e", f"{h}^{{commit}}"], cwd=str(rp))
                r.add("PASS" if rc == 0 else "FAIL", f"hash 存在：{h}")
            auto = sorted(set(HASH_RX.findall(text)))
            bad_auto = []
            for h in auto:
                # 纯数字串（日期 20260916、编号）不可能是 git hash，跳过以免噪声
                if len(h) < 7 or not re.search(r"[a-f]", h):
                    continue
                rc, _, _ = _sh(["git", "cat-file", "-e", f"{h}^{{commit}}"], cwd=str(rp))
                if rc != 0:
                    bad_auto.append(h)
            if auto:
                skipped = [h for h in auto if len(h) < 7 or not re.search(r"[a-f]", h)]
                r.add("INFO" if not bad_auto else "WARN",
                      f"文档内 hex 串（{len(auto)} 个，其中纯数字/短串 {len(skipped)} 个已跳过核验）",
                      "" if not bad_auto else "仓库里找不到（可能是别类编号，人工确认）：" + ", ".join(bad_auto[:8]))
            # -z + core.quotepath=false：默认的 `status --short` 会把中文路径输出成
            # "\350\277\233…" 转义串，于是「默认放过本文件自身」对中文名交接卡完全失效
            # （交接卡恰恰是中文名），且 --allow-dirty <中文路径> 也救不回来（实测假 FAIL）。
            # -uall：未跟踪目录不折叠成 `dir/` 一条，否则 --allow-dirty <目录内文件> 永远命中不了。
            rc, out, err = _sh(["git", "-c", "core.quotepath=false", "status", "--porcelain",
                                "-z", "-uall"], cwd=str(rp))
            if rc != 0:
                # 失败时输出为空 ⇒ 旧版会把「啥都读不到」当成「没有任何 dirty」直接给绿灯（实测）。
                r.add("FAIL", "git status 可用（dirty 白名单前提）",
                      (err or out or "git status 失败").strip().splitlines()[0][:160]
                      + "（仓库不可读/不是仓库时不允许把白名单判成 PASS）")
            dirty: list[str] = []
            items = [x for x in out.split("\0") if x]
            k = 0
            while k < len(items):
                it = items[k]
                if not re.match(r"^[ MADRCU?!]{2} ", it):
                    k += 1                                  # rename/copy 的第二段是裸原名，跳过
                    continue
                xy, path = it[:2], it[3:].replace("\\", "/").rstrip("/")
                if path:
                    dirty.append(path)
                k += 2 if ("R" in xy or "C" in xy) else 1    # R/C 的下一条是原名

            def _rel(x: str) -> str:
                """把 --doc / --allow-dirty 的路径归一成仓库相对路径（git status 给的是相对的）。

                用 resolve 统一处理绝对/相对：相对路径按调用者 cwd 解析，覆盖「cwd 不在仓库根、
                doc 写成 repo/卡.md」这种实际用法（旧版只认绝对路径，实测假 FAIL）。
                """
                root_abs = str(rp.resolve()).replace("\\", "/").rstrip("/")
                s = str(x).strip().strip('"').replace("\\", "/")
                try:
                    ab = str(pathlib.Path(s).resolve()).replace("\\", "/")
                except Exception:                              # noqa: BLE001
                    ab = ""
                if ab.lower().startswith(root_abs.lower() + "/"):
                    return ab[len(root_abs) + 1:].rstrip("/")
                if ab.lower() == root_abs.lower():
                    return "."
                return s.lstrip("./").rstrip("/")

            # 白名单是**追加**语义，且默认永远放过本文件自身（它本来就是要被写进去的那个）。
            allow = [_rel(p)] + [_rel(a) for a in args.allow_dirty]
            # 路径分量比较：`--allow-dirty a/b` 不该连 `a/bc` 一起放过（旧版用裸 startswith）。
            whole = [a for a in allow if a in ("", ".", "/")]
            if whole:
                r.add("WARN", "dirty 白名单含「整仓」项",
                      "--allow-dirty 归一后为空或 `.`（收到 " + str(len(whole))
                      + " 项）：按整仓放过处理，白名单等于失效")
            extra = [] if whole else [
                d for d in dirty
                if not any(a and (d == a.rstrip("/") or d.startswith(a.rstrip("/") + "/")) for a in allow)]
            if rc != 0:
                r.add("FAIL", "git 只新增目标 untracked 文件（dirty 白名单）",
                      "无法判定：git status 未成功执行")
            else:
                r.add("PASS" if not extra else "FAIL",
                      "git 只新增目标 untracked 文件（dirty 白名单）",
                      "" if not extra else "白名单外：" + ", ".join(extra[:8]))
    else:
        r.add("WARN", "git 检查", "未给 --repo，hash 语义与 dirty 白名单未检查")

    # 7) 关键数字清单必须命中
    if args.must_contain:
        mf = pathlib.Path(args.must_contain)
        if not mf.is_file():
            r.add("FAIL", "关键数字清单可读", f"{mf} 不存在")
        else:
            need = [l.strip() for l in mf.read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.startswith("#")]
            miss = [n for n in need if n not in text]
            r.add("PASS" if not miss else "FAIL", f"关键数字命中（{len(need)} 项）",
                  "" if not miss else f"{len(miss)} 项未出现：" + ", ".join(miss[:8]))
    else:
        r.add("WARN", "关键数字命中", "未给 --must-contain，数字溯源未检查")

    return r.show(args.json)


if __name__ == "__main__":
    sys.exit(main())
