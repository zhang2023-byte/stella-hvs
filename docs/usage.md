# 使用方法

## 1. 抓取文献

默认批量运行：

```bash
bash scripts/run_2025_2026.sh
```

基础运行：

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03
```

只给一个月：

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03 \
  --to 2026-03
```

### 常用参数

```text
--source deepxiv|arxiv       搜索后端，默认 arxiv
--from DATE                  开始时间，可写 YYYY-MM-DD、YYYY-MM、YYYY
--to DATE                    结束时间，默认今天
--llm-review True|False      是否让 LLM 复核“标题没有明显证据”的论文，默认 False
--max-results N              每个 query/category 的返回上限，默认 20
--categories A,B,C           arXiv 分类，默认 astro-ph.GA
--min-score X                DeepXiv 分数下限，默认关闭
--progress True|False        是否显示进度条，默认 True
--token TOKEN                覆盖 DEEPXIV_TOKEN
--notes-dir PATH             输出目录，默认 notes
--logs-dir PATH              日志目录，默认 logs
```

### 默认值

```text
--to                今天
--source            arxiv
--llm-review        False
--max-results       20
--categories        astro-ph.GA
--min-score         关闭
--search-mode       hybrid
--progress          True
--sleep             0.2
--llm-base-url      默认 https://api.openai.com/v1
--llm-model         默认 gpt-4o-mini
--llm-batch-size    25
--notes-dir         notes
--logs-dir          logs
```

### 说明

- 运行开始时，脚本会打印最终参数
- 密钥不会明文打印
- 去重后会先做规则标题初筛，并写出 `YYYY-MM.title-triage.json`
- `--llm-review True` 时，只复核“标题没有明显证据”的论文
- 最终月度 note 只收录规则直判相关论文，以及被 LLM 复核确认相关的论文
- `fetch_high_velocity_lit.py` 不再调用 `DeepXiv brief`
- 默认候选检索走 `arXiv API`

## 2. 补数据相关判断

给一个月补 `catalog_assessment`：

```bash
conda run -n stella-env python scripts/annotate_catalog_data.py --on 2026-03
```

给一个范围补：

```bash
conda run -n stella-env python scripts/annotate_catalog_data.py \
  --from 2025-01 \
  --to 2025-06
```

给多个不连续月份补：

```bash
conda run -n stella-env python scripts/annotate_catalog_data.py \
  --on 2025-01,2025-03,2026-02
```

### 常用参数

```text
--on MONTH[,MONTH...]       一个或多个 YYYY-MM
--from DATE                 开始月份或日期
--to DATE                   结束月份或日期
--notes-dir PATH            notes 根目录，默认 notes
--llm-api-key KEY           覆盖 LLM_API_KEY
--llm-base-url URL          覆盖 LLM_BASE_URL
--llm-model MODEL           覆盖 LLM_MODEL
--llm-batch-size N          LLM 批大小，默认 25
--render True|False         是否刷新 Markdown 和索引，默认 True
--dry-run True|False        只显示将要修改什么
```

### 说明

- `catalog_assessment` 会先通过本地 `deepxiv` CLI 获取 `DeepXiv brief`
- 同时会读取 Introduction 的最后一段，以及各个 section 的标题和第一段
- LLM 综合使用 `title + abstract + DeepXiv brief + 引言末段 + 各 section 标题与首段 + categories`
- 只有 `catalog_assessment_context.deepxiv_brief` 会写回月度 JSON；section 摘录只在本次判断中使用
- 重新运行 `annotate_catalog_data.py` 时会重算已有 `catalog_assessment`

## 3. 重生成 Markdown

重生成全部月度 Markdown：

```bash
conda run -n stella-env python scripts/render_lit_notes.py
```

只重生成一个月：

```bash
conda run -n stella-env python scripts/render_lit_notes.py --month 2026-03
```

重建年度索引：

```bash
conda run -n stella-env python scripts/render_lit_notes.py --index-only
```

## 4. 拉取本地文献资料

给一个范围内、已经被判定为 data-related 的论文拉取本地资料：

```bash
conda run -n stella-env python scripts/pull_literature_assets.py \
  --from 2024-01 \
  --to 2026-04
```

只拉取某几个月：

```bash
conda run -n stella-env python scripts/pull_literature_assets.py \
  --on 2025-07,2025-11
```

只拉取指定论文：

```bash
conda run -n stella-env python scripts/pull_literature_assets.py \
  --arxiv-id 2402.10714,2507.07558
```

### 常用参数

```text
--on MONTH[,MONTH...]       一个或多个 YYYY-MM
--from DATE                 开始月份或日期
--to DATE                   结束月份或日期
--arxiv-id ID[,ID...]       指定 arXiv ID
--notes-dir PATH            notes 根目录，默认 notes
--literature-dir PATH       资料归档根目录，默认 literature
--timeout N                 单次网络请求超时秒数，默认 60
--dry-run True|False        只解析选择结果，不实际下载，默认 False
```

### 说明

- 只会处理 `notes/` 中 `catalog_assessment.has_observational_catalog == true` 的论文
- 每篇论文会写到 `literature/<arxiv_id>/`
- 默认尝试保存：
  - arXiv 页面 HTML
  - arXiv PDF
  - arXiv source（如果响应看起来真的是源码包）
  - 解压后的 `arxiv_source/` 目录
  - NASA ADS 页面 HTML
- 每篇论文都会生成 `audit.json`，记录各类资产的成功/失败状态

## 5. 审阅高速星对象 catalog

对已经拉取到 `literature/<arxiv_id>/` 的论文，先生成候选清单：

```bash
conda run -n stella-env python scripts/inventory_catalog_candidates.py \
  --arxiv-id 2402.10714
```

然后使用项目内 `hvs-catalog-review` skill 结合全文审阅候选表格和资源，
写出：

```text
literature/<arxiv_id>/catalog_review.json
```

本阶段只做语义审阅、来源定位和证据记录，不把 LaTeX 转 CSV，不解析 FITS，也不下载外部表格。
真正的表格提取阶段后续使用：

```text
literature/<arxiv_id>/catalog_sources/
literature/<arxiv_id>/catalog_tables/
```

重建全局 catalog 审阅索引：

```bash
conda run -n stella-env python scripts/build_catalog_index.py
```

输出：

```text
literature/catalog_index.json
literature/catalog_index.md
```

## 6. 时间写法

```text
--from 2026-03-15  表示从 2026-03-15 开始
--from 2026-03     表示从 2026-03-01 开始
--from 2026        表示从 2026-01-01 开始
--to 2026-03-15    表示到 2026-03-15 结束
--to 2026-03       表示到 2026-03-31 结束
--to 2026          表示到 2026-12-31 结束
--to none          表示到今天
```

未来日期会自动截到今天。
非法日期格式会直接报错。

## 7. 额外说明

当 DeepXiv 返回限额错误时：

- 已完成的月份仍会保存
- 脚本会写出 `logs/partial_<run_id>.json`
- 同时把结果追加到 `logs/runs.jsonl`
- 然后打印恢复命令并退出

默认搜索词：

```text
hypervelocity stars
high-velocity stars
runaway stars
unbound stars
escaping stars
```
