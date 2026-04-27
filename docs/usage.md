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
- 资料下载只允许公网 HTTP(S)，拒绝本机/私网/特殊地址；PDF/source 下载会流式读取并按大小上限停止
- source 解压会拒绝绝对路径、`..` 和任何写出解压目录的 archive member

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

重建全局 catalog 审阅索引：

```bash
conda run -n stella-env python scripts/build_catalog_index.py
```

输出：

```text
literature/catalog_index.json
literature/catalog_index.md
```

## 6. 提取已审阅 catalog 表格

推荐先安装 LaTeXML：

```bash
brew install latexml
```

提取脚本会按顺序尝试 LaTeXML、Pandoc 和项目内 fallback parser；同一次运行也会处理
`catalog_review.json` 中记录的外部机器可读 catalog。

给单篇论文提取所有已审阅的 LaTeX catalog 表格和 external catalog：

```bash
conda run -n stella-env python scripts/extract_catalog_tables.py \
  --arxiv-id 2402.10714
```

只提取一个候选表格：

```bash
conda run -n stella-env python scripts/extract_catalog_tables.py \
  --arxiv-id 2402.10714 \
  --candidate-id table-tab-72dr3
```

只提取一个外部资源：

```bash
conda run -n stella-env python scripts/extract_catalog_tables.py \
  --arxiv-id 2509.24010 \
  --resource-id resource-local-final-catalog-fits
```

提取所有已审阅且有 catalog candidate 的论文：

```bash
conda run -n stella-env python scripts/extract_catalog_tables.py \
  --all-reviewed
```

### 常用参数

```text
--arxiv-id ID              提取单篇论文
--all-reviewed             提取所有 reviewed 且有 catalog candidate 或 external resource 的论文
--candidate-id ID          只提取单个 catalog_candidates[].id，需配合 --arxiv-id
--resource-id ID           只提取单个 external_resources[].id，需配合 --arxiv-id
--fetch-external Auto|True|False
                           外部资源网络策略；Auto 下单篇联网、批量不联网
--max-external-files N     每个外部资源最多下载 N 个机器可读文件，默认 5
--max-external-bytes N     单个外部资源下载硬上限，默认 52428800
--external-timeout N       外部资源 HTTP 超时秒数，默认 30
--agent-locator Off|Always
                           LLM Agent 页面定位；默认 Always，对 HTML landing page 始终调用 Agent
--llm-api-key KEY          Agent locator 使用的 OpenAI-compatible API key；也可用 LLM_API_KEY 等环境变量
--llm-base-url URL         Agent locator API base URL，默认 LLM_BASE_URL 或 https://api.openai.com/v1
--llm-model MODEL          Agent locator 模型，默认 LLM_MODEL 或 gpt-4o-mini
--literature-dir PATH      文献归档根目录，默认 literature
--dry-run True|False       只解析并报告，不写文件，默认 False
--overwrite True|False     覆盖已有 excerpt.tex 和 CSV，默认 False
```

### 说明

- LaTeX 表格会写出 `catalog_sources/<candidate_id>/excerpt.tex`、转换器 HTML/log artifacts 和 `catalog_tables/<candidate_id>.csv`。
- LaTeX 解析失败也会保留 `excerpt.tex`，便于复查失败上下文。
- 外部资源会优先解析 `local_path`，其次抓取明确 URL；没有 `url/local_path` 时，会读取已有或可获取的 ADS HTML，并交给同一个 bounded Agent locator 选择候选链接。
- `--agent-locator` 默认是 `Always`：明确 URL 返回 HTML landing page 或 ADS HTML 需要定位下载项时，下载链接选择交给 LLM Agent。Agent 只接收页面标题、可见文本摘录、外部资源 evidence 和页面中提取出的链接候选；网页正文、链接文字和文件名都被视为不可信数据，它只能返回候选 ID，不能发明 URL。脚本仍会校验链接、下载类型、文件大小和解析结果，并把 `agent_locator_context.json`、`agent_locator_response.json` 作为 provenance 写入 `catalog_sources/<resource_id>/`。如果未配置 API key、LLM 连不上、返回格式错误或选择了无效候选，流程不会崩溃；对应错误会写入 `external_resources[].locator_attempts[]`、`error` 和 `stopped_reason`。需要完全关闭时使用 `--agent-locator Off`，此时 HTML landing page 和 ADS HTML 只记录停止原因，不下载页面链接。
- 外部抓取不会使用搜索引擎、不会递归爬取、不会登录；只允许公网 HTTP(S)，拒绝 localhost、私网 IP、link-local、loopback、multicast、reserved 地址和无 host URL；遇到占位 URL、unsupported content、超时、超过文件数、超过大小上限或解析失败时，会在 JSON 中记录 `stopped_reason`。
- 外部机器可读后缀统一支持 `.csv/.tsv/.txt/.dat/.tbl/.mrt/.ecsv/.fits/.fit/.fits.gz/.vot/.votable/.xml`。
- 重跑时，只有 source hash 与列身份匹配，才会保留已人工审核的 `usage` 和列语义；否则语义状态会回到 `needs_agent_review`。
- 每篇论文会写出 `catalog_extraction.json`，记录来源、运行日志、转换/下载/定位尝试结果、成功失败、CSV 路径、列头、单位行和待补充的列语义字段。
- CSV 使用 `col_001`、`col_002` 这类稳定列名，尽量忠实保留论文表格，不表示已经完成统一对象 schema。
- 使用项目内 `hvs-catalog-extraction` skill 时，Agent 需要在提取后手动补充每列 `physical_quantity`、`meaning`、`source_of_definition`、`notes` 和表格 `usage`。

## 7. 时间写法

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

## 8. 额外说明

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
