# 输出说明

JSON 是标准输出。Markdown 是从 JSON 生成的阅读视图。

## 标准数据

```text
literature/<arxiv_id>/    本地文献资产目录
literature/<arxiv_id>/catalog_review.json   单篇论文结构化数据资产审阅事实源
literature/<arxiv_id>/catalog_extraction.json   单篇论文数据资产提取事实源
literature/catalog_workflow_index.json       从 catalog_review.json 和 catalog_extraction.json 重建的全局数据资产工作流索引
notes/literature_notes_index.json                  从月度 JSON 重建的全局索引
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
literature/<arxiv_id>/catalog_sources/<internal_table_id>/excerpt.tex
literature/<arxiv_id>/catalog_sources/<internal_table_id>/latexml.html
literature/<arxiv_id>/catalog_sources/<internal_table_id>/latexml.stderr.txt
literature/<arxiv_id>/catalog_sources/<internal_table_id>/pandoc.html
literature/<arxiv_id>/catalog_sources/<internal_table_id>/pandoc.stderr.txt
literature/<arxiv_id>/catalog_tables/<internal_table_id>.ecsv
literature/<arxiv_id>/catalog_sources/<external_resource_id>/download-001.*
literature/<arxiv_id>/catalog_sources/<external_resource_id>/landing.html
literature/<arxiv_id>/catalog_tables/<external_resource_id>.ecsv
literature/catalog_workflow_index.md        从 catalog_workflow_index.json 生成的数据资产工作流视图
notes/literature_notes_index.md                   从 literature_notes_index.json 生成的年度视图
notes/YYYY/YYYY-MM/YYYY-MM.md    从月度 JSON 生成的月度笔记
```

表格提取阶段使用：

```text
literature/<arxiv_id>/catalog_sources/   原始数据资产文件、下载件或 LaTeX excerpt
literature/<arxiv_id>/catalog_tables/    忠实 ECSV 表格
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

`catalog_review.json` 是 Agent 结合全文审阅后的结构化数据资产目录，不表示已经完成表格抽取，也不判断这些资产是否是高速星 catalog。

- `paper`：arXiv ID、标题、月份、月度 JSON 路径、abs/pdf 链接
- `source`：论文目录、`audit.json`、源码目录、主 TeX、源码可用性
- `review`：数据资产审阅状态、时间、reviewer、总体说明
- `internal_tables`：论文 LaTeX 内部结构化表格，包含全文语境下的作用和可见数据单元含义
- `external_resources`：论文声明或引用的外部/本地资源，包含全文语境下的作用和论文可见的 declared data units

本阶段只保存 LaTeX 段落、链接、路径、证据、数据单元说明和解释；不把 LaTeX 转 ECSV，不下载外部资源，不做高速星筛选。`external_resources[].local_path` 只表示已经归档的本地资源；远程资源的真实结构由 extraction 阶段下载后记录。

## `catalog_extraction.json` 包含什么

`catalog_extraction.json` 是数据资产保全和转换阶段的事实源，输入来自
`catalog_review.json` 中列出的 `internal_tables` 和 `external_resources`。

- `paper`：arXiv ID、标题、月份
- `review`：来源 `catalog_review.json` 路径、schema 和 review 状态
- `run`：生成当前提取数据资产的单次运行参数、成功失败统计和状态；不会累积历史 runs
- `files`：原始 TeX excerpt、外部下载件、HTML/ReadMe/JSON 等非表格资源、checksum、获取状态和错误
- `tables`：ECSV 路径、caption/资源说明、label、行列数、解析状态、转换/解析工具尝试记录、warnings、观测到的列记录
- `external_resources`：外部资源定位、下载、解析日志，生成的 ECSV outputs，raw files，错误和严格停止原因 `stopped_reason`

ECSV 使用 `col_001`、`col_002` 等稳定列名，尽量忠实保留论文表格数据。Extraction 不记录人工科学语义或规范化对象 schema；高速星对象识别和规范化由后续阶段完成。

## 索引文件包含什么

`notes/literature_notes_index.json` 保存：

- 按年份汇总的统计
- 全部论文的扁平 `papers` 列表

`notes/literature_notes_index.md` 重点展示：

- 每年文献数量
- 最近文献
- 被 `catalog_assessment` 判为数据相关的文献

`literature/catalog_workflow_index.json` 保存：

- 已有 `catalog_review.json` 的论文汇总
- review 状态、状态说明、internal table 数量、external resource 数量
- 是否已有 `catalog_extraction.json`、当前 extraction 状态、表格和文件成功/失败数量
- 按年份聚合的 review / data asset / extraction 统计

`literature/catalog_workflow_index.md` 重点展示：

- 每篇已审阅或待复核论文的 review 状态和 extraction 状态
- data asset 数量，包括 internal tables 和 external resources
- 表格和 raw files 提取进度
- 指向单篇 `catalog_review.json` 和 `catalog_extraction.json` 的链接

`catalog_workflow_index` 中 review 状态和 extraction 状态是两条独立状态轴：

- review `reviewed`：数据资产审阅已在可用论文/源码上下文中完成。
- review `partial`：数据资产审阅不完整，或候选覆盖还有未决问题。
- review `needs_review`：尚未完成数据资产审阅。
- review `source_missing`：无法基于源码完成审阅；如果源码元数据同时显示可用，Markdown 中会用 `(!)` 标出不一致。
- extraction `success`：当前提取运行无表格或文件失败。
- extraction `partial`：当前提取至少产出一个表格或文件，但也有失败。
- extraction `failed`：当前提取或 manifest 读取失败。
- extraction `not_started`：review 已发现 data assets，但尚无 `catalog_extraction.json`。
- extraction `not_applicable`：review 未发现 data assets，无需提取。

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
