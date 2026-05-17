# 输出说明

JSON 是标准输出。Markdown 是从 JSON 生成的阅读视图。

## 标准数据

```text
literature/<arxiv_id>/    本地文献资产目录
literature/<arxiv_id>/catalog_review.json   单篇论文结构化数据资产审阅事实源
literature/<arxiv_id>/catalog_extraction.json   单篇论文内部表格提取事实源
literature/<arxiv_id>/literature_hvs_candidates.json   单篇论文 HVS/unbound candidates 抽取事实源
literature/literature_catalog_index.json       从 catalog_review.json 和 catalog_extraction.json 重建的全局数据资产工作流索引
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
literature/<arxiv_id>/ads_metadata.json
literature/<arxiv_id>/catalog_sources/<internal_table_id>/excerpt.tex
literature/<arxiv_id>/catalog_sources/<internal_table_id>/latexml.html
literature/<arxiv_id>/catalog_sources/<internal_table_id>/latexml.stderr.txt
literature/<arxiv_id>/catalog_sources/<internal_table_id>/pandoc.html
literature/<arxiv_id>/catalog_sources/<internal_table_id>/pandoc.stderr.txt
literature/<arxiv_id>/catalog_tables/<internal_table_id>.ecsv
literature/literature_catalog_index.md        从 literature_catalog_index.json 生成的数据资产工作流视图
notes/literature_notes_index.md                   从 literature_notes_index.json 生成的年度视图
notes/YYYY/YYYY-MM/YYYY-MM.md    从月度 JSON 生成的月度笔记
```

表格提取阶段使用：

