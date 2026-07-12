# Stella Benchmark — 当前计划与设计边界

本文件回答四个问题：benchmark 要验证什么、三种方法如何比较、现在推进到哪里、
哪些边界不能在执行中悄悄改变。可执行命令、输入、输出和 validator 由
[`workflows/stella_workflows.yaml`](../workflows/stella_workflows.yaml) 及其
`benchmark_*` workflow definitions 管理；版本和实时数量以 registry、campaign
manifest 与 gold manifest 为准。本文件不重复充当命令手册或手工状态数据库。

## 研究目标与比较方法

`hvs-extraction-v2` 是当前正式 campaign。它以专家、PDF-only gold 检验 AI 能否从
HVS 文献中完整发现候选星并准确转录论文报告的关键数值，为论文中的方法比较提供
可复现证据。

- **方法 A：通用 coding agent。** Agent 在 Stella skill 与隔离 harness 的约束下
  完成单篇提取；记录模型、harness 版本、代码和产物哈希，使其成为可复现实验条件。
- **方法 B：直接 API 两段式管线。** 确定性 scheduler 先生成论文级 scaffold，再
  按候选生成记录并通过 validator/定向修复；它是结构化直接调用的基线。
- **方法 C：Stella 轻量 agentic 管线。** 自研工具驱动 ReAct extractor 逐候选工作，
  再由不同模型的独立 reviewer 审核；它承载 Stella 的 agent 方法主张。

评分保持分层，不制造单一总分：

- **L1 候选发现**：候选集合的 precision、recall 与 F1。
- **L2 数值转录**：匹配候选上的严格一致率，以及包含 L1 漏检影响的端到端交付率。
- **并列头条指标**：L1 micro F1、`agreement_over_compared_strict`、
  `delivery_end_to_end_strict`。端到端交付率已经包含 L1 recall，再与 L1 合成会重复
  惩罚漏检。
- **L3 证据溯源**：不属于当前正式评分范围；只有形成独立设计、专家审核口径和新
  campaign/contract 后才实施。

详细 L2 口径见 [`benchmark-l2-spec.md`](benchmark-l2-spec.md)，长期有效的方法选择与
边界见 [`ADR 0003`](adr/0003-benchmark-methodology-and-boundaries.md)。

## 冻结的实验合同

- **样本**：50 篇版本一致论文；固定 10 dev / 40 test。dev 依据采样前
  `legacy_status` 代理和 `table_complexity` 平衡，不能按 gold 或模型结果换论文。
- **迭代边界**：dev 可用于发现问题和迭代；test 默认锁定。查看 test 后若改变方法、
  prompt、schema 或 validator，必须进入新的实验版本和新的 held-out 设计，不能继续
  把同一 test 当作未见数据。
- **release gate**：test run 只有在 sealed、leakage audit clean 且存在匹配的持久
  release manifest 时才可评分或构建报告。
- **评分合同**：正式 scorecard 使用 `benchmark.scorecard` version 3。dev 报未加权
  主指标；test 另报面向排除 dev 后 197-paper evaluation frame 的 post-stratified
  sensitivity。
- **身份与版本**：campaign manifest 的 SHA256 锚定 evaluation contract；每次 run
  另行记录实际代码与 method fingerprint。artifact schema 版本只来自
  [`schema_registry.py`](../src/stella/schema_registry.py)。

## 当前状态（2026-07-12）

- ✅ `hvs-extraction-v2` 的 sampling/campaign manifests 已冻结为 50 篇、10 dev、
  40 test；可确定性重建。
- ✅ formal run contract、retry/archive、leak audit、seal、test release、Method A
  isolation harness、Method C reviewer/provenance、scorecard version 3 和 report
  cohort gate 已实现。
- ✅ public `gold_manifest.json` 当前记录 12/50 篇完整 YAML/JSON twins：dev 8/10、
  test 4/40；公共仓只保存文件名级元数据与哈希，不保存 gold 内容。
- ⌛ dev 仍缺 `2304.11269` 与 `2507.07558`。完成 PDF-only 专家标注并刷新 manifest
  之前，不得把部分 dev gold 结果称为 formal dev score。
