# 高速星文献工作流

当前仓库主要提供这些能力：

- 按月份抓取高速星相关文献
- 用标题做规则初筛，并可选用 LLM 复核“标题没有明显证据”的论文
- 保存月度标题分类结果到 `notes/`
- 把标准结果写入 `notes/`
- 给可能是数据型文献的论文加上 `catalog_assessment`
- 给 `notes/` 中已判为数据相关的论文拉取本地资料归档到 `literature/`
- 审阅已归档论文源码中的高速星对象 catalog，并生成 catalog 审阅索引
- 从 JSON 生成可读的 Markdown

## 环境准备

```bash
conda env create -f environment.yml
conda activate stella-env
cp scripts/env.example .env
```

如果你要使用 `--source deepxiv`，或运行 `catalog_assessment` 的 DeepXiv 增强阅读，再在 `.env` 中填写 `DEEPXIV_TOKEN`。

详细说明见 [docs/setup.md](docs/setup.md)。

## 常用命令

默认批量运行：

```bash
bash scripts/run_2025_2026.sh
```

基础运行：

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03
```

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

审阅单篇论文的高速星对象 catalog 候选：

```bash
conda run -n stella-env python scripts/inventory_catalog_candidates.py \
  --arxiv-id 2402.10714
```

然后使用项目内 `hvs-catalog-review` skill 结合全文写出
`literature/<arxiv_id>/catalog_review.json`。本阶段只做审阅和来源定位，
不转换 CSV、不解析 FITS、不下载外部表格。

重建 catalog 审阅索引：

```bash
conda run -n stella-env python scripts/build_catalog_index.py
```

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
scripts/inventory_catalog_candidates.py   列出单篇论文的 catalog 审阅候选
scripts/build_catalog_index.py       从 catalog_review.json 重建 catalog 审阅索引
scripts/render_lit_notes.py          从 JSON 重生成 Markdown
scripts/run_2025_2026.sh             批量运行脚本
docs/                                说明文档
literature/                          本地文献资产归档（默认不纳入 Git）
notes/                               月度标题分类 JSON、月度 JSON、月度 Markdown、年度索引
src/high_velocity_lit/               核心实现
tests/                               测试
```
