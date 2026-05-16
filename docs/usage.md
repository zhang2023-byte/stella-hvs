# 使用方法

## 1. 抓取文献

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
--source deepxiv|arxiv       搜索后端，默认 deepxiv；DeepXiv 异常时自动 fallback 到 arXiv
--from DATE                  开始时间，可写 YYYY-MM-DD、YYYY-MM、YYYY
--to DATE                    结束时间，默认今天
--llm-review True|False      是否让 LLM 复核“标题没有明显证据”的论文，默认 False
--max-results N              每个 arXiv query 或 DeepXiv query/category 的返回上限，默认 20
--deepxiv-llm-review-max-candidates N
                             DeepXiv 模式下送入 LLM 复核的 no-clear-title-evidence 候选上限，默认 20
--categories A,B,C           arXiv 分类，默认 astro-ph.GA,astro-ph.SR,astro-ph.IM
--min-score X                DeepXiv 分数下限，默认关闭
--progress True|False        是否显示进度条，默认 True
--token TOKEN                覆盖 DEEPXIV_TOKEN
--notes-dir PATH             输出目录，默认 notes
--logs-dir PATH              日志目录，默认 logs
```

### 默认值

```text
--to                今天
--source            deepxiv
--llm-review        False
--max-results       20
--categories        astro-ph.GA,astro-ph.SR,astro-ph.IM
--min-score         关闭
--search-mode       hybrid
--progress          True
--sleep             0.2
--llm-base-url      默认 https://api.openai.com/v1
--llm-model         默认 gpt-4o-mini
--llm-batch-size    25
--deepxiv-llm-review-max-candidates 20
--notes-dir         notes
--logs-dir          logs
```

### 说明

- 运行开始时，脚本会打印最终参数
- 密钥不会明文打印
- 去重后会先做规则标题初筛，并写出 `YYYY-MM.title-triage.json`
- `--llm-review True` 时，只复核“标题没有明显证据”的论文
- `--source deepxiv --llm-review True` 时，会先按 DeepXiv score 对
  `no-clear-title-evidence` 候选降序排序，只把前
  `--deepxiv-llm-review-max-candidates` 篇交给 LLM；其余候选仍保留在
  `title-triage.json`，并标记为 `review.status=skipped`
- 最终月度 note 只收录规则直判相关论文，以及被 LLM 复核确认相关的论文
- `fetch_high_velocity_lit.py` 不再调用 `DeepXiv brief`
- 默认候选检索走 `DeepXiv`；DeepXiv 出现额度耗尽、token/API 错误或其它检索异常时，本次运行后续检索自动 fallback 到 `arXiv API`
- arXiv 候选检索会把多个 `--categories` 合并为 OR 条件推入查询，例如
  `(cat:astro-ph.GA OR cat:astro-ph.SR OR cat:astro-ph.IM)`；DeepXiv 候选检索则按分类分别查询后去重合并

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

## 5. 审阅论文结构化数据资产

对已经拉取到 `literature/<arxiv_id>/` 的论文，先生成标准审阅模板：

```bash
conda run -n stella-env python scripts/init_catalog_review.py \
  --arxiv-id 2402.10714
```

`init_catalog_review.py` 会调用候选清单逻辑，按 Pydantic schema 生成固定字段的
`catalog_review.json` skeleton。然后使用项目内 `hvs-catalog-review` skill 结合全文
审阅候选表格和资源，只填语义空位：

```text
literature/<arxiv_id>/catalog_review.json
```

本阶段梳理论文已有结构化数据资产，不判断是否是高速星 catalog。输出只分为
`internal_tables` 和 `external_resources`；内部表格需要记录全文语境下的作用和 `columns[]`
列含义，外部资源只逐项记录论文中的整体描述、链接、路径、证据和备注，不分析远程资源内部结构，也不下载远程资源。

审阅完成后运行严格结构和 source ref 校验：

```bash
conda run -n stella-env python scripts/validate_catalog_review.py \
  --arxiv-id 2402.10714 \
  --require-complete