- ⌛ v2 尚无 formal run、release 或 scorecard。下一执行里程碑是完成 10/10 dev gold，
  然后以冻结方法创建、审计、seal 并评分三种方法的 dev runs。
- ⌛ test gold 可与 dev runs 的机械执行并行继续标注，但 test extraction 结果保持锁定，
  直到用户显式授权 release。

实时进度必须从
[`manifest/`](../benchmark/campaigns/hvs-extraction-v2/manifest/) 重新计算；上面的日期化
快照用于说明当前里程碑，不替代机器合同。

## 当前推进顺序

1. 专家完成两篇缺失 dev gold；Agent 只处理 PDF-only 誊抄、校验和 manifest 刷新等
   机械工作。
2. 为方法 A/B/C 分别建立独立 dev run，固定 model、prompt/harness、代码和 method
   fingerprint；不得跨 run 读取 gold、scorecard、报告或历史 run 输出。
3. 对每个 run 只做 fingerprint 不变的 infrastructure retry，随后生成 leakage audit
   并 seal；成功论文不可覆盖。
4. 在显式获准读取 private gold 后评分 dev，并并列解释 L1、配对 L2 与端到端 L2；
   failure mode 分析进入 private details，不把 raw gold 带回公共仓。
5. 继续完成剩余 test gold。只有在方法冻结、test run clean/sealed 且用户明确授权时，
   才创建 test release、正式评分和论文报告。

具体执行必须从 workflow index 路由到
`benchmark_gold_annotation_form`、`benchmark_extraction_run`、
`benchmark_run_finalize` 或 `benchmark_score_report`，不能把本节当作可复制命令。

## 运行与数据红线

- gold 只由 PDF-only、expert-led annotation workflow 写入外部私有仓；提取 run 永不
  读取 gold。scribe session 单篇、单次使用，不能复用于 extraction/scoring/toolchain。
- 正式 run 只能由 campaign + split 创建。方法、model、prompt、harness、reviewer 或
  code 改变时使用新 run ID；改变 evaluation contract 时创建新 campaign。
- seal 前仅允许相同 fingerprint 的 infrastructure retry；污染 run 只能留作诊断，
  不得 release 或正式评分。
- public repo 只提交 hash-only manifest、release 和 scorecard。gold、run archive、
  private scoring details 与 report HTML 永不提交。
- `method_chain` 保持 schema-validated 的诊断/产品信息，但不进入当前专家 benchmark
  的 L1/L2 评分。
- benchmark 期间不借机重构 catalog 网页、`hvs_dynamics_calculate` 科学逻辑或整个
  literature schema；需要改变 extraction surface 的工作必须脱离当前冻结 campaign。

## 暂缓事项与触发条件

- **L3 evidence scoring**：等独立 rubric 明确定位符容差、抽查/全查策略、gold 成本和
  scorer 合法输入后，再开新合同；不补入当前 L1/L2 scorecard。
- **全量语料重提取**：等 benchmark 选出并冻结可接受的方法后，再决定是否重跑完整
  literature corpus；benchmark 本身不授权批量覆盖现有数据。
- **深层 schema 形状调整**：多值/多估计等改造属于新 artifact schema 与迁移工作，
  需按 [`versioning-policy.md`](versioning-policy.md) 另行设计，不能混入正式 run。
- **validator warning 升级为 error**：只有经过足够真实论文验证、证明不会造成系统性
  误伤后再升级，并为行为变化补回归测试。

## 决策与历史入口

- [`ADR 0001`](adr/0001-hvs-extraction-v1-campaign.md)：v1 campaign 的原始冻结决定，
  现为只读历史。
- [`ADR 0002`](adr/0002-two-layer-version-model.md)：当前双层版本模型与 v2 campaign
  迁移。
- [`ADR 0003`](adr/0003-benchmark-methodology-and-boundaries.md)：三种方法、分层评分、
  gold 隔离、实验纪律与非目标。
- [`schema-v0.2-notes.md`](schema-v0.2-notes.md)：已落地 schema 变更和仍延期的形状问题。
- Git 历史中的 `hvs-extraction-v1`、gold8、47/8/39、scorecard version 2 与旧 run
  layout 仅用于追溯开发过程，不是当前执行合同。
