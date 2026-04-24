# 输出说明

JSON 是标准输出。Markdown 是从 JSON 生成的阅读视图。

## 标准数据

```text
literature/<arxiv_id>/    本地文献资产目录
literature/<arxiv_id>/catalog_review.json   单篇 catalog 审阅事实源
literature/catalog_index.json       从 catalog_review.json 重建的全局 catalog 审阅索引
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
literature/catalog_index.md        从 catalog_index.json 生成的 catalog 审阅视图
notes/index.md                   从 index.json 生成的年度视图
notes/YYYY/YYYY-MM/YYYY-MM.md    从月度 JSON 生成的月度笔记
```

后续真正表格提取阶段预留：

```text
literature/<arxiv_id>/catalog_sources/   原始 catalog 来源文件、下载表格或 LaTeX excerpt
literature/<arxiv_id>/catalog_tables/    规范化后的 CSV、schema、转换日志
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
- `error`

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

本阶段只保存 LaTeX 段落、链接、路径、证据和解释；不把 LaTeX 转 CSV，不下载外部表格。

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
- review 状态、catalog 候选数量、外部资源数量
- 按年份聚合的 reviewed / has catalog / needs review 统计

`literature/catalog_index.md` 重点展示：

- 每篇已审阅或待复核论文
- catalog 候选数量
- 外部资源数量
- 指向单篇 `catalog_review.json` 的链接

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
