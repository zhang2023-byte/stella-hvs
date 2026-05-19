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

修复已归档论文的 ADS metadata 和本文献级 HVS candidates bibcode：

```bash
conda run -n stella-env python scripts/repair_ads_metadata.py
```

需要覆盖刷新全部 ADS API metadata JSON 时：

```bash
conda run -n stella-env python scripts/repair_ads_metadata.py --force True
```

脚本会读取 `.env` 中的 `ADS_API_TOKEN`，用 ADS API 按 arXiv ID 查询本文献
bibcode，并把完整 ADS API 响应保存为 `ads_metadata.json`。不再爬取 ADS 页面 HTML。
API 失败或查不到时保持字段为空并报告原因，不构造 arXiv 形式 bibcode。

初始化单篇论文的结构化数据资产审阅模板：

```bash
conda run -n stella-env python scripts/init_catalog_review.py \
  --arxiv-id 2402.10714
```

模板由 Pydantic schema 代码生成，Agent 只填论文语义空位。然后使用项目内
`hvs-catalog-review` skill 结合全文补全 `literature/<arxiv_id>/catalog_review.json`。
本阶段建立论文数据资产目录，只分 `internal_tables` 和 `external_resources`，不判断是否是高速星 catalog，
内部表格用 `internal_tables[].columns` 梳理列含义；外部资源只记录论文中的逐项描述，不转换 ECSV、不解析 FITS、不下载外部资源。
补全后校验：

```bash
conda run -n stella-env python scripts/validate_catalog_review.py \
  --arxiv-id 2402.10714 \
  --require-complete
```

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
提取脚本写出前会用 Pydantic schema 校验 `catalog_extraction.json`；也可以单独运行：

```bash
conda run -n stella-env python scripts/validate_catalog_extraction.py \
  --arxiv-id 2402.10714 \
  --require-reviewed
```

抽取单篇论文中的 HVS/unbound candidates 时，使用项目内
`hvs-candidates-extraction` skill。先生成代码 schema 模板：

```bash
conda run -n stella-env python scripts/init_hvs_candidates.py \
  --arxiv-id 2402.10714
```

然后由 Agent 补全
`literature/<arxiv_id>/literature_hvs_candidates.json`。本阶段使用
`stella.literature_hvs_candidates.v5`，以正文证据为纳入边界：只纳入文章认为可能从
银河系/Galactic potential 非束缚或逃逸的对象。普通 runaway、星团逃逸、本地 GC
非束缚但文章说明整体仍银河系束缚的对象、以及文章已判定 bound 的对象不进入
`candidates[]`。

抽取顺序应先读正文确定 candidate 身份、非束缚证据和 `candidate_origin`，再用
`catalog_review.json`、`catalog_extraction.json` 与 ECSV 提取数值。`core`/`extra[]`
的参数要同时保留 `raw_value`、清洗后的 `value`、逐值 `source_refs` 和字段级
direct-producer `method_refs`。候选标识统一写在 `identifiers` 下：
`record_id` 是 Stella 内部 `<arxiv_id>:cand-001` 记录号，`paper_candidate_id`
是论文内首选展示名，`gaia_source_id` 是空字符串或严格 `Gaia DR3/EDR3/DR2 ...`
机器标识，`all[]` 收录论文中出现过的所有名称和编号并逐项给出 `source_refs`。
`method_chain[]` 使用本文内局部 `step-01`、`step-02`
ID、受控 `step_type` 和 `depends_on[]` 记录上游依赖；引用其它工作的 candidate
需要记录正文 cite 行以及 `.bib`/`.bbl` 条目。

```bash
conda run -n stella-env python scripts/validate_hvs_candidates.py \
  --arxiv-id 2402.10714 \
  --require-complete
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
scripts/repair_ads_metadata.py       用 ADS API 补本文献级 bibcode
scripts/inventory_catalog_candidates.py   列出单篇论文的数据资产审阅候选
scripts/init_catalog_review.py       从代码 schema 生成 catalog_review.json 模板
scripts/extract_catalog_tables.py    从 catalog_review.json 提取内部 LaTeX 表格为 ECSV
scripts/validate_catalog_review.py    校验 catalog_review.json 的结构和 source refs
scripts/validate_catalog_extraction.py 校验 catalog_extraction.json 的结构和提取产物
scripts/init_hvs_candidates.py        从代码 schema 生成 literature_hvs_candidates.json 模板
scripts/validate_hvs_candidates.py    校验 literature_hvs_candidates.json 的结构和 provenance
scripts/generate_schema_docs.py       从 Pydantic schema 生成 skill schema 参考文档
scripts/cleanup_catalog_workflow_outputs.py   清理旧 catalog review/extraction 产物
scripts/build_catalog_index.py       从 catalog_review.json 和 catalog_extraction.json 重建数据资产工作流索引
scripts/render_lit_notes.py          从 JSON 重生成 Markdown
docs/                                说明文档
literature/                          本地文献资产归档（默认不纳入 Git）
notes/                               月度标题分类 JSON、月度 JSON、月度 Markdown、年度索引
src/high_velocity_lit/               核心实现
tests/                               测试
```