```text
literature/<arxiv_id>/catalog_sources/   原始 LaTeX excerpt 和转换 artifacts；stdout/stderr 存文件，extraction JSON 只记录路径
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
- `ads_api`
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

`catalog_review.json` 是 Agent 结合全文审阅后的结构化数据资产目录，不表示已经完成表格抽取，也不判断这些资产是否是高速星 catalog。文件结构由 Pydantic schema 和 `scripts/init_catalog_review.py` 生成，Agent 只补全论文语义字段。

- `paper`：arXiv ID、标题、月份、月度 JSON 路径、abs/pdf 链接
- `source`：论文目录、`audit.json`、源码目录、主 TeX、源码可用性
- `review`：数据资产审阅状态、时间、reviewer、总体说明
- `internal_tables`：论文 LaTeX 内部结构化表格，包含全文语境下的作用和可见 `columns[]` 列定义
- `external_resources`：论文声明或引用的外部/本地资源，逐项保存论文中的整体描述、链接、路径、证据和备注

本阶段只保存 LaTeX 段落、链接、路径、证据、内部表 `columns[]` 列说明，以及外部资源在论文中的描述；不把 LaTeX 转 ECSV，不下载外部资源，不分析远程资源内部结构，不做高速星筛选。`external_resources[].local_path` 只表示已经归档的本地资源。
完成后应使用 `scripts/validate_catalog_review.py --require-complete` 校验结构、枚举、路径、source line refs 和是否仍是未填空模板。

## `catalog_extraction.json` 包含什么

`catalog_extraction.json` 是内部 LaTeX 表格保全和转换阶段的事实源，输入来自
`catalog_review.json` 中列出的 `internal_tables`。

- `paper`：arXiv ID、标题、月份
- `review`：来源 `catalog_review.json` 路径、schema 和 review 状态
- `run`：生成当前提取内部表格的单次运行参数、成功失败统计和状态；不会累积历史 runs
- `files`：原始 TeX excerpt、checksum、保存状态和错误
- `tables`：ECSV 路径、caption、label、行列数、解析状态、转换/解析工具尝试记录、warnings、观测到的列记录

ECSV 使用 `col_001`、`col_002` 等稳定列名，尽量忠实保留论文表格数据。Extraction 不记录人工科学语义或规范化对象 schema；高速星对象识别和规范化由后续阶段完成。
该文件由 `scripts/extract_catalog_tables.py` 生成并在写出前通过 Pydantic schema 校验；Agent 不应手工填改。最终检查可加 `scripts/validate_catalog_extraction.py --require-reviewed`，防止从 `needs_review` 的审阅模板继续下游流程。

## `literature_hvs_candidates.json` 包含什么

`literature_hvs_candidates.json` 是单篇论文中可能从银河系/Galactic potential
非束缚或逃逸的 HVS/unbound candidates 抽取事实源。抽取由论文正文驱动；
`catalog_review.json`、`catalog_extraction.json` 和已生成的 ECSV 只用于定位表格和数值。
文件 skeleton 由 `scripts/init_hvs_candidates.py` 从 Pydantic schema 生成，Agent 只补全候选、方法链、数值和 provenance。

- `paper`：arXiv ID、bibcode（来自 ADS，优先用 `audit.json` 的 `ads_metadata.ads_bibcode`）、标题、月份、月度 JSON 路径和 abs/pdf 链接
- `inputs`：本次抽取参考的 paper 目录、review/extraction JSON 和 ECSV 路径
- `extraction`：候选抽取状态、时间、执行者和摘要
- `method_chain`：论文级原子方法 DAG，包括巡天输入、样本筛选、质量过滤、距离估计、RV 测量、速度计算、势模型、轨道积分、束缚概率或逃逸判断等步骤；ID 使用 `step-01`、`step-02` 等本文内局部顺序号，`step_type` 使用受控词表，`depends_on[]` 只列直接上游 step
- `candidates`：正文证据锚定的 Galactic-unbound HVS/unbound candidates；每个候选包含 identifiers、候选判断、`candidate_origin`、观测 6D、派生运动学、束缚/非束缚概率和 `extra[]`
- `candidate_groups_considered`：审阅过但未纳入的候选组、表格或对象集合，尤其用于 `no_candidates` 结果

纳入候选的依据必须来自论文自身正文：论文明确把对象作为可能从银河系/Galactic
potential 非束缚或逃逸的 HVS、unbound、escaping、hyper-runaway 或等价候选讨论、
列出或评估。普通 runaway、星团逃逸、本地 GC 非束缚但文章说明整体仍银河系束缚的对象、
以及文章已判定 bound 的对象不进入 `candidates[]`。固定速度阈值只能作为 sanity check，
不能作为唯一纳入理由。

`candidate_origin.origin_type` 区分 `introduced_by_this_paper` 和
`cited_from_literature`。“首次给出”指本文首次把对象作为可能 Galactic-unbound/HVS
candidate 提出；已知对象即使本文重新分析，也标为 `cited_from_literature`，并用
`paper_reassesses_unbound_status=true` 表示本文重新评估。cited candidates 必须给出正文
cite 行和 `.bib`/`.bbl` 条目。

`core` 和 `extra[]` 中每个参数都必须有 `raw_value`、清洗后的 `value`、逐值 source
provenance 和字段级 direct-producer `method_refs`。
`raw_value` 保持和 ECSV cell 或原文值一致以保证可追溯；`value`、`error`、
`lower_error`、`upper_error` 用于机器读取，不能保留 LaTeX 命令、花括号、`$`、`_`、`^`
或 `+/-`。ECSV 来源需要精确到文件路径、物理行号、机器列名、列头和原始单元格文本；
原文来源需要精确到 TeX/文本文件路径和行号范围。`method_refs` 引用同一文件内
直接生成该值的 `method_chain[]` `step-XX` ID；完整方法 lineage 由该 step 的
`depends_on[]` 递归展开得到。

## 索引文件包含什么

`notes/literature_notes_index.json` 保存：

- 按年份汇总的统计
- 全部论文的扁平 `papers` 列表

`notes/literature_notes_index.md` 重点展示：

- 每年文献数量
- 最近文献
- 被 `catalog_assessment` 判为数据相关的文献

`literature/literature_catalog_index.json` 保存：

- 已有 `catalog_review.json` 的论文汇总
- review 状态、状态说明、internal table 数量、external resource 数量
- 是否已有 `catalog_extraction.json`、当前内部表格 extraction 状态、表格和 excerpt 文件成功/失败数量
- 按年份聚合的 review / data asset / extraction 统计

`literature/literature_catalog_index.md` 重点展示：

- 每篇已审阅或待复核论文的 review 状态和 extraction 状态
- data asset 数量，包括 internal tables 和 external resources
- 内部表格和 excerpt 文件提取进度
- 指向单篇 `catalog_review.json` 和 `catalog_extraction.json` 的链接

`literature_catalog_index` 中 review 状态和 extraction 状态是两条独立状态轴：

- review `reviewed`：数据资产审阅已在可用论文/源码上下文中完成。
- review `partial`：数据资产审阅不完整，或候选覆盖还有未决问题。
- review `needs_review`：尚未完成数据资产审阅。
- review `source_missing`：无法基于源码完成审阅；如果源码元数据同时显示可用，Markdown 中会用 `(!)` 标出不一致。
- extraction `success`：当前提取运行无表格或文件失败。
- extraction `partial`：当前提取至少产出一个表格或文件，但也有失败。
- extraction `failed`：当前提取或 manifest 读取失败。
- extraction `not_started`：review 已发现内部表格，但尚无 `catalog_extraction.json`。
- extraction `not_applicable`：review 未发现内部表格；即使只有外部资源，也无需进入 extraction。

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
