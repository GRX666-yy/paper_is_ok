# 数据格式规范

`scripts/extract_text.py` 产出 `blocks` 文件，agent 产出标注文件，`scripts/generate_report.py` 消费两者。三者的格式契约如下。

## 1. blocks 文件（extract_text.py 产出）

```json
{
  "source_file": "paper.tex",
  "source_type": "tex",
  "title": "论文标题（可能为 null）",
  "total_chars": 12345,
  "char_count_rule": "非空白字符数（含标点，不含空白）",
  "blocks": [
    { "id": "b000", "section": "引言", "text": "近年来……。", "chars": 210 }
  ]
}
```

- `id`：`b000` 起的全局唯一编号，标注时用它定位。
- `section`：抽取时推断的章节名；PDF 无法可靠推断时统一为 `正文`。
- `chars`：该块 `text` 的非空白字符数。**数学公式以原始 LaTeX 源码保留在 `text` 中**（如 `$G=(V,E)$`、`\begin{equation}...\end{equation}`），其字符按源码计入统计。
- PDF 抽取为启发式段落切分，**agent 标注前必须通读**，发现明显段落粘连可在心中按句处理，但偏移量仍以 `text` 原文为准。

## 2. 标注文件（agent 产出，可分多份由脚本自动合并）

```json
{
  "paper": { "title": "用户论文标题", "file": "paper.tex" },
  "coverage": {
    "sources_total": 25,
    "sources_fulltext": 20,
    "note": "4 篇因付费墙跳过，1 篇仅有摘要"
  },
  "skipped": [
    { "title": "某付费文献（2021）", "reason": "付费墙且用户无资源，未参与比对" }
  ],
  "annotations": [
    {
      "block_id": "b012",
      "start": 34,
      "end": 180,
      "level": "severe",
      "source": {
        "title": "Deep Reinforcement Learning for Graph Coloring",
        "authors": "A. Smith, B. Li",
        "year": 2021,
        "venue": "NeurIPS",
        "url": "https://...",
        "access": "fulltext"
      },
      "matched_excerpt": "来源文献中对应的原文片段（≤50 字）",
      "reason": "R1a：连续重合 42 字符"
    }
  ]
}
```

### annotation 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `block_id` | 是 | 必须是 blocks 文件中存在的 id |
| `start` | 是 | 片段在 `block.text` 中的起始偏移（含），Unicode 码点下标，从 0 开始 |
| `end` | 是 | 结束偏移（不含）。要求 `0 ≤ start < end ≤ len(text)` |
| `excerpt_paper` | 强烈建议 | 论文中被标注片段的原文。用于脚本校验偏移量；偏移量非法时作为回退定位依据 |
| `level` | 是 | `minor` / `moderate` / `severe` 三选一；`none` 无疑似**不写标注** |
| `quote` | 否 | `true` 表示规范直接引用（R3c，引号或 [1] 式编号标注）：不计入查重率，单独计入引用率 |
| `source.title` | 是 | 来源文献题名 |
| `source.authors` / `year` / `venue` / `url` | 尽量 | 便于用户核查 |
| `source.access` | 是 | `fulltext` / `abstract` / `user-provided` |
| `matched_excerpt` | 是 | 来源文献中与该片段对应的原句，截取 ≤50 字 |
| `reason` | 是 | 引用 rubric 条款编号 + 一句话依据 |

### 偏移量规则（重要）

- 偏移量以 blocks 文件中 `block.text` 的 Python 字符串下标为准（Unicode 码点）。
- **一致性保障**：`block.text[start:end]` 去空白后应与 `excerpt_paper` 一致。脚本会校验，不一致时以偏移量为准并打印警告；偏移量非法时脚本用 `excerpt_paper` 在块内模糊定位，仍失败则丢弃该条并给出警告。
- 多条标注**不得重叠**；脚本按起始位置排序后自动修剪重叠（保留靠前的），被修剪的给出警告。

### 顶层字段

- `paper`、`coverage`、`skipped` 可选；多个标注文件合并时，`skipped` 列表拼接，`coverage` 取最后出现的。
- `annotations` 为数组，多文件时脚本按顺序拼接。

## 3. 常见错误（脚本行为）

| 情形 | 脚本行为 |
|------|---------|
| `block_id` 不存在 | 警告并丢弃该条 |
| `start/end` 越界或倒序 | 尝试用 `matched_excerpt` 对应论文片段失败后丢弃 |
| 偏移与摘录不一致 | 以偏移量为准，打印警告 |
| 标注重叠 | 修剪后保留先出现的，打印警告 |
| `level` 非法 | 警告并丢弃 |

脚本退出码：`0` 正常；`1` 参数/文件错误；标注存在问题时仍正常退出但打印 `WARNING` 行，**agent 必须检查 stdout 的 WARNING 并修正后重跑**。
