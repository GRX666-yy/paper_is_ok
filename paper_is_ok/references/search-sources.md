# 文献检索平台清单与检索策略

Phase 3 检索时按本文件执行。核心原则：**尽可能多平台交叉检索，优先合法免费全文，绝不使用盗版渠道**。

## 0. 合规红线

- 禁止使用 Sci-Hub、LibGen、Z-Library 等盗版/侵权渠道。
- 出版商付费墙拦截时，一律转入 SKILL.md Phase 4 的「付费文献用户授权流程」。
- 保存/展示来源文献文字时，只保留比对所必需的短句（≤50 字/处）。

## 1. A 类：免费全文平台（优先获取全文比对）

| 平台 | 地址/接口 | 覆盖领域 | 说明 |
|------|-----------|----------|------|
| arXiv | `http://export.arxiv.org/api/query?search_query=...` | CS/物理/数学/统计 | 预印本全文，含最新研究 |
| bioRxiv / medRxiv | `https://api.biorxiv.org` / `https://www.medrxiv.org` | 生物/医学 | 预印本全文 |
| chemRxiv / SSRN | `https://chemrxiv.org` / `https://www.ssrn.com` | 化学/社科预印本 | 全文 |
| OpenReview | `https://api2.openreview.net` | 机器学习会议（ICLR/NeurIPS/ICML 部分） | 全文 PDF + 审稿意见 |
| ACL Anthology | `https://aclanthology.org` | NLP/计算语言学 | 全文 PDF |
| PMLR / NeurIPS Proceedings / CVF Open Access | `https://proceedings.mlr.press` 等 | ML/CV 会议 | 全文 PDF |
| CORE | `https://api.core.ac.uk` | 综合聚合 | 聚合全球 OA 仓库全文 |
| BASE | `https://www.base-search.net` | 综合聚合 | 2 亿+ 文献，多数有 OA 链接 |
| DOAJ | `https://doaj.org/api` | 综合期刊 | 开放获取期刊全文 |
| PubMed Central / Europe PMC | `https://eutils.ncbi.nlm.nih.gov` / `https://europepmc.org` | 生物医学 | 全文 |
| Zenodo | `https://zenodo.org` | 综合 | 工作论文/报告全文 |
| ResearchGate / Academia.edu | 经网页搜索进入 | 综合 | 作者自传版本，常含全文 |
| Unpaywall | `https://api.unpaywall.org/v2/<DOI>?email=...` | 按 DOI 查询 | 返回该 DOI 的**合法** OA 版本链接，付费文献的破解第一步 |

## 2. B 类：免费元数据/摘要与引文图谱（发现与筛选文献）

| 平台 | 地址/接口 | 说明 |
|------|-----------|------|
| Semantic Scholar | `https://api.semanticscholar.org/graph/v1/paper/search?query=...` | 免费 API 无需 key；摘要、引文列表、被引、相似论文推荐（`/paper/{id}/recommendations`），查重最有用的单一平台 |
| OpenAlex | `https://api.openalex.org/works?search=...` | 2.5 亿+ 作品，免费无 key；相关作品与 OA 链接 |
| Crossref | `https://api.crossref.org/works?query.bibliographic=...` | DOI 与元数据权威来源 |
| dblp | `https://dblp.org/search/publ/api?q=...` | CS 文献题录 |
| Google Scholar | 经 WebSearch 间接使用（不要直接抓取页面） | 被引次数与「相关文章」是前向滚雪球的关键 |
| 百度学术 | `https://xueshu.baidu.com` | 中文文献发现，可检索 CNKI/万方题录 |
| SciEngine/知网空间等中文题录 | 经 WebSearch | 中文论文标题/摘要获取 |

## 3. C 类：付费出版商平台（摘要可见，全文触发 Phase 4 询问）

| 平台 | 覆盖领域 | 说明 |
|------|----------|------|
| IEEE Xplore | 电子/工程/CS | 摘要免费，全文付费 |
| ACM Digital Library | CS | 同上 |
| ScienceDirect（Elsevier） | 综合 | 同上 |
| SpringerLink / Nature | 综合 | 同上 |
| Wiley / Taylor & Francis / SAGE / Emerald | 综合 | 同上 |
| CNKI 知网 / 万方 / 维普 | 中文核心期刊与学位论文 | 摘要免费，全文付费；学位论文重叠检测很重要 |
| J-STAGE / SciELO / CNKI 海外版 | 日韩/拉美文献 | 多数 OA |

## 4. 检索策略（保证覆盖率）

1. **向后滚雪球**：论文自身参考文献列表逐条核对（最高优先级）；用 Semantic Scholar `/paper/{id}/references` 与 OpenAlex `referenced_works` 补全条目信息。
2. **向前滚雪球**：用 Semantic Scholar `/paper/{id}/citations`、Google Scholar 被引、OpenAlex `cited_by` 找引用了种子文献的后续工作。
3. **相似推荐**：Semantic Scholar recommendations、OpenAlex `related_works`、Connected Papers（网页版）扩展近邻文献。
4. **关键词组合**：中英文各构造 3–5 组查询；同义词与缩写展开（如 GCP/graph coloring、RL/reinforcement learning/deep RL）；领域术语 + 方法词 + 任务词交叉组合。
5. **精确补漏**：对拿不到全文的文献，用「标题 + filetype:pdf」「标题 + 作者姓名 site:作者主页」经 WebSearch 找作者自传版；再不行用 Unpaywall 按 DOI 查合法 OA 版。
6. **逐篇获取顺序**（每篇都按此顺序尝试）：
   A 类 OA 全文 → 作者主页/机构仓库 → Unpaywall → C 类出版商页（仅摘要，`access: "abstract"`）→ 全文被付费墙拦截且确属必要 → **Phase 4 询问用户**。
7. **去重与记录**：按 DOI/标题去重；每篇记录来源平台与 `access` 字段，写入 `paper_check_work/sources/`。

## 5. 收敛条件

满足任一条件即可停止扩展检索，进入 Phase 5 比对：

- 比对池达到 15–40 篇且近 3 轮检索无新增高相关文献；
- 连续 2 个平台检索均只返回已有文献或无关文献；
- 关键词组合已穷尽且向前/向后滚雪球均已各执行至少一轮。
