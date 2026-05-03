# 输出说明

JSON 是标准输出。Markdown 是从 JSON 生成的阅读视图。

## 标准数据

```text
literature/<arxiv_id>/    本地文献资产目录
literature/<arxiv_id>/catalog_review.json   单篇 catalog 审阅事实源
literature/<arxiv_id>/catalog_extraction.json   单篇 catalog 表格提取事实源
literature/catalog_index.json       从 catalog_review.json 和 catalog_extraction.json 重建的全局 catalog 工作流索引
notes/index.json                  从月度 JSON 重建的全局索引
notes/YYYY/YYYY-MM/YYYY-MM.json   月度标准记录
notes/YYYY/YYYY-MM/YYYY-MM.title-triage.json   月度标题初筛与复核记录
```

## 生成文件

```text
literature/<arxiv_id>/audit.json   单篇文献资产拉取审计记录
literature/<arxiv_id>/arxiv_abs.html
literature/<arxiv_id>/arxiv.pdf
literature/<arxiv_id>/arxiv_source*
literature/<arxiv_id>/arxiv_source/...
literature/<arxiv_id>/ads_abstract.html
literature/<arxiv_id>/catalog_sources/<candidate_id>/excerpt.tex
literature/<arxiv_id>/catalog_sources/<candidate_id>/latexml.html
literature/<arxiv_id>/catalog_sources/<candidate_id>/latexml.stderr.txt
literature/<arxiv_id>/catalog_sources/<candidate_id>/pandoc.html
literature/<arxiv_id>/catalog_sources/<candidate_id>/pandoc.stderr.txt
literature/<arxiv_id>/catalog_tables/<candidate_id>.csv
literature/<arxiv_id>/catalog_sources/<resource_id>/download-001.csv
literature/<arxiv_id>/catalog_sources/<resource_id>/landing.html
literature/<arxiv_id>/catalog_tables/<resource_id>.csv
literature/catalog_index.md        从 catalog_index.json 生成的 catalog 工作流视图
notes/index.md                   从 index.json 生成的年度视图
notes/YYYY/YYYY-MM/YYYY-MM.md    从月度 JSON 生成的月度笔记
```

表格提取阶段使用：

```text
literature/<arxiv_id>/catalog_sources/   原始 catalog 来源文件或 LaTeX excerpt
literature/<arxiv_id>/catalog_tables/    忠实 CSV 表格
```

## 本地日志

```text
logs/arxiv_metadata_<timestamp>.json
logs/partial_<timestamp>.json
logs/runs.jsonl
logs/run_<timestamp>.log
```

`logs/` 不纳入 Git。
`literature/` 默认也不纳入 Git。

## 月度 JSON 包含什么

- 时间范围和 `run_id`
- 实际使用的搜索参数
- 每个 query / category 的搜索日志
- 月份过滤统计
- arXiv metadata 回填统计
- 最终判定和高速星相关、并写入月度 note 的论文列表
- 匹配到的 query 和 category
- 搜索返回的摘要
- 可选的 `catalog_assessment`
- 可选的 `catalog_assessment_context.deepxiv_brief`

## 标题分类 JSON 包含什么

- 规则直判相关的论文：`rule_related_papers`
- 标题没有明显证据的论文：`no_clear_title_evidence_papers`
- 若开启 `--llm-review True`，后者会额外包含 `review`
- 月度搜索日志与筛选统计

## 月度 Markdown 怎么组织

- 只列最终收录进月度 note 的论文
- 不再展示 direct / weak 分层
- 顶部保留规则初筛、LLM 复核和最终收录数量统计
- 如果有 `catalog_assessment`，会显示在对应论文旁边

## `catalog_assessment_context` 包含什么

- `deepxiv_brief.source`
- `deepxiv_brief.fetched`
- `deepxiv_brief.error`
- `deepxiv_brief.tldr`
- `deepxiv_brief.keywords`
- `deepxiv_brief.citations`
- `deepxiv_brief.fetched_at`

这里不会持久化 section 摘录。Introduction 末段和各 section 首段只在 `catalog_assessment` 运行时作为临时上下文使用。

## `literature/` 审计记录包含什么

- `arxiv_id`
- `title`
- `month`
- `source_note_json`
- `folder_name`
- `run_at`
- `ads_metadata`
- `arxiv_abs`
- `arxiv_pdf`
- `arxiv_source`
- `ads_abstract`

其中每个资产状态都会记录：

- `url`
- `success`
- `status_code`
- `content_type`
- `final_url`
- `local_path`
- `size_bytes`
- `error`

资产下载只允许公网 HTTP(S)，并流式读取到大小上限；被安全边界或大小上限拦截时，
对应错误会写入资产记录。源码包解压会拒绝绝对路径、`..` 和目录外写入。

`arxiv_source` 还会额外记录：

- `extracted`
- `extract_dir`
- `extract_error`
- `extract_skipped_existing`
- `source_unavailable_on_arxiv`
- `source_unavailable_reason`

