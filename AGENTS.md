# Stella 代理说明

本文件写给以后在 `stella-workspace` 中工作的 agent。

## 当前仓库内容

当前仓库主要流程：

- 按月份抓取高速星相关文献
- 用标题做相关性初筛
- 把标准结果写入 `notes/`
- 给已有月度 JSON 加上 `catalog_assessment`
- 审阅已归档论文源码中的结构化数据资产，并写入 `catalog_review.json`
- 根据 `catalog_review.json` 将内部 LaTeX 表格和外部资源忠实提取为 ECSV/raw files，并写入 `catalog_extraction.json`
- 从 JSON 生成 Markdown

## 项目愿景

Stella 的长期目标，是逐步建设一个面向高速星研究的、可追溯、可复现、
可持续更新的对象级数据与知识系统。

如果需要理解项目的长期方向、实施路线和未来扩展目标，请先阅读根目录的
`TODO.md`。

## 核心原则

JSON 是事实源。Markdown 只是从 JSON 生成的阅读视图，必须和 JSON 对应。

默认输出：

```text
notes/YYYY/YYYY-MM/YYYY-MM.json   月度标准记录
notes/YYYY/YYYY-MM/YYYY-MM.md     月度阅读笔记
notes/literature_notes_index.json                  全局索引
notes/literature_notes_index.md                    年度视图
literature/<arxiv_id>/catalog_review.json   单篇论文数据资产审阅事实源
literature/<arxiv_id>/catalog_extraction.json   单篇论文数据资产提取事实源
literature/<arxiv_id>/catalog_sources/<internal_table_id>/excerpt.tex   原始 LaTeX 表格摘录
literature/<arxiv_id>/catalog_sources/<internal_table_id>/latexml.html   LaTeXML 转换视图
literature/<arxiv_id>/catalog_tables/<internal_table_id>.ecsv   忠实表格 ECSV
literature/<arxiv_id>/catalog_sources/<external_resource_id>/download-001.*   外部资源下载件
literature/<arxiv_id>/catalog_tables/<external_resource_id>.ecsv   外部表格资源忠实 ECSV
literature/catalog_workflow_index.json      数据资产工作流全局索引
literature/catalog_workflow_index.md        数据资产工作流阅读视图
```

不要手动改生成后的 Markdown。  
如果输出有问题，应修改 JSON 构建逻辑或 Markdown 渲染逻辑，然后重新生成。

Git 只保存生成这些数据的工具链、说明文档、测试和 skill。`notes/`、
`literature/`、`logs/` 下的 JSON、Markdown、PDF、源码包、HTML 等数据产物默认
遵守 `.gitignore`，不要为了保存工作而 `git add -f` 强制纳入版本控制，除非用户
明确要求这样做。

## 文献流程

