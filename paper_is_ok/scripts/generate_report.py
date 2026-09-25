#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate_report.py — 依据标注计算加权查重率，生成带颜色高亮的 查重报告.tex。

用法:
    python generate_report.py paper_blocks.json annotations.json -o 查重报告.tex
    python generate_report.py paper_blocks.json ann1.json ann2.json -o 查重报告.tex --compile

- 支持多个标注文件，自动合并（skipped 拼接、coverage/paper 取最后）。
- --compile: 本机存在 xelatex 时编译生成 查重报告.pdf。

查重率公式: Σ(片段非空白字符数 × 等级权重) ÷ 全文非空白字符数 × 100
权重: minor=0.2, moderate=0.3, severe=0.5
"""
import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

WEIGHTS = {"minor": 0.2, "moderate": 0.3, "severe": 0.5}
LEVEL_NAMES = {"minor": "轻微疑似", "moderate": "中度疑似", "severe": "严重疑似"}
LEVEL_COLORS = {"minor": "cminor", "moderate": "cmoderate", "severe": "csevere"}
LEVEL_ORDER = ["severe", "moderate", "minor"]

MAX_CJK_PER_BOX = 6          # 高亮分片的最大中文字符数（保证可断行）
EXCERPT_SHOW = 80            # 明细表中论文片段显示长度
MATCH_SHOW = 50              # 明细表中来源原句显示长度

# 不参与查重的章节（对照知网口径：检测总字符数通常去除目录、参考文献、致谢等）
EXCLUDE_SEC = re.compile(
    r"^(目录|图表目录|插图目录|表格目录|插图和表格清单|参考文献|references?"
    r"|bibliography|works\s+cited|致谢|致\s*谢|后记|鸣谢|acknowledg"
    r"|附录|appendices?|作者声明|原创性声明|独创性声明"
    r"|学位论文版权使用授权|declaration|list of (figures|tables|abbreviations|symbols))",
    re.I)

warnings = []


def warn(msg):
    warnings.append(msg)
    print("WARNING: %s" % msg)


# ---------------------------------------------------------------- 工具函数

def count_chars(text):
    return len(re.sub(r"\s+", "", text))


# 数学区域（公式以 LaTeX 源码形式存于 blocks 文本中，渲染时原样保留）
_MATH_ENV_SRC = (r"equation\*?|align\*?|alignat\*?|gather\*?|multline\*?"
                 r"|eqnarray\*?|split|cases|flalign\*?|math|displaymath")
MATH_PAT = re.compile(
    r"(\\begin\{(?P<env>" + _MATH_ENV_SRC + r")\}.*?\\end\{(?P=env)\}"
    r"|\$\$.*?\$\$"
    r"|\\\[.*?\\\]"
    r"|\\\((?:[^\\]|\\.)*?\\\)"
    r"|\$[^$\n]*?\$)", re.S)


def iter_segments(text):
    """把文本切分为 (是否公式, 片段) 序列；公式片段原样保留。"""
    pos = 0
    for m in MATH_PAT.finditer(text):
        if m.start() > pos:
            yield False, text[pos:m.start()]
        yield True, m.group(0)
        pos = m.end()
    if pos < len(text):
        yield False, text[pos:]


def norm(text):
    return re.sub(r"\s+", "", text)


def esc(text):
    """LaTeX 特殊字符转义。"""
    text = text.replace("\\", r"\textbackslash{}")
    for a, b in [("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
                 ("_", r"\_"), ("{", r"\{"), ("}", r"\}"),
                 ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}")]:
        text = text.replace(a, b)
    return text


def truncate(text, n):
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[:n] + "……"


def split_chunks(text, max_cjk=MAX_CJK_PER_BOX):
    """把片段切成短分片：中文每 max_cjk 字一片，英文单词独立成片。
    相邻 colorbox 之间由调用者插入 \\hspace{0pt} 提供断行点。"""
    tokens = re.findall(r"[A-Za-z0-9]+(?:[-.'][A-Za-z0-9]+)*|\s+|.", text)
    chunks, cur, cjk = [], "", 0
    for tok in tokens:
        if tok.isspace():
            if cur:
                chunks.append(cur)
                cur, cjk = "", 0
            continue
        cur += tok
        if re.match(r"[A-Za-z0-9]", tok):
            chunks.append(cur)
            cur, cjk = "", 0
        else:
            cjk += 1
            if cjk >= max_cjk:
                chunks.append(cur)
                cur, cjk = "", 0
    if cur:
        chunks.append(cur)
    return chunks


# ---------------------------------------------------------------- 数据加载

def locate_segment(block_text, start, end, excerpt_paper):
    """校验/修复偏移量；失败返回 None。"""
    n = len(block_text)
    if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= n:
        if excerpt_paper and norm(block_text[start:end]) != norm(excerpt_paper):
            warn("偏移量与 excerpt_paper 不一致，以偏移量为准: block[%d:%d] "
                 "vs《%s》" % (start, end, truncate(excerpt_paper, 30)))
        return start, end
    if excerpt_paper:
        ce = norm(excerpt_paper)
        if ce:
            condensed = norm(block_text)
            idxmap = [i for i, ch in enumerate(block_text) if not ch.isspace()]
            i = condensed.find(ce)
            if i >= 0:
                return idxmap[i], idxmap[i + len(ce) - 1] + 1
            warn("无法在块内定位 excerpt_paper《%s》，该条标注被丢弃"
                 % truncate(excerpt_paper, 30))
            return None
    warn("偏移量非法(start=%r,end=%r)且无 excerpt_paper 可回退，该条标注被丢弃"
         % (start, end))
    return None


def is_excluded(block):
    return bool(EXCLUDE_SEC.search(block.get("section", "")))


def load_annotations(paths):
    anns, skipped, coverage, paper = [], [], {}, {}
    for p in paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        for a in data.get("annotations", []):
            a["_src_file"] = str(p)
            anns.append(a)
        skipped.extend(data.get("skipped", []))
        if isinstance(data.get("coverage"), dict):
            coverage = data["coverage"]
        if isinstance(data.get("paper"), dict):
            paper = data["paper"]
    return anns, skipped, coverage, paper


def resolve_annotations(blocks, anns, excluded_ids=frozenset()):
    block_map = {b["id"]: b for b in blocks}
    resolved = []
    for a in anns:
        bid = a.get("block_id")
        b = block_map.get(bid)
        if b is None:
            warn("block_id=%r 不存在（来自 %s），该条标注被丢弃"
                 % (bid, a.get("_src_file", "?")))
            continue
        if bid in excluded_ids:
            warn("block=%s 属于不参与查重的章节（目录/参考文献/致谢/附录等），"
                 "该条标注被丢弃" % bid)
            continue
        level = a.get("level")
        if level not in WEIGHTS:
            warn("level=%r 非法，该条标注被丢弃" % (level,))
            continue
        loc = locate_segment(b["text"], a.get("start"), a.get("end"),
                             a.get("excerpt_paper"))
        if loc is None:
            continue
        resolved.append({"block": b, "start": loc[0], "end": loc[1],
                         "level": level, "quote": bool(a.get("quote")),
                         "source": a.get("source", {}),
                         "matched": a.get("matched_excerpt", ""),
                         "reason": a.get("reason", "")})
    # 按 (块顺序, start) 排序并修剪重叠
    order = {b["id"]: i for i, b in enumerate(blocks)}
    resolved.sort(key=lambda r: (order[r["block"]["id"]], r["start"]))
    trimmed = []
    for r in resolved:
        if trimmed and trimmed[-1]["block"]["id"] == r["block"]["id"] \
                and r["start"] < trimmed[-1]["end"]:
            warn("标注重叠已修剪: block=%s 原区间[%d,%d)"
                 % (r["block"]["id"], r["start"], r["end"]))
            r["start"] = trimmed[-1]["end"]
            if r["start"] >= r["end"]:
                continue
        trimmed.append(r)
    for i, r in enumerate(trimmed, 1):
        r["mark"] = i
    return trimmed


# ---------------------------------------------------------------- 统计

def compute_stats(total_chars, resolved):
    stats = {lv: {"count": 0, "chars": 0, "weighted": 0.0}
             for lv in LEVEL_ORDER}
    quote_chars = 0
    quote_weighted = 0.0
    for r in resolved:
        seg = count_chars(r["block"]["text"][r["start"]:r["end"]])
        lv = r["level"]
        stats[lv]["count"] += 1
        stats[lv]["chars"] += seg
        stats[lv]["weighted"] += seg * WEIGHTS[lv]
        if r["quote"]:
            quote_chars += seg
            quote_weighted += seg * WEIGHTS[lv]
    total_weighted = sum(stats[lv]["weighted"] for lv in LEVEL_ORDER)
    rate = total_weighted / total_chars * 100 if total_chars else 0.0
    rate_no_quote = ((total_weighted - quote_weighted) / total_chars * 100
                     if total_chars else 0.0)
    quote_rate = quote_chars / total_chars * 100 if total_chars else 0.0
    for lv in LEVEL_ORDER:
        stats[lv]["contrib"] = (stats[lv]["weighted"] / total_chars * 100
                                if total_chars else 0.0)
    return (stats, rate, total_weighted, rate_no_quote, quote_chars,
            quote_rate)


# ---------------------------------------------------------------- LaTeX 渲染

PREAMBLE = r"""\documentclass[UTF8,12pt]{ctexart}
\usepackage[a4paper,margin=2.4cm]{geometry}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{bm}
\usepackage{mathtools}
\usepackage{xcolor}
\usepackage{longtable}
\usepackage{booktabs}
\usepackage{array}
\definecolor{cminor}{RGB}{255,244,120}
\definecolor{cmoderate}{RGB}{255,190,120}
\definecolor{csevere}{RGB}{255,120,120}
\newcommand{\flagminor}[1]{\colorbox{cminor}{#1}}
\newcommand{\flagmoderate}[1]{\colorbox{cmoderate}{#1}}
\newcommand{\flagsevere}[1]{\colorbox{csevere}{#1}}
\newcommand{\flagmark}[2]{\textsuperscript{\textcolor{#1}{\textbf{[#2]}}}}
\newcolumntype{L}[1]{>{\raggedright\arraybackslash}p{#1}}
\newcolumntype{R}[1]{>{\raggedleft\arraybackslash}p{#1}}
\setlength{\parindent}{2em}
\setlength{\tabcolsep}{4pt}
\begin{document}
"""

RUBRIC_RECAP = [
    ("严重疑似（红）", "0.5",
     "连续重合不低于30字符；或整段同构复写/拼接复写（R1a--R1c）"),
    ("中度疑似（橙）", "0.3",
     "连续重合15--29字符；或单句同构、短句连续命中（R2a--R2c）"),
    ("轻微疑似（黄）", "0.2",
     "连续重合8--14字符；或观点高度相近（R3a--R3b）；规范引用（R3c）标记"
     "quote=true，不计入查重率"),
    ("无疑似（不标记）", "0",
     "表述原创或已充分改写，不标记、不计入查重率"),
]

FORMULA_TEX = (r"$\text{查重率}=\dfrac{\sum(\text{片段字符数}\times\text{权重})}"
               r"{\text{检测总字符数}}\times 100$")


def render_plain(text):
    """未标记文本：普通文字转义，公式原样输出。"""
    return "".join(seg if is_math else esc(seg)
                   for is_math, seg in iter_segments(text))


def render_piece(level, text, mark):
    """标记片段：文字分片涂色，行内公式随片涂色（原样），
    display 公式环境独立成行原样输出（不置于 colorbox 内）。"""
    out = []
    buf = ""

    def flush():
        nonlocal buf
        if buf:
            out.append(r"\hspace{0pt}".join(
                r"\colorbox{%s}{%s}" % (LEVEL_COLORS[level], esc(c))
                for c in split_chunks(buf)))
            buf = ""

    for is_math, seg in iter_segments(text):
        if not is_math:
            buf += seg
            continue
        flush()
        if seg.lstrip().startswith("\\begin"):
            out.append("\n\n" + seg + "\n\n")
        else:
            out.append(r"\colorbox{%s}{%s}" % (LEVEL_COLORS[level], seg))
    flush()
    if mark is not None:
        out.append(r"\flagmark{%s}{%d}" % (LEVEL_COLORS[level], mark))
    return "".join(out)


def render_fulltext(blocks, resolved):
    by_block = {}
    for r in resolved:
        by_block.setdefault(r["block"]["id"], []).append(r)
    out = [r"\section*{五、正文高亮重现}",
           r"\noindent 图例：",
           r"\flagminor{轻微疑似(黄)} \flagmoderate{中度疑似(橙)} "
           r"\flagsevere{严重疑似(红)}；编号 [n] 对应疑似明细表。数学公式以 "
           r"LaTeX 源码完整保留并参与比对；display 公式不涂色、原样排版。\par\bigskip"]
    prev_sec = None
    for b in blocks:
        if b["section"] != prev_sec:
            out.append(r"\subsection*{%s}" % esc(b["section"]))
            prev_sec = b["section"]
        anns = by_block.get(b["id"], [])
        parts, pos = [], 0
        for r in sorted(anns, key=lambda x: x["start"]):
            if r["start"] > pos:
                parts.append((None, b["text"][pos:r["start"]], None))
            parts.append((r["level"], b["text"][r["start"]:r["end"]], r["mark"]))
            pos = r["end"]
        if pos < len(b["text"]):
            parts.append((None, b["text"][pos:], None))
        out.append("".join(
            render_plain(t) if lv is None else render_piece(lv, t, mk)
            for lv, t, mk in parts))
        out.append("\n\n")
    return "\n".join(out)


def build_report(meta_title, blocks, resolved, stats, rate, rate_no_quote,
                 quote_rate, total_chars, total_weighted, skipped, coverage,
                 paper, excluded_n):
    today = datetime.date.today().isoformat()
    title = paper.get("title") or meta_title or "用户论文"
    n_sources = coverage.get("sources_total")
    n_full = coverage.get("sources_fulltext")
    cov_note = coverage.get("note", "")

    L = [PREAMBLE]
    L.append(r"\title{论文查重报告}")
    L.append(r"\author{由 paper\_is\_ok 技能生成}")
    L.append(r"\date{%s}" % esc(today))
    L.append(r"\maketitle")

    # 一、结果摘要
    L.append(r"\section*{一、查重结果摘要}")
    L.append(r"\noindent 论文题名：%s\par" % esc(title))
    L.append(r"\noindent 检测总字符数：%d（正文口径，已去除目录、参考文献、"
             r"致谢、附录等不参与查重的章节 %d 块）\par"
             % (total_chars, excluded_n))
    L.append(r"\noindent 疑似标注总数：%d\par" % len(resolved))
    if n_sources is not None and n_full is not None:
        cov_line = "比对覆盖率：%s / %s 篇" % (n_full, n_sources)
    else:
        cov_line = "比对覆盖率：未提供"
    if cov_note:
        cov_line += "（%s）" % cov_note
    L.append(r"\noindent %s\par" % esc(cov_line))
    L.append(r"\begin{center}\Large 总查重率（不计规范引用）："
             r"\textbf{%.2f\%%}\end{center}" % rate_no_quote)
    L.append(r"\noindent 含规范引用的总复制比：%.2f\%%；引用率（规范引用字符"
             r"占检测总字符数）：%.2f\%%\par" % (rate, quote_rate))
    L.append(r"\noindent 计算公式：%s\par\medskip" % FORMULA_TEX)
    L.append(r"\noindent \textbf{结果说明}：本查重率仅基于本次可获取并已比对的"
             r"文献子集；付费跳过的文献未参与比对，实际重复率只可能更高。"
             r"知网实际连续匹配阈值约为 13--15 字符，严于本报告的严重疑似"
             r"阈值（30 字符），故本报告结果整体偏低。\textbf{仅供参考，"
             r"不等同于知网/iThenticate 等官方查重报告}。\par")

    # 二、等级统计
    L.append(r"\section*{二、等级统计}")
    L.append(r"\begin{longtable}{L{2.8cm} R{1.5cm} R{2.5cm} R{1.5cm} "
             r"R{2.8cm} R{2.2cm}}")
    L.append(r"\toprule 等级 & 处数 & 涉及字符数 & 权重 & 加权字符数 & "
             r"贡献率 \\ \midrule")
    for lv in LEVEL_ORDER:
        s = stats[lv]
        L.append(r"\colorbox{%s}{%s} & %d & %d & %.1f & %.1f & %.2f\%% \\"
                 % (LEVEL_COLORS[lv], esc(LEVEL_NAMES[lv]), s["count"],
                    s["chars"], WEIGHTS[lv], s["weighted"], s["contrib"]))
    L.append(r"\midrule \textbf{合计} & \textbf{%d} & \textbf{%d} & --- & "
             r"\textbf{%.1f} & \textbf{%.2f\%%} \\ \bottomrule"
             % (sum(stats[lv]["count"] for lv in LEVEL_ORDER),
                sum(stats[lv]["chars"] for lv in LEVEL_ORDER),
                total_weighted, rate))
    L.append(r"\end{longtable}")

    # 三、疑似明细
    L.append(r"\section*{三、疑似明细表}")
    if resolved:
        L.append(r"\begin{longtable}{L{0.8cm} L{1.8cm} L{1.9cm} L{3.9cm} "
                 r"L{4.4cm} L{1.4cm}}")
        L.append(r"\toprule 编号 & 等级 & 位置 & 论文片段 & 来源文献与判定依据 "
                 r"& 贡献 \\ \midrule")
        for r in resolved:
            b = r["block"]
            seg_text = b["text"][r["start"]:r["end"]]
            src = r["source"]
            src_cell = esc(truncate(src.get("title", "（未提供题名）"), 60))
            meta = ", ".join(x for x in [
                src.get("authors", ""), str(src.get("year", "")),
                src.get("venue", "")] if x)
            if meta:
                src_cell += r"\newline %s" % esc(truncate(meta, 60))
            if src.get("url"):
                src_cell += r"\newline %s" % esc(truncate(src["url"], 70))
            acc = {"fulltext": "全文比对", "abstract": "仅摘要比对",
                   "user-provided": "用户提供文本"}.get(src.get("access"), "")
            if acc:
                src_cell += r"\newline %s" % esc(acc)
            if r["matched"]:
                src_cell += (r"\newline 对应用原文：%s"
                             % esc(truncate(r["matched"], MATCH_SHOW)))
            if r["reason"]:
                src_cell += r"\newline 判定：%s" % esc(truncate(r["reason"], 90))
            contrib = count_chars(seg_text) * WEIGHTS[r["level"]] \
                / total_chars * 100
            L.append(r"%d & \colorbox{%s}{%s} & %s（%s） & %s & %s & %.3f\%% \\"
                     % (r["mark"], LEVEL_COLORS[r["level"]],
                        esc(LEVEL_NAMES[r["level"]]
                            + ("（规范引用）" if r["quote"] else "")),
                        esc(b["id"]),
                        esc(truncate(b["section"], 12)),
                        esc(truncate(seg_text, EXCERPT_SHOW)),
                        src_cell, contrib))
        L.append(r"\bottomrule \end{longtable}")
    else:
        L.append(r"\noindent 未检出任何疑似片段。\par")

    # 四、未比对文献
    L.append(r"\section*{四、未比对文献清单}")
    if skipped:
        L.append(r"\begin{itemize}")
        for s in skipped:
            L.append(r"\item %s%s" % (
                esc(truncate(s.get("title", "（未提供题名）"), 80)),
                ("——" + esc(s.get("reason", ""))) if s.get("reason") else ""))
        L.append(r"\end{itemize}")
    else:
        L.append(r"\noindent 无（本次应比对文献均已参与比对）。\par")

    # 五、正文高亮
    L.append(render_fulltext(blocks, resolved))

    # 六、判定标准
    L.append(r"\section*{六、判定标准说明}")
    L.append(r"\noindent 查重率公式：%s。其中字符数为非空白字符（含标点），"
             r"疑似片段字符数按其在正文中覆盖的范围统计。\par\medskip"
             % FORMULA_TEX)
    L.append(r"\begin{longtable}{L{3.2cm} L{1.5cm} L{10.0cm}}")
    L.append(r"\toprule 等级（颜色） & 权重 & 判定要点 \\ \midrule")
    for name, w, desc in RUBRIC_RECAP:
        L.append(r"%s & %s & %s \\" % (esc(name), w, esc(desc)))
    L.append(r"\bottomrule \end{longtable}")
    L.append(r"\medskip\noindent 生成时间：%s。比对范围为近 15--20 年文献；"
             r"目录、参考文献列表、致谢、附录、声明与图表标题不参与比对，"
             r"亦不计入检测总字符数；公式按其 LaTeX 源码参与比对与字符统计"
             r"（标准公式且已规范引用的除外，见判定标准 R5）。"
             r"降重方法参见随附的降重指南。\par"
             % esc(today))
    L.append(r"\end{document}")
    return "\n".join(L)


def docx_to_pdf(docx_path):
    """把 docx 转为 PDF。依序尝试 MS Word COM → WPS COM (KWps) → LibreOffice。
    成功返回引擎名，全部失败返回 None。"""
    docx = str(Path(docx_path).resolve())
    pdf = str(Path(docx_path).with_suffix(".pdf").resolve())

    def _com_escape(s):
        return s.replace("'", "''")

    for progid, name in [("Word.Application", "word"), ("KWps.Application", "wps")]:
        ps = (
            "try { $w = New-Object -ComObject %s } catch { exit 3 }; "
            "$w.Visible = $false; "
            "$d = $w.Documents.Open('%s'); "
            "$d.SaveAs([ref]'%s', [ref]17); "
            "$d.Close(); $w.Quit(); Write-Output CONVERTED"
            % (progid, _com_escape(docx), _com_escape(pdf)))
        try:
            rc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=300)
        except Exception:
            continue
        if rc.returncode == 0 and Path(pdf).exists():
            return name
    soffice = shutil.which("soffice")
    if soffice is None:
        for cand in [r"C:\Program Files\LibreOffice\program\soffice.exe",
                     r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"]:
            if Path(cand).exists():
                soffice = cand
                break
    if soffice:
        try:
            rc = subprocess.run(
                [soffice, "--headless", "--convert-to", "pdf",
                 "--outdir", str(Path(docx_path).resolve().parent), docx],
                capture_output=True, text=True, timeout=300)
        except Exception:
            rc = None
        if rc is not None and Path(pdf).exists():
            return "libreoffice"
    return None


def build_docx(meta_title, blocks, resolved, stats, rate, rate_no_quote,
               quote_rate, total_chars, skipped, coverage, paper, excluded_n,
               out_path):
    """生成与 tex 版同构的 Word 查重报告（.docx）。"""
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
    except ImportError:
        print("ERROR: 缺少依赖 python-docx，请先执行: pip install python-docx",
              file=sys.stderr)
        sys.exit(1)

    HEX = {"minor": "FFF478", "moderate": "FFBE78", "severe": "FF7878"}
    today = datetime.date.today().isoformat()
    title = paper.get("title") or meta_title or "用户论文"

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal._element.get_or_add_rPr()
    rfonts = normal._element.rPr.get_or_add_rFonts()
    rfonts.set(qn("w:eastAsia"), "宋体")

    def shade(run, fill):
        rPr = run._element.get_or_add_rPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), fill)
        rPr.append(shd)

    def para(text="", bold=False, size=None):
        p = doc.add_paragraph()
        r = p.add_run(text)
        r.bold = bold
        if size:
            r.font.size = Pt(size)
        return p

    def table(headers, rows):
        t = doc.add_table(rows=1 + len(rows), cols=len(headers))
        try:
            t.style = "Table Grid"
        except Exception:
            pass
        for j, h in enumerate(headers):
            cell = t.rows[0].cells[j]
            r = cell.paragraphs[0].add_run(h)
            r.bold = True
        for i, row in enumerate(rows, 1):
            for j, v in enumerate(row):
                t.rows[i].cells[j].paragraphs[0].add_run(str(v))
        doc.add_paragraph()
        return t

    doc.add_heading("论文查重报告", level=0)
    para("由 paper_is_ok 技能生成　%s" % today)

    doc.add_heading("一、查重结果摘要", level=1)
    para("论文题名：%s" % title)
    para("检测总字符数：%d（正文口径，已去除目录、参考文献、致谢、附录等"
         "不参与查重的章节 %d 块）" % (total_chars, excluded_n))
    para("疑似标注总数：%d" % len(resolved))
    if coverage.get("sources_total") is not None:
        cov = "比对覆盖率：%s / %s 篇" % (coverage.get("sources_fulltext", "?"),
                                         coverage.get("sources_total", "?"))
        if coverage.get("note"):
            cov += "（%s）" % coverage["note"]
        para(cov)
    p = doc.add_paragraph()
    r = p.add_run("总查重率（不计规范引用）：%.2f%%" % rate_no_quote)
    r.bold = True
    r.font.size = Pt(14)
    para("含规范引用的总复制比：%.2f%%；引用率：%.2f%%" % (rate, quote_rate))
    para("计算公式：查重率 = Σ(片段字符数 × 权重) ÷ 检测总字符数 × 100")
    para("结果说明：本查重率仅基于本次可获取并已比对的文献子集；付费跳过的文献未参与"
         "比对，实际重复率只可能更高。知网实际连续匹配阈值约为 13–15 字符，严于本报告"
         "的严重疑似阈值（30 字符），故本报告结果整体偏低。仅供参考，不等同于知网/"
         "iThenticate 等官方查重报告。")

    doc.add_heading("二、等级统计", level=1)
    table(["等级", "处数", "涉及字符数", "权重", "加权字符数", "贡献率"],
          [[LEVEL_NAMES[lv], stats[lv]["count"], stats[lv]["chars"],
            WEIGHTS[lv], round(stats[lv]["weighted"], 1),
            "%.2f%%" % stats[lv]["contrib"]] for lv in LEVEL_ORDER])

    doc.add_heading("三、疑似明细表", level=1)
    rows = []
    for r_ in resolved:
        b = r_["block"]
        seg_text = b["text"][r_["start"]:r_["end"]]
        src = r_["source"]
        src_cell = "%s (%s)" % (src.get("title", "（未提供题名）"),
                                ", ".join(x for x in [
                                    src.get("authors", ""),
                                    str(src.get("year", "")),
                                    src.get("venue", "")] if x))
        if src.get("url"):
            src_cell += " %s" % src["url"]
        rows.append([r_["mark"], LEVEL_NAMES[r_["level"]]
                     + ("（规范引用）" if r_["quote"] else ""),
                     "%s（%s）" % (b["id"], b["section"]),
                     truncate(seg_text, EXCERPT_SHOW),
                     src_cell + " 对应用原文：" + truncate(r_["matched"], MATCH_SHOW)
                     + " 判定：" + truncate(r_["reason"], 90),
                     "%.3f%%" % (count_chars(seg_text) * WEIGHTS[r_["level"]]
                                 / total_chars * 100)])
    if rows:
        table(["编号", "等级", "位置", "论文片段", "来源文献与判定依据", "贡献"], rows)
    else:
        para("未检出任何疑似片段。")

    doc.add_heading("四、未比对文献清单", level=1)
    if skipped:
        for s in skipped:
            para("• %s——%s" % (s.get("title", "（未提供题名）"),
                                s.get("reason", "")))
    else:
        para("无（本次应比对文献均已参与比对）。")

    doc.add_heading("五、正文高亮重现", level=1)
    para("图例：轻微疑似（黄）、中度疑似（橙）、严重疑似（红）；编号 [n] 对应疑似明细表。"
         "数学公式以 LaTeX 源码完整保留并参与比对（Word 版中公式显示为源文本，"
         "内容可完整核对）。")
    by_block = {}
    for r_ in resolved:
        by_block.setdefault(r_["block"]["id"], []).append(r_)
    prev_sec = None
    for b in blocks:
        if b["section"] != prev_sec:
            doc.add_heading(b["section"], level=2)
            prev_sec = b["section"]
        p = doc.add_paragraph()
        pos = 0
        for r_ in sorted(by_block.get(b["id"], []), key=lambda x: x["start"]):
            if r_["start"] > pos:
                p.add_run(b["text"][pos:r_["start"]])
            fill = HEX[r_["level"]]
            run = p.add_run(b["text"][r_["start"]:r_["end"]])
            shade(run, fill)
            mk = p.add_run("[%d]" % r_["mark"])
            mk.font.superscript = True
            mk.bold = True
            mk.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
            pos = r_["end"]
        if pos < len(b["text"]):
            p.add_run(b["text"][pos:])

    doc.add_heading("六、判定标准说明", level=1)
    para("查重率公式：查重率 = Σ(片段字符数 × 权重) ÷ 检测总字符数 × 100，其中字符数为"
         "非空白字符（含标点），疑似片段字符数按其在正文中覆盖的范围统计。")
    table(["等级（颜色）", "权重", "判定要点"],
          [[n, w, d] for n, w, d in RUBRIC_RECAP])
    para("生成时间：%s。比对范围为近 15–20 年文献；目录、参考文献列表、致谢、附录、"
         "声明与图表标题不参与比对，亦不计入检测总字符数；公式按其 LaTeX 源码参与"
         "比对与字符统计（标准公式且已规范引用的除外，见判定标准 R5）。"
         "降重方法参见随附的降重指南。" % today)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))


def detect_missing_packages(log_text):
    """从编译日志中识别缺失的宏包/文件名（去掉 .sty/.cls 等后缀）。"""
    found = []
    for pat in [r"File `([^']+)' not found", r"file '([^']+)' not found",
                r"\\(?:usepackage|RequirePackage)\{([^}]+)\}"]:
        for m in re.findall(pat, log_text):
            name = m.strip()
            for suf in (".sty", ".cls", ".tex", ".def", ".cfg"):
                if name.endswith(suf):
                    name = name[:-len(suf)]
                    break
            if name and name not in found:
                found.append(name)
    return found


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="查重率计算与查重报告生成")
    ap.add_argument("blocks_json", help="extract_text.py 产出的 blocks JSON")
    ap.add_argument("annotations", nargs="+", help="一个或多个标注 JSON")
    ap.add_argument("-o", "--output", default="查重报告.tex")
    ap.add_argument("--compile", action="store_true",
                    help="若本机有 xelatex 则编译为 PDF")
    ap.add_argument("--docx", action="store_true",
                    help="同时输出 Word 版报告(.docx)并自动转换为 PDF"
                         "（本机无 LaTeX 环境时使用）")
    ap.add_argument("--enable-installer", action="store_true",
                    help="MiKTeX 缺宏包时允许联网自动安装（等价 xelatex "
                         "-enable-installer）")
    args = ap.parse_args()

    blocks_data = json.loads(Path(args.blocks_json).read_text(
        encoding="utf-8"))
    blocks = blocks_data.get("blocks", [])
    if not blocks:
        print("ERROR: blocks JSON 中没有内容块", file=sys.stderr)
        sys.exit(1)

    # 知网口径：目录/参考文献/致谢/附录等不参与比对，不计入检测总字符数
    included = [b for b in blocks if not is_excluded(b)]
    excluded = [b for b in blocks if is_excluded(b)]
    excluded_ids = {b["id"] for b in excluded}
    if excluded:
        print("INFO 排除不参与查重的章节块 %d 个（%s）"
              % (len(excluded),
                 "、".join(sorted({b["section"] for b in excluded}))))
    total_chars = sum(count_chars(b["text"]) for b in included)

    anns, skipped, coverage, paper = load_annotations(args.annotations)
    resolved = resolve_annotations(blocks, anns, excluded_ids)
    stats, rate, total_weighted, rate_no_quote, quote_chars, quote_rate = \
        compute_stats(total_chars, resolved)

    report = build_report(blocks_data.get("title"), blocks, resolved, stats,
                          rate, rate_no_quote, quote_rate, total_chars,
                          total_weighted, skipped, coverage, paper,
                          len(excluded))
    out_path = Path(args.output)
    out_path.write_text(report, encoding="utf-8")

    print("OK report=%s" % out_path)
    print("RESULT total_chars=%d rate_no_quote=%.2f%% rate_with_quote=%.2f%% "
          "quote_rate=%.2f%% severe=%d moderate=%d minor=%d"
          % (total_chars, rate_no_quote, rate, quote_rate,
             stats["severe"]["count"], stats["moderate"]["count"],
             stats["minor"]["count"]))
    for lv in LEVEL_ORDER:
        print("  %s: %d 处 / %d 字符 / 贡献 %.2f%%"
              % (LEVEL_NAMES[lv], stats[lv]["count"], stats[lv]["chars"],
                 stats[lv]["contrib"]))
    print("  规范引用: %d 字符（不计入查重率，引用率 %.2f%%）"
          % (quote_chars, quote_rate))

    if args.docx:
        docx_path = out_path.with_suffix(".docx")
        build_docx(blocks_data.get("title"), blocks, resolved, stats, rate,
                   rate_no_quote, quote_rate, total_chars, skipped,
                   coverage, paper, len(excluded), docx_path)
        print("OK docx=%s" % docx_path)
        engine = docx_to_pdf(docx_path)
        if engine:
            print("OK pdf=%s (via %s)" % (docx_path.with_suffix(".pdf"), engine))
        else:
            warn("未能自动转换 PDF（本机未检测到 Word/WPS/LibreOffice），"
                 "请用 Word 或 WPS 打开 %s 后另存为 PDF" % docx_path.name)

    if args.compile:
        if shutil.which("xelatex") is None:
            warn("未找到 xelatex，LaTeX 环境不可用")
            print("LATEX_STATUS: missing-xelatex")
            sys.exit(0)
        xargs = ["-interaction=nonstopmode", "-halt-on-error"]
        if args.enable_installer:
            xargs.append("-enable-installer")
        rc = subprocess.run(
            ["xelatex"] + xargs + [out_path.name],
            cwd=str(out_path.parent) if str(out_path.parent) else None,
            capture_output=True, text=True)
        pdf = out_path.with_suffix(".pdf")
        if rc.returncode == 0 and pdf.exists():
            print("OK compiled=%s" % pdf)
        else:
            log = (rc.stdout or "") + (rc.stderr or "")
            missing = detect_missing_packages(log)
            print("LATEX_STATUS: compile-failed")
            if missing:
                print("MISSING_PACKAGES: %s" % ", ".join(missing))
                print("HINT: MiKTeX 修复：miktex packages install <包名>，"
                      "或重跑并加 --enable-installer 联网自动安装；"
                      "TeX Live 修复：tlmgr install <包名>")
            warn("xelatex 编译失败。日志尾部：\n" + log[-1200:])


if __name__ == "__main__":
    main()