## `catalog_review.json` 包含什么

`catalog_review.json` 是 Agent 结合全文审阅后的事实源，不表示已经完成表格抽取。

- `paper`：arXiv ID、标题、月份、月度 JSON 路径、abs/pdf 链接
- `source`：论文目录、`audit.json`、源码目录、主 TeX、源码可用性
- `review`：审阅状态、时间、reviewer、总体说明
- `catalog_candidates`：被判定为高速星对象 catalog 的表格或资源
- `external_resources`：外部托管或本地机器可读资源及评论
- `rejected_candidates`：被排除或不确定的候选及原因

本阶段只保存 LaTeX 段落、链接、路径、证据和解释；不把 LaTeX 转 CSV，不下载外部表格，也不记录表格列 schema。后续表格抽取应以 `source_refs.start_line` 和 `source_refs.end_line` 定位原始 TeX，并在 `catalog_sources/` 和 `catalog_tables/` 阶段写入精确列含义。

## `catalog_extraction.json` 包含什么

`catalog_extraction.json` 是表格提取阶段的事实源，输入来自
`catalog_review.json` 中已经确认的候选。

- `paper`：arXiv ID、标题、月份
- `review`：来源 `catalog_review.json` 路径、schema 和 review 状态
- `runs`：每次提取的时间、参数、成功失败统计和状态
- `sources`：原始 TeX 路径、行号、摘录文件，或 external resource 的本地/下载来源、checksum、获取状态和错误
- `tables`：CSV 路径、caption/资源说明、label、行列数、解析状态、转换/解析工具尝试记录、warnings、列记录和使用说明
- `external_resources`：外部资源定位、下载、解析日志，生成的 table outputs，错误和严格停止原因 `stopped_reason`；默认的 `Always` Agent locator 会在明确 URL 返回 HTML landing page 或 ADS HTML 需要定位下载项时运行，并记录 bounded agent 的页面候选选择、LLM 缺失/连接/格式错误、`agent_locator_context.json` 和 `agent_locator_response.json`

CSV 使用 `col_001`、`col_002` 等稳定列名，尽量忠实保留论文表格数据。
列的 `original_header`、`unit_text`、`physical_quantity`、`meaning`、
`original_name`、`description`、`format`、`data_type`、`null_values`、
`source_of_definition`、`notes`、`semantic_status` 和 `confidence` 保存在 JSON 中。
提取器会自动填列头、单位和基础数据类型；
Agent 使用 `hvs-catalog-extraction` skill 后，需要结合表格 caption、footnote、
正文引用和上下文手动补充每列物理含义与表格 `usage`。
`tables[].source_sha256` 和 `sources[].sha256` 用于重跑时判断旧语义能否保留；
只有 source hash 与列身份（稳定列名、原始列头/列名、单位、描述、格式）匹配时，
已审核的 `usage` 和列语义才会自动保留，否则回到 `needs_agent_review`。

## 索引文件包含什么

`notes/index.json` 保存：

- 按年份汇总的统计
- 全部论文的扁平 `papers` 列表

`notes/index.md` 重点展示：

- 每年文献数量
- 最近文献
- 被 `catalog_assessment` 判为数据相关的文献

`literature/catalog_index.json` 保存：

- 已有 `catalog_review.json` 的论文汇总
- review 状态、状态说明、catalog 候选数量、外部资源数量
- 是否已有 `catalog_extraction.json`、最近一次 extraction 状态、表格和外部资源成功/失败数量
- 表格 usage 与列语义 reviewed 进度
- 按年份聚合的 review / catalog source / extraction / semantic 统计

`literature/catalog_index.md` 重点展示：

- 每篇已审阅或待复核论文的 review 状态和 extraction 状态
- catalog source 数量，包括 LaTeX catalog candidates 和 external resources
- 表格、外部资源、语义补全进度
- 指向单篇 `catalog_review.json` 和 `catalog_extraction.json` 的链接

`catalog_index` 中 review 状态和 extraction 状态是两条独立状态轴：

- review `reviewed`：catalog 审阅已在可用论文/源码上下文中完成。
- review `partial`：catalog 审阅不完整，或候选覆盖还有未决问题。
- review `needs_review`：尚未完成 catalog 审阅。
- review `source_missing`：无法基于源码完成审阅；如果源码元数据同时显示可用，Markdown 中会用 `(!)` 标出不一致。
- extraction `success`：最近一次提取运行无表格失败。
- extraction `partial`：最近一次提取至少产出一个表格，但也有失败。
- extraction `failed`：最近一次提取或 manifest 读取失败。
- extraction `not_started`：review 已发现 catalog source，但尚无 `catalog_extraction.json`。
- extraction `not_applicable`：review 未发现 catalog source，无需提取。

## 主要日志事件

```text
start
query
arxiv_metadata
classify
month_done
partial_finish
finish
```
