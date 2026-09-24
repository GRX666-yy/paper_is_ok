# paper-is-ok

一个遵循 [Agent Skills 规范](https://agentskills.io)（SKILL.md）的**论文查重技能**：驱动 AI agent 对你的论文（.pdf / .tex）执行规范、可复现、可量化的查重流程，并生成带颜色标注的 LaTeX 查重报告。

An [Agent Skills](https://agentskills.io)-compatible skill that guides an AI agent to check your paper (.pdf/.tex) for textual overlap against published literature from the last 15–20 years, compute a weighted duplication rate, and generate a color-highlighted LaTeX report (`查重报告.tex`).

## 工作原理 / How it works

1. **解析论文** — `scripts/extract_text.py` 将 PDF 或 LaTeX 源文件解析为结构化文本块；
2. **通读论文** — agent 通读全文，提炼题目、贡献、章节、关键词；
3. **文献检索** — 以论文自身参考文献列表为最高优先级种子，再用关键词（中英文）在多个学术平台交叉检索近 **15–20 年**的相关文献：免费全文平台（arXiv、OpenReview、ACL Anthology、CORE、PubMed Central 等）、元数据与引文图谱（Semantic Scholar、OpenAlex、Crossref、百度学术等）、付费出版商（IEEE/Springer/CNKI 等，全文需经用户确认，详见 `references/search-sources.md`）；
4. **付费墙处理** — 遇到付费文献会**先询问**你是否已有资源；无资源且占比小则跳过并记录，占比大则由你决定是否继续；
5. **逐句比对** — 按四级量化 rubric 判级（见下表）；目录、参考文献、致谢、附录等不计入检测总字符数（对照知网口径），规范引用单独计"引用率"；
6. **计算查重率** — `scripts/generate_report.py` 加权计算；
7. **生成报告** — 统一放入 `查重报告\` 文件夹：有 LaTeX 环境输出 `查重报告.tex` 并编译为 `查重报告.pdf`；**无 LaTeX 环境（如只上传 PDF 的用户）输出 `查重报告.docx`（Word 版，红/橙/黄底纹高亮）并自动转换为 `查重报告.pdf`**；全文重现并高亮，无疑似不标记，并随附**降重指南**（基于知网降重原理的 `references/reduce-duplication.md`）。

## 四级判定与权重

| 等级 | 权重 | 报告标记 | 判定要点 |
|------|------|---------|----------|
| 无疑似 | 0 | 不标记 | 表述原创或已充分改写 |
| 轻微疑似 | 0.2 | 黄色 | 连续重合 8–14 字符 / 观点高度相近 / 规范直接引用 |
| 中度疑似 | 0.3 | 橙色 | 连续重合 15–29 字符 / 单句同构仅换措辞 |
| 严重疑似 | 0.5 | 红色 | 连续重合 ≥30 字符 / 整段同构复写 |

**查重率公式**：`Σ(片段非空白字符数 × 权重) ÷ 全文非空白字符数 × 100`

例：10000 字论文中一段 100 字被判严重疑似 → (100 × 0.5) ÷ 10000 × 100 = **0.5%**。

## 安装 / Install

**环境要求**：Python ≥ 3.8，`pypdf`（PDF 解析）与 `python-docx`（Word 报告输出）。报告 PDF 二选一：本机有 TeX（xelatex + ctex）→ LaTeX 版；**无 LaTeX 环境 → Word 版（.docx 自动经本机 Word/WPS/LibreOffice 转为 PDF）**。

```bash
pip install pypdf python-docx
```

### 方式一：放入 agent 技能目录

将**整个文件夹**（必须连同 `scripts/` 与 `references/` 一起，保持相对位置不变）放入 agent 的技能目录或工作区：

| Agent | 安装位置 | 说明 |
|-------|----------|------|
| Claude Code | `~/.claude/skills/paper-duplication-check/`（全局）或 `项目/.claude/skills/`（项目级） | 原生支持 Agent Skills 规范，放入后自动按需触发 |
| Claude.ai 网页版 | 设置 → Capabilities → Skills，将本文件夹打包为 `.zip` 上传 | 上传后所有对话可用 |
| Trae / Trae CN | 将文件夹放入项目目录（如 `项目根目录/paper-duplication-check/`），并在 Trae 规则文件（`.trae/rules/project_rules.md`）中登记：查重任务请遵循 `paper-duplication-check/SKILL.md` | 放入后对 Trae 说"使用 paper-duplication-check 技能"即可 |
| Codex（OpenAI） | 将文件夹放入仓库根目录，并在 `AGENTS.md` 中写明：`论文查重任务请阅读并严格遵循 paper-duplication-check/SKILL.md 执行` | Codex 无独立技能目录，通过 AGENTS.md 引用生效 |
| WorkBuddy | 将文件夹放入工作区；在其技能/扩展设置中登记路径，或在系统提示/规则中写明 SKILL.md 的相对路径 | 若所用版本尚无技能目录机制，走下方通用方法 |
| ZCOD | 将文件夹放入工作区或其技能目录，并在规则配置或首条对话消息中指明 `paper-duplication-check/SKILL.md` 路径 | 同上，通用方法始终可用 |
| 其他遵循 Agent Skills 规范的 agent | 参照其文档的 skills 目录 | 文件夹名需与 SKILL.md 中的 `name` 一致 |

### 方式二：通用方法（任何能读取本地文件的 agent）

即使 agent 没有技能机制，也可以手动驱动：

1. 把 `paper-duplication-check/` 放入项目目录或 agent 可访问的任意位置；
2. 在对话（或系统提示/规则文件）中告诉 agent：

   > 请阅读 paper-duplication-check/SKILL.md，并严格按照其中的七阶段流程执行论文查重；判定标准见 references/rubric.md，数据格式见 references/data-formats.md，检索平台见 references/search-sources.md，脚本位于 scripts/。

3. agent 即按流程工作并最终交付 `查重报告.tex`。

> 注意：SKILL.md 以相对路径引用 `references/` 与 `scripts/`，移动时三者必须保持同在一个文件夹内。

## 使用 / Usage

对 agent 说：

> 请用 paper-duplication-check 技能帮我查重这篇论文：D:\papers\my_paper.tex

> 用查重技能检查 paper.pdf 的重复率

agent 会按流程询问必要信息（付费文献资源等）并最终交付 `查重报告.tex`。

## 目录结构

```
paper_is_ok/                        # 本仓库
├── README.md                       # 本说明文件
├── LICENSE                         # 非商业自定义许可（基于 MIT 修改）
└── paper-duplication-check/        # 技能本体（安装时复制这个文件夹）
    ├── SKILL.md                    # 技能主文件（frontmatter + 七阶段工作流）
    ├── LICENSE                     # 随技能分发的许可副本
    ├── references/
    │   ├── rubric.md               # 四级量化判定标准（R0–R4 条款）+ 知网口径对照
    │   ├── data-formats.md         # blocks/标注 JSON 数据契约
    │   ├── search-sources.md       # 文献检索平台清单与检索策略
    │   └── reduce-duplication.md   # 降重指南（如何有效降低重复率）
    └── scripts/
        ├── extract_text.py         # PDF/.tex → blocks JSON
        └── generate_report.py      # 查重率计算 + 查重报告.tex 生成
```

## 免责声明 / Disclaimer

本技能的查重结果由 AI 基于其**可获取**的文献比对得出，覆盖率有限，**仅供参考，不等同于知网、iThenticate、Turnitin 等官方查重报告**，不可用于学位/期刊的正式审查依据。Please use the results as a reference only; they are not a substitute for official similarity reports.

## 许可证 / License

非商业自定义许可（基于 MIT 修改）：允许使用、复制、修改、合并、发布、分发、再许可，但**请勿用作商业用途或盈利**；若由私人（非作者）导致的利益侵犯与作者无关。详见 [LICENSE](LICENSE)。