```

重建全局 catalog 工作流索引：

```bash
conda run -n stella-env python scripts/build_catalog_index.py
```

输出：

```text
literature/literature_catalog_index.json
literature/literature_catalog_index.md
```

索引以 `literature/*/catalog_review.json` 为入口；如果同目录存在
`catalog_extraction.json`，会同时汇总当前内部表格提取状态、ECSV 表格成功/失败数量，以及 excerpt
文件保存成功/失败数量。`literature_catalog_index.md` 中 review 状态和 extraction 状态分开显示。

Review 状态含义：

- `reviewed`：数据资产审阅已在可用论文/源码上下文中完成。
- `partial`：数据资产审阅不完整，或候选覆盖还有未决问题。
- `needs_review`：尚未完成数据资产审阅。
- `source_missing`：无法基于源码完成审阅；如果源码元数据同时显示可用，索引会用 `(!)` 标出不一致。

Extraction 状态含义：

- `success`：当前提取运行无表格或文件失败。
- `partial`：当前提取至少产出一个表格或文件，但也有失败。
- `failed`：当前提取或 manifest 读取失败。
- `not_started`：review 已发现内部表格，但尚无 `catalog_extraction.json`。
- `not_applicable`：review 未发现内部表格；即使只有外部资源，也无需提取。

## 6. 提取已审阅内部表格

推荐先安装 LaTeXML：

```bash
brew install latexml
```

提取脚本会按顺序尝试 LaTeXML、Pandoc 和项目内 fallback parser。只有
`catalog_review.json` 中的 `internal_tables` 会进入提取阶段；`external_resources` 只保留在 review 中。

给单篇论文提取所有已审阅的内部表格：

```bash
conda run -n stella-env python scripts/extract_catalog_tables.py \
  --arxiv-id 2402.10714
```

只提取一个候选表格：

```bash
conda run -n stella-env python scripts/extract_catalog_tables.py \
  --arxiv-id 2402.10714 \
  --internal-table-id table-tab-72dr3
```

提取所有已审阅且有 internal table 的论文：

```bash
conda run -n stella-env python scripts/extract_catalog_tables.py \
  --all-reviewed
```

### 常用参数

```text
--arxiv-id ID              提取单篇论文
--all-reviewed             提取所有 reviewed 且有 internal table 的论文
--internal-table-id ID     只提取单个 internal_tables[].id，需配合 --arxiv-id
--jobs Auto|N              --all-reviewed 的并行论文 worker 数，默认 1
--literature-dir PATH      文献归档根目录，默认 literature
--dry-run True|False       只解析并报告，不写文件，默认 False
--overwrite True|False     覆盖已有 excerpt.tex 和 ECSV，默认 False
```

### 说明

- LaTeX 表格会写出 `catalog_sources/<internal_table_id>/excerpt.tex`、转换器 HTML/log artifacts 和 `catalog_tables/<internal_table_id>.ecsv`。
- LaTeX 解析失败也会保留 `excerpt.tex`，便于复查失败上下文。
- 外部资源不会在 extraction 阶段解析、下载、定位、转换或写入下载件；如需参考，只看 `catalog_review.json` 中的资源描述和证据。
- 清理旧 catalog 工作流产物可运行：

```bash
conda run -n stella-env python scripts/cleanup_catalog_workflow_outputs.py --dry-run True
```

- 全量重跑可以用 `--jobs Auto` 按论文并行；Auto 会按论文数选择 1/2/4/8/12 个 worker。也可以直接指定 `--jobs N`。
- 每篇论文会写出 `catalog_extraction.json`，记录单个当前 `run`、excerpt 文件、转换尝试结果、成功失败、ECSV 路径和观测到的列头/单位；转换器 stdout/stderr 内容只保存在 artifact 文件中，JSON 里只保留路径。
- ECSV 使用 `col_001`、`col_002` 这类稳定列名，尽量忠实保留论文表格，不表示已经完成统一对象 schema。
- `catalog_extraction.json` 写出前会按 Pydantic schema 校验；也可以单独运行：

```bash
conda run -n stella-env python scripts/validate_catalog_extraction.py \
  --arxiv-id 2402.10714 \
  --require-reviewed
```

## 7. 抽取论文级 HVS candidates

完成 `catalog_review.json` 和 `catalog_extraction.json` 后，使用项目内
`hvs-candidates-extraction` skill。先生成固定字段模板：

```bash
conda run -n stella-env python scripts/init_hvs_candidates.py \
  --arxiv-id 2402.10714
```

然后结合论文原文、review/extraction 事实源和 ECSV 填写：

```text
literature/<arxiv_id>/literature_hvs_candidates.json
```

本阶段只抽取单篇论文内、被正文证据锚定为可能从银河系/Galactic potential
非束缚或逃逸的 HVS/unbound/escaping/hyper-runaway candidates。普通 runaway、
星团逃逸、本地 GC 非束缚但文章说明整体仍受银河系束缚的对象、以及文章已判定 bound
的对象不进入 `candidates[]`。固定速度阈值只能用于检查，不作为唯一纳入依据。

抽取顺序必须是正文驱动：先读论文正文确定 candidate 身份、银河系非束缚证据和
`candidate_origin`，再用 `catalog_review.json`、`catalog_extraction.json` 和
`catalog_tables/*.ecsv` 定位具体数值。review/extraction JSON 只是表格地图，不能作为纳入依据。

完成后运行校验：

```bash
conda run -n stella-env python scripts/validate_hvs_candidates.py \
  --arxiv-id 2402.10714 \
  --require-complete
```

也可以直接校验一个指定文件：

```bash
conda run -n stella-env python scripts/validate_hvs_candidates.py \
  --path literature/2402.10714/literature_hvs_candidates.json \
  --require-complete
```

校验通过后自动重建全局索引：

```bash
conda run -n stella-env python scripts/validate_hvs_candidates.py \
  --arxiv-id 2402.10714 \
  --require-complete \
  --rebuild-index
```

单独重建全局索引（不需要先校验）：

```bash
conda run -n stella-env python scripts/build_hvs_candidates_index.py
```

### 说明

- `literature_hvs_candidates.json` 使用 `schema_version: stella.literature_hvs_candidates.v4`。
- 模板、validator 和 skill schema 参考文档来自同一套 Pydantic models；不要手工新增模板之外的字段。
- 每篇论文都应有结果文件；没有符合边界的候选时，写 `extraction.status=no_candidates` 和空 `candidates[]`。
- `method_chain[]` 是论文级原子方法 DAG，ID 使用 `step-01`、`step-02` 等本文内局部顺序号，`step_type` 使用受控词表，`depends_on[]` 只列直接上游 step。
- `core` 和 `extra[]` 的每个参数记录用字段级 `method_refs` 引用恰好一个直接生成该值的 `method_chain` step；完整 lineage 由该 step 递归展开 `depends_on[]` 得到，候选层级不再使用 `method_chain_refs`。
- `candidate_origin.origin_type` 区分 `introduced_by_this_paper` 和 `cited_from_literature`。
  “首次给出”指本文首次把对象作为可能 Galactic-unbound/HVS candidate 提出；已知对象即使本文重新分析，也标为 `cited_from_literature`，并用 `paper_reassesses_unbound_status=true` 表示本文重新评估。
  cited candidates 必须在 `candidate_origin.citation.source_refs` 中同时给出正文 cite 行和 `.bib`/`.bbl` 条目。
- `core.observed_phase_space` 标准槽位是 RA、Dec、距离/视差、pmRA、pmDec、RV；论文给出的 Galactocentric 坐标、速度、逃逸速度比较和束缚/非束缚概率放在 derived/probabilities。
- `extra[]` 保存光度、恒星参数、质量标志、邻近源检查、轨道或论文特有指标等非核心信息。
- `core` 和 `extra[]` 的每个参数记录都必须同时有 `raw_value`、清洗后的 `value`、`source_refs` 和 `method_refs`。
  ECSV 来源需要 `path`、`line`、`column`、`column_header`、`raw_value`，且参数级 `raw_value`、source ref `raw_value` 和真实 ECSV cell 必须一致。
  `value`、`error`、`lower_error`、`upper_error` 不能保留 LaTeX 命令、花括号、`$`、`_`、`^` 或 `+/-`；机械误差表达应拆到 error 字段。
  原文来源需要 `path`、`start_line`、`end_line`。
- 校验脚本只检查 JSON 结构和 provenance 是否自洽，不替代 Agent 判断对象是否应纳入。
- direct-producer `method_refs` 的固定规则：位置/视差/自行/星表光度直接引用 `input_catalog` 或 `astrometric_calibration`；RV 引用 `radial_velocity_measurement` 或直接星表 `input_catalog`；距离引用 `distance_estimation`；速度和 Galactocentric 坐标引用 `velocity_calculation`；逃逸速度、束缚概率和 escape margin 引用 `escape_or_bound_assessment`；轨道量引用 `orbit_integration`；起源量引用 `origin_assessment`；恒星参数引用 `stellar_parameter_inference` 或 `photometric_or_sed_modeling`；只报告无方法的值引用 `reported_value_adoption`。

旧版本 `literature_hvs_candidates.json` 不再作为长期兼容目标；需要补录或重做时，按当前 v4 schema 和 `hvs-candidates-extraction` skill 重新审阅生成。
- 修改 schema 字段时，先改 Pydantic models，再运行：

```bash
conda run -n stella-env python scripts/generate_schema_docs.py
```
- 全局索引文件为 `literature/literature_hvs_index.json` 和 `literature/literature_hvs_index.md`，
  由 `scripts/build_hvs_candidates_index.py` 自动扫描所有 `literature/<arxiv_id>/literature_hvs_candidates.json` 生成。
  不要手动修改索引文件；如果输出有问题，应修改 candidates JSON 或索引渲染逻辑，然后重新生成。

## 8. 时间写法

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

## 9. 额外说明

当 DeepXiv 返回限额错误时：

- 已完成的月份仍会保存
- 脚本会写出 `logs/partial_<run_id>.json`
- 同时把结果追加到 `logs/runs.jsonl`
- 然后打印恢复命令并退出

默认搜索词：

```text
hypervelocity stars
high-velocity stars
high radial velocity stars
runaway stars
unbound stars
escaping stars
```
