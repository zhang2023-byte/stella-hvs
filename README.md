# 高速星文献工作流

当前仓库主要提供这些能力：

- 按月份抓取高速星相关文献
- 用标题做规则初筛，并可选用 LLM 复核“标题没有明显证据”的论文
- 保存月度标题分类结果到 `notes/`
- 把标准结果写入 `notes/`
- 给可能是数据型文献的论文加上 `catalog_assessment`
- 给 `notes/` 中已判为数据相关的论文拉取本地资料归档到 `literature/`
- 审阅已归档论文源码中的结构化数据资产，并生成数据资产工作流索引
- 将已审阅的内部 LaTeX 表格提取为 ECSV，并保留提取 provenance
- 从论文原文和 ECSV 中抽取论文级 HVS/unbound candidates，并保留逐值 provenance
- 从 JSON 生成可读的 Markdown

## 环境准备

```bash
conda env create -f environment.yml
conda activate stella-env
cp env.example .env
```

LaTeX 表格提取推荐额外安装 LaTeXML：

```bash
brew install latexml
```

如果你要使用 `--source deepxiv`，或运行 `catalog_assessment` 的 DeepXiv 增强阅读，再在 `.env` 中填写 `DEEPXIV_TOKEN`。

详细说明见 [docs/setup.md](docs/setup.md)。

## 常用命令

基础运行：

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03
```

默认候选检索走 DeepXiv，分类覆盖 `astro-ph.GA`、`astro-ph.SR` 和
`astro-ph.IM`；DeepXiv 出现额度耗尽、token/API 错误或其它检索异常时，
本次运行后续检索会自动 fallback 到 arXiv API。

带 LLM 复核运行：

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03 \
  --llm-review True
```

给已有月份补数据相关判断：

```bash
conda run -n stella-env python scripts/annotate_catalog_data.py \
  --on 2026-03
```

这条流程会为每篇待判断论文读取 DeepXiv brief，并抓取引言末段与各 section 的标题和首段，再交给 LLM 综合判断是否属于高速星数据型文献。

给已判定为数据相关的论文拉取本地资料：

```bash
conda run -n stella-env python scripts/pull_literature_assets.py \
  --from 2024-01 \
  --to 2026-04
```

审阅单篇论文的结构化数据资产候选：

```bash
conda run -n stella-env python scripts/inventory_catalog_candidates.py \
  --arxiv-id 2402.10714
```

然后使用项目内 `hvs-catalog-review` skill 结合全文写出
`literature/<arxiv_id>/catalog_review.json`。本阶段建立论文数据资产目录，
只分 `internal_tables` 和 `external_resources`，不判断是否是高速星 catalog，
内部表格用 `internal_tables[].columns` 梳理列含义；外部资源只记录论文中的逐项描述，不转换 ECSV、不解析 FITS、不下载外部资源。

提取已审阅的内部表格：

```bash
conda run -n stella-env python scripts/extract_catalog_tables.py \
  --arxiv-id 2402.10714
```

提取阶段会写出 `literature/<arxiv_id>/catalog_extraction.json`、
`catalog_sources/<id>/...` 和 `catalog_tables/<id>.ecsv`。LaTeX 表格优先使用
LaTeXML，然后是 Pandoc，最后回退到项目内 parser。外部资源不进入提取阶段；
它们只保留在 `catalog_review.json` 中作为论文声明的资源描述。
`catalog_extraction.json` 只保留生成当前提取资产的单个 `run`，不累积历史 runs。
ECSV 保持论文内部表格结构，不代表已经进入统一对象 schema；高速星对象识别由后续阶段完成。
全量重跑时可以给 `--all-reviewed` 加 `--jobs Auto` 按论文并行；
100 篇以上默认会尝试 12 个 jobs。你也可以直接指定 `--jobs N`。

抽取单篇论文中的 HVS/unbound candidates 时，使用项目内
`hvs-candidates-extraction` skill 写出
`literature/<arxiv_id>/literature_hvs_candidates.json`。本阶段以论文证据为纳入边界，
数值事实优先来自 ECSV，候选身份、方法链和缺失说明来自原文。

```bash
conda run -n stella-env python scripts/validate_hvs_candidates.py \
  --arxiv-id 2402.10714
```

校验脚本只检查 JSON 结构和 provenance 行列是否自洽，不替代 Agent 做科学判断。

清理旧 catalog workflow 产物、保留原始论文归档：

```bash
conda run -n stella-env python scripts/cleanup_catalog_workflow_outputs.py --dry-run True
```

重建 catalog 工作流索引：

```bash
conda run -n stella-env python scripts/build_catalog_index.py
```

该索引以 `catalog_review.json` 为入口，并在存在 `catalog_extraction.json` 时同时展示
内部表格提取状态、ECSV 表格和 excerpt 文件成功失败数量。Review 状态和 extraction 状态分开
展示，`partial` 不会跨阶段混用。

从 JSON 重生成 Markdown：

```bash
conda run -n stella-env python scripts/render_lit_notes.py
```

更多参数见 [docs/usage.md](docs/usage.md)。

## 文档

- 环境说明：[docs/setup.md](docs/setup.md)
- 使用方法：[docs/usage.md](docs/usage.md)
- 输出说明：[docs/outputs.md](docs/outputs.md)
- 标题分类规则：[docs/title-triage.md](docs/title-triage.md)
- 仓库内代理约束：[AGENTS.md](AGENTS.md)

## 目录

```text
scripts/fetch_high_velocity_lit.py   月度文献抓取主入口
scripts/annotate_catalog_data.py     给月度 JSON 补 catalog_assessment
scripts/pull_literature_assets.py    拉取 data-related 文献的本地资料归档
scripts/inventory_catalog_candidates.py   列出单篇论文的数据资产审阅候选
scripts/extract_catalog_tables.py    从 catalog_review.json 提取内部 LaTeX 表格为 ECSV
scripts/validate_hvs_candidates.py    校验 literature_hvs_candidates.json 的结构和 provenance
scripts/cleanup_catalog_workflow_outputs.py   清理旧 catalog review/extraction 产物
scripts/build_catalog_index.py       从 catalog_review.json 和 catalog_extraction.json 重建数据资产工作流索引
scripts/render_lit_notes.py          从 JSON 重生成 Markdown
docs/                                说明文档
literature/                          本地文献资产归档（默认不纳入 Git）
notes/                               月度标题分类 JSON、月度 JSON、月度 Markdown、年度索引
src/high_velocity_lit/               核心实现
tests/                               测试
```