常用命令只需要 `--from`：

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py --from 2026-03
```

默认值应兼顾召回和额度：

- `--source deepxiv`
- DeepXiv 出现额度耗尽、token/API 错误或其它检索异常时，本次运行后续检索自动 fallback 到 arXiv
- `--llm-review False`
- 不抓 `DeepXiv brief`
- `--max-results 20`
- `--deepxiv-llm-review-max-candidates 20`
- `--categories astro-ph.GA,astro-ph.SR,astro-ph.IM`
- `--search-mode hybrid`

多分类含义是 OR：论文属于 `astro-ph.GA`、`astro-ph.SR`、`astro-ph.IM`
任意一个分类即可进入候选。DeepXiv 按 query/category 分别检索并去重合并；
arXiv 查询应把分类 OR 条件直接放进 API query，不要先抓无分类结果再只靠本地过滤。

如果使用 `--source deepxiv --llm-review True`，DeepXiv 仍按 query/category
分别检索并去重合并，但送入 LLM 复核的 `no-clear-title-evidence` 候选默认只取
DeepXiv score 最高的 20 篇；其余候选应保留在 title triage JSON 并标记 skipped。

默认标题 triage 分两类：

- `rule-related`：标题明确命中高速星相关规则，直接进入月度 note
- `no-clear-title-evidence`：标题证据不明确，默认只进入标题分类 JSON

如果开启 `--llm-review True`：

- 只让 LLM 判断 `no-clear-title-evidence` 是否保留
- 不改变 `rule-related` 的结果

LLM 分类或复核时，输入应包含：

- 标题
- 搜索返回的摘要
- categories

不要只发标题，除非用户明确要求。

给已有月份补 `catalog_assessment` 时，使用：

```bash
conda run -n stella-env python scripts/annotate_catalog_data.py --on 2026-03
```

判断应结合 abstract；如果记录里已有旧的 brief 字段，也可以一起参考。完成后要刷新对应 Markdown，并重建索引。

做论文结构化数据资产审阅时，使用项目内 `hvs-catalog-review` skill。
本阶段不再判断哪些资产是高速星 catalog，只梳理全文中的 `internal_tables`
和 `external_resources`，并记录每个资产在全文语境下的作用和论文可见的数据单元含义。
Review 阶段不下载外部资源；远程资源的真实结构由 extraction 阶段记录。

辅助候选清单：

```bash
conda run -n stella-env python scripts/inventory_catalog_candidates.py --arxiv-id 2402.10714
```

重建数据资产 workflow index：

```bash
conda run -n stella-env python scripts/build_catalog_index.py
```

不要手动改 `literature/catalog_workflow_index.json` 或 `literature/catalog_workflow_index.md`。
如果输出有问题，应修改 `catalog_review.json` 或索引渲染逻辑，然后重新生成。

提取已审阅数据资产时，使用项目内 `hvs-catalog-extraction` skill：

```bash
conda run -n stella-env python scripts/extract_catalog_tables.py --arxiv-id 2402.10714
```

提取同时处理 `internal_tables` 中的 `latex_table` 和 `external_resources`。LaTeX 转换顺序是
LaTeXML、Pandoc、项目内 fallback parser；表格型资产写出 ECSV，非表格资源
如 ReadMe、HTML、JSON metadata 或无法表格化的下载件也要忠实保存为 raw files。
`catalog_extraction.json` 只保留生成当前提取资产的单个 `run`，不累积历史 runs。
Extraction 阶段不补科学语义、不做高速星筛选、不强行统一 schema。外部网络抓取不得使用
搜索引擎、不得递归爬取、不得登录；只允许公网 HTTP(S)，拒绝 localhost、私网和特殊地址；
单文件下载受 `--max-external-bytes` 限制；`--all-reviewed --fetch-external Auto` 默认不联网。
全量重跑可用 `--jobs Auto` 按论文数自动并行；100 篇以上会尝试更高并发，
也可以直接指定 `--jobs N` 控制并发。

## 工程规则

- 测试环境：`conda run -n stella-env python -m unittest discover tests`
- 除非用户明确要求重新抓数据，否则不要做真实 DeepXiv 调用
- JSON 里要保留 provenance：搜索来源、query、category、score、`run_id`
- 遇到限额时，已经完成的月份仍然要保存 JSON、Markdown 和 partial summary
- 不要恢复无关改动，也不要回退用户已有的生成文件
- 如果改了依赖或环境步骤，要同时更新环境文件和相关文档

## 改动清单

改输出结构时，同时更新：

- `src/high_velocity_lit/records.py`
- `src/high_velocity_lit/markdown.py`
- `docs/outputs.md`
- 相关测试

改 CLI 参数或默认值时，同时更新：

- `scripts/fetch_high_velocity_lit.py`
- 相关新增或改动的 `scripts/*.py`
- `docs/usage.md`
- `README.md`
- CLI 测试

改依赖或环境步骤时，同时更新：

- `environment.yml`
- `docs/setup.md`
- `README.md`

新增科学能力时，先设计机器可读 JSON，再考虑 Markdown 或其它展示层。
