#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_text.py — 将论文（.pdf / .tex）解析为结构化 blocks JSON。

用法:
    python extract_text.py paper.tex -o paper_check_work/paper_blocks.json
    python extract_text.py paper.pdf -o paper_check_work/paper_blocks.json

输出 JSON 结构:
{
  "source_file": "...", "source_type": "tex|pdf", "title": "..." | null,
  "total_chars": 12345, "char_count_rule": "非空白字符数（含标点，不含空白）",
  "blocks": [ {"id": "b000", "section": "引言", "text": "...", "chars": 210}, ... ]
}

退出码: 0 正常（可能带 WARNING）; 1 文件/参数错误; 2 解析质量差（仍写出 JSON）。
"""
import argparse
import json
import re
import sys
from pathlib import Path

MATH_PH = "［数学式］"
MIN_BLOCK_CHARS = 6

# ---------------------------------------------------------------- 通用工具

def count_chars(text: str) -> int:
    """非空白字符数（与查重率统计口径一致）。"""
    return len(re.sub(r"\s+", "", text))


def flush(cur: list, blocks: list, section: str) -> None:
    if cur:
        text = "".join(cur)
        text = re.sub(r"[ \t]+", " ", text).strip()
        if count_chars(text) >= MIN_BLOCK_CHARS:
            blocks.append({"section": section, "text": text})
        cur.clear()

# ---------------------------------------------------------------- .tex 解析

DROP_ENVS = [
    r"figure\*?", r"table\*?", r"equation\*?", r"align\*?", r"alignat\*?",
    r"gather\*?", r"multline\*?", r"eqnarray\*?", r"split", r"cases",
    r"verbatim\*?", r"Verbatim", r"lstlisting\*?", r"minted",
    r"algorithm\*?", r"algorithmic\*?", r"algorithm2e",
    r"thebibliography", r"math", r"displaymath", r"tabular\*?", r"longtable",
]

NO_TEXT_CMDS = (
    r"cite[tp]?\*?|citealp|citeauthor|citeyear[tp]?|ref|eqref|autoref|pageref|"
    r"label|bibitem|bibliography|bibliographystyle|includegraphics|"
    r"usepackage|documentclass|input|include|footnotemark|nocite|index|"
    r"setlength|setcounter|newcommand|renewcommand|def|usectexset|"
    r"ctexset|renewenvironment|newenvironment|vspace|hspace|hspace\*?|"
    r"pagestyle|thispagestyle|setmainfont|setCJKmainfont|caption\*?"
)


def strip_comments(src: str) -> str:
    lines = []
    for line in src.splitlines():
        line = re.sub(r"(?<!\\)%.*$", "", line)
        lines.append(line)
    return "\n".join(lines)


def drop_environments(s: str) -> str:
    for env in DROP_ENVS:
        pat = re.compile(
            r"\\begin\{" + env + r"\}.*?\\end\{" + env + r"\}", re.S)
        while True:
            s2 = pat.sub("\n" + MATH_PH + "\n", s)
            if s2 == s:
                break
            s = s2
    return s


def clean_tex(src: str):
    """返回 (正文文本, 论文标题或None)。启发式清洗，保留正文文字。"""
    s = strip_comments(src)

    title = None
    mt = re.search(r"\\title\s*(?:\[[^\]]*\])?\{([^{}]*)\}", s)
    if mt:
        title = re.sub(r"\\[a-zA-Z]+\*?", "", mt.group(1)).strip()

    m = re.search(r"\\begin\{document\}", s)
    if m:
        s = s[m.end():]
    s = re.sub(r"\\(?:end)?\{document\}", "", s)

    s = drop_environments(s)
    s = re.sub(r"\\begin\{abstract\}", "\n@@H@@摘要\n", s)
    s = re.sub(r"\\end\{abstract\}", "\n", s)
    s = re.sub(r"\\maketitle", "", s)

    # 章节命令 → 标记行（保留标题文字）
    s = re.sub(
        r"\\(chapter|section|subsection|subsubsection|paragraph)\*?\s*"
        r"(?:\[[^\]]*\])?\{([^{}]*?)\}",
        lambda m: "\n@@H@@" + m.group(2).strip() + "\n", s)

    s = re.sub(r"\\item(?:\[[^\]]*\])?", "\n@@ITEM@@\n", s)

    # 行内数学
    s = re.sub(r"\$[^$\n]*\$", MATH_PH, s)
    s = re.sub(r"\\\[.*?\\\]", "\n" + MATH_PH + "\n", s, flags=re.S)
    s = re.sub(r"\\\((.*?)\\\)", MATH_PH, s, flags=re.S)

    # 引用/标签/超链接等无正文价值的命令
    s = re.sub(r"\\(?:url|href)\s*\{[^{}]*\}", "", s)
    s = re.sub(r"\\(?:" + NO_TEXT_CMDS + r")\s*(?:\[[^\]]*\])*\s*\{[^{}]*\}",
               "", s)
    s = re.sub(r"\\(?:" + NO_TEXT_CMDS + r")\b", "", s)

    # 其余命令名丢弃，保留参数内容
    s = re.sub(r"\\[a-zA-Z]+\*?\s*", " ", s)
    s = re.sub(r"\\([{}%&#_$])", r"\1", s)
    s = s.replace("~", " ")
    s = s.replace("{", " ").replace("}", " ")
    return s, title


def tex_to_blocks(src: str):
    text, title = clean_tex(src)
    blocks, cur, section = [], [], "正文"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush(cur, blocks, section)
            continue
        if line.startswith("@@H@@"):
            flush(cur, blocks, section)
            section = line[len("@@H@@"):].strip() or section
            continue
        if line.startswith("@@ITEM@@"):
            flush(cur, blocks, section)
            continue
        cur.append(line + " ")
    flush(cur, blocks, section)
    return blocks, title

# ---------------------------------------------------------------- .pdf 解析

HEADING_WORDS = {
    "abstract": "摘要", "keywords": "关键词", "introduction": "引言",
    "related work": "相关工作", "background": "背景", "preliminaries": "预备知识",
    "method": "研究方法", "methods": "研究方法", "methodology": "研究方法",
    "experiments": "实验", "experiment": "实验", "results": "结果",
    "data analysis": "数据分析", "analysis": "分析", "discussion": "讨论",
    "conclusion": "结论", "conclusions": "结论",
    "references": "参考文献", "acknowledgments": "致谢",
    "acknowledgements": "致谢", "appendix": "附录",
}
SEC_NUM_PAT = re.compile(r"^\s*(\d+(?:\.\d+)*)[\s.、]+(\S.{1,60})$")
CJK_PAT = re.compile(r"[\u4e00-\u9fff]")


def pdf_lines_to_blocks(raw: str):
    blocks, cur, section = [], [], "正文"
    pending_head = None
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower().rstrip(":").strip()
        if low in HEADING_WORDS:
            flush(cur, blocks, section)
            section = HEADING_WORDS[low]
            continue
        m = SEC_NUM_PAT.match(s)
        if m and count_chars(s) < 60:
            flush(cur, blocks, section)
            section = m.group(2).strip()
            continue
        # 上一行以句末标点结束且当前行较短 → 视为标题/新段信号
        if pending_head is not None:
            flush(cur, blocks, section)
            section = pending_head
            pending_head = None
        cur.append(s + " ")
        joined = "".join(cur)
        if len(joined) > 400 and re.search(r"[。！？.!?][\"')\]]?$", s):
            flush(cur, blocks, section)
    flush(cur, blocks, section)
    return blocks


def extract_pdf(path: Path):
    try:
        from pypdf import PdfReader
    except ImportError:
        print("ERROR: 缺少依赖 pypdf，请先执行: pip install pypdf",
              file=sys.stderr)
        sys.exit(1)
    reader = PdfReader(str(path))
    pages = []
    for p in reader.pages:
        try:
            pages.append(p.extract_text() or "")
        except Exception:
            pages.append("")
    raw = "\n".join(pages)
    warnings = []
    n_pages = max(len(pages), 1)
    if count_chars(raw) / n_pages < 60:
        warnings.append(
            "平均每页仅抽出 %.0f 字符，疑似扫描版或图片型 PDF，无法可靠查重，"
            "强烈建议向用户索取 .tex 源文件" % (count_chars(raw) / n_pages))
    if raw.count("cid:") > 20:
        warnings.append("抽取文本含大量 cid 乱码，字体嵌入异常，质量可能不可靠")
    blocks = pdf_lines_to_blocks(raw)
    return blocks, None, warnings

# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="论文文本解析为 blocks JSON")
    ap.add_argument("input", help="论文文件路径 (.pdf 或 .tex)")
    ap.add_argument("-o", "--output", required=True, help="输出 JSON 路径")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.is_file():
        print("ERROR: 文件不存在: %s" % src, file=sys.stderr)
        sys.exit(1)

    warnings = []
    title = None
    suffix = src.suffix.lower()
    if suffix == ".tex":
        blocks, title = tex_to_blocks(src.read_text(encoding="utf-8",
                                                    errors="replace"))
        source_type = "tex"
    elif suffix == ".pdf":
        blocks, title, warnings = extract_pdf(src)
        source_type = "pdf"
    else:
        print("ERROR: 不支持的文件类型 %s（仅支持 .pdf / .tex）" % suffix,
              file=sys.stderr)
        sys.exit(1)

    for i, b in enumerate(blocks):
        b["id"] = "b%03d" % i
        b["chars"] = count_chars(b["text"])
    total = sum(b["chars"] for b in blocks)

    out = {
        "source_file": str(src),
        "source_type": source_type,
        "title": title,
        "total_chars": total,
        "char_count_rule": "非空白字符数（含标点，不含空白）",
        "blocks": blocks,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    print("OK blocks=%d total_chars=%d title=%s"
          % (len(blocks), total, title or "(未知)"))
    for w in warnings:
        print("WARNING: %s" % w)
    if warnings:
        sys.exit(2)


if __name__ == "__main__":
    main()
