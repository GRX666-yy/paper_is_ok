# paper-is-ok

[中文](README.md) | **English**

An [Agent Skills](https://agentskills.io)-compatible **paper duplication-check skill**: it drives an AI agent to run a standardized, reproducible and quantifiable plagiarism/similarity check on your paper (.pdf / .tex), and produces a color-highlighted duplication report (LaTeX or Word, compiled/auto-converted to PDF).

## How it works

1. **Parse the paper** — `scripts/extract_text.py` converts the PDF or LaTeX source into structured text blocks;
2. **Read the paper** — the agent reads the full text and extracts the title, contributions, section structure and keywords;
3. **Literature search** — seeded first by the paper's own reference list, then by bilingual keyword queries across multiple academic platforms for related work from the last **15–20 years**: open-access full-text sources (arXiv, OpenReview, ACL Anthology, CORE, PubMed Central, etc.), metadata & citation graphs (Semantic Scholar, OpenAlex, Crossref, etc.), and paywalled publishers (IEEE/Springer/CNKI, etc. — see `references/search-sources.md`);
4. **Paywall handling** — for paywalled literature the agent **asks first** whether you already have access; if not and paywalled items are a small fraction, they are skipped and logged; if a large fraction, you decide how to proceed;
5. **Sentence-level comparison** — every sentence/paragraph is graded with a 4-level quantified rubric (table below); the table of contents, reference list, acknowledgments and appendices are excluded from the character count (aligned with CNKI's convention); properly formatted citations are counted separately as a "citation rate";
6. **Compute the duplication rate** — weighted calculation by `scripts/generate_report.py`;
7. **Generate the report** — delivered in a `查重报告\` (duplication-report) folder: with a LaTeX environment, `查重报告.tex` is compiled to `查重报告.pdf`; **without LaTeX (e.g., PDF-only users), a `查重报告.docx` Word report with red/orange/yellow shading is generated and auto-converted to `查重报告.pdf`**; if the LaTeX environment turns out to be incomplete (missing packages), the agent **asks whether you want to fix the environment first** — if you decline, it switches to the Word mode automatically. The full text is reproduced with highlights (original passages stay unmarked), together with a **duplication-reduction guide** (`references/reduce-duplication.md`, based on how CNKI computes similarity).

## Four similarity levels and weights

| Level | Weight | Report mark | Criteria |
|-------|--------|-------------|----------|
| None | 0 | unmarked | original wording or sufficiently rewritten |
| Minor | 0.2 | yellow | 6–8 consecutive overlapping characters / highly similar viewpoint / properly formatted direct quote |
| Moderate | 0.3 | orange | 9–17 consecutive overlapping characters / single-sentence structural copy with rewording |
| Severe | 0.5 | red | ≥18 consecutive overlapping characters / whole-paragraph structural copy |

**Duplication-rate formula**: `Σ(non-whitespace chars of flagged span × weight) ÷ total non-whitespace chars × 100`

Example: one 100-character paragraph graded severe in a 10,000-character paper → (100 × 0.5) ÷ 10000 × 100 = **0.5%**.

## Install

**Requirements**: Python ≥ 3.8 with `pypdf` (PDF parsing) and `python-docx` (Word report output). For the PDF report, either works: a local TeX installation (xelatex + ctex) → LaTeX report; **no LaTeX → Word report (.docx auto-converted to PDF via local Word/WPS/LibreOffice)**.

```bash
pip install pypdf python-docx
```

### Option 1: put the folder into your agent's skills directory

Copy the **entire folder** (keeping `scripts/` and `references/` alongside SKILL.md, relative layout unchanged) into the agent's skills directory or workspace:

| Agent | Location | Notes |
|-------|----------|-------|
| Claude Code | `~/.claude/skills/paper_is_ok/` (global) or `project/.claude/skills/` (per-project) | native Agent Skills support, auto-triggered on demand |
| Claude.ai (web) | Settings → Capabilities → Skills, upload the folder as a `.zip` | available in all chats afterwards |
| Trae / Trae CN | put the folder in the project (e.g. `project_root/paper_is_ok/`) and register it in the Trae rules file (`.trae/rules/project_rules.md`): duplication-check tasks must follow `paper_is_ok/SKILL.md` | then just say "use the paper_is_ok skill" in Trae |
| Codex (OpenAI) | put the folder at the repo root and state in `AGENTS.md`: `For paper duplication checks, read and strictly follow paper_is_ok/SKILL.md` | Codex has no separate skills directory; it is referenced via AGENTS.md |
| WorkBuddy | put the folder in the workspace; register the path in its skill/extension settings, or state the SKILL.md relative path in the system prompt/rules | if your version has no skills mechanism, use the universal method below |
| ZCOD | put the folder in the workspace or its skills directory, and point to `paper_is_ok/SKILL.md` in the rule configuration or the first message | same as above; the universal method always works |
| Other Agent-Skills-compatible agents | follow their documented skills directory | folder name must match the `name` field in SKILL.md |

### Option 2: universal method (any agent that can read local files)

1. Put `paper_is_ok/` into the project directory or anywhere the agent can access;
2. Tell the agent (in chat, a system prompt or a rules file):

   > Please read paper_is_ok/SKILL.md and run the paper duplication check strictly following its 7-phase workflow; see references/rubric.md for the grading standard, references/data-formats.md for data formats, references/search-sources.md for search platforms, and scripts/ for the scripts.

3. The agent runs the workflow and delivers the duplication report.

> Note: SKILL.md references `references/` and `scripts/` by relative paths — keep all three inside the same folder when moving it.

## Usage

Say to your agent:

> Use the paper_is_ok skill to check this paper for duplication: D:\papers\my_paper.tex

> Run a similarity check on paper.pdf

The agent will ask for whatever it needs (e.g., paywalled literature access) and deliver the duplication report.

## Repository layout

```
paper_is_ok/                        # this repository
├── README.md                       # Chinese documentation
├── README.en.md                    # this file
├── LICENSE                         # non-commercial custom license (modified MIT)
└── paper_is_ok/                    # the skill itself (copy this folder to install)
    ├── SKILL.md                    # main skill file (frontmatter + 7-phase workflow)
    ├── LICENSE                     # license copy shipped with the skill
    ├── references/
    │   ├── rubric.md               # 4-level quantified rubric (clauses R0–R4) + CNKI alignment
    │   ├── data-formats.md         # blocks/annotation JSON contract
    │   ├── search-sources.md       # literature search platforms & strategies
    │   └── reduce-duplication.md   # duplication-reduction guide
    └── scripts/
        ├── extract_text.py         # PDF/.tex → blocks JSON
        └── generate_report.py      # weighted rate + report generation (tex/docx/pdf)
```

## Disclaimer

The results are produced by AI comparing your paper against the literature it **can access**, so coverage is limited. They are **for reference only and are not equivalent to official similarity reports** from CNKI, iThenticate, Turnitin, etc., and must not be used as formal evidence in degree or journal review.

## License

Non-commercial custom license (modified MIT): use, copy, modify, merge, publish, distribute and sublicense are permitted, but the software **must not be used for commercial purposes or profit**; any infringement of rights caused by a private party (i.e., anyone other than the author) shall not involve the author. See [LICENSE](LICENSE).
