# Stella Benchmark — 当前计划

## 目标

`hvs-extraction-v2` 是 HVS 候选提取的当前正式 benchmark campaign：以专家、PDF-only
gold 评估三种 AI extraction 方法的 L1 候选发现和 L2 数值转录。L1 F1、严格配对
一致率与端到端交付率并列报告，不合成为单一总分。

## 冻结合同

- 采样：原 47 篇加 3 篇确定性、版本一致的补样，共 50 篇。
- split：固定 10 dev / 40 test；dev 依据采样前 `legacy_status` 代理与
  `table_complexity` 平衡，绝不根据 gold 真值或模型表现换论文。
- test：默认锁定；必须是 sealed 且 leakage audit clean 的 test run，另有匹配的
  持久 release manifest，才可评分或构建报告。
- 评分：正式 scorecard 使用 `benchmark.scorecard` version 3。dev 只报未加权主指标；test 另报面向排除 dev 后
  197-paper evaluation frame 的 post-stratified sensitivity。
- 科学范围：本轮只实施 L1/L2，不实现 L3。campaign manifest 的 SHA256 锚定
  evaluation contract；每次 run 另行记录实际代码与 method fingerprint。

## 当前状态

- ✅ `benchmark.sampling_manifest` version 2 与 `hvs-extraction-v2` campaign manifest 已生成。
- ✅ formal run contract、retry/archive、leak audit、seal manifest、Method C
  provenance/reviewer 修复、Method A isolation harness、test release、scorecard
  `benchmark.scorecard` version 3 与 report cohort gate 已实现。
- ⌛ 专家需要以既有 PDF-only workflow 完成 dev 的 `2304.11269` 与
  `2507.07558` gold，并刷新 `gold_manifest.json`。在此之前不得进行 formal dev
  scoring。
- ⌛ 完成 dev gold 后，按被冻结的方法执行 sealed dev runs；test 仍不评分、不打开
  结果，直到显式 release。

## 运行纪律

1. 正式 run 只能通过 campaign manifest + `--split dev|test` 创建；方法或
   prompt/model/code 改变必须使用新的 run ID。
2. seal 前只允许相同 fingerprint 的 infrastructure retry；成功论文不可覆盖。
3. seal 时审计报告、每篇交付状态和 artifact SHA256 固化；污染 run 仅可保留诊断，
   不可 release 或正式评分。
4. scorecard 只加载所选 split 的 private JSON gold twins，并逐项核对 public
   `gold_manifest.json`。非法/缺失交付在主指标中均视为未交付。
5. public scorecard/release manifest 可以提交；gold、run archive、private details
   和 report HTML 永不提交。

`hvs-extraction-v1`、历史 gold8、47/8/39 划分、scorecard version 2 与旧 run
layout 是只读开发历史，不属于当前 campaign。原始冻结决策见
[`ADR 0001`](adr/0001-hvs-extraction-v1-campaign.md)，当前双层版本与 campaign
迁移决策见 [`ADR 0002`](adr/0002-two-layer-version-model.md)。
