# ADR 0001: `hvs-extraction-v1` campaign contract

状态：已被 [ADR 0002](0002-two-layer-version-model.md) 取代；作为历史决策保留（2026-07-10）

## 决策

1. 正式 campaign 固定为 50 篇：保留原 47 篇，并以确定性补样加入 3 篇；
   `benchmark/campaigns/hvs-extraction-v1/manifest/campaign_manifest.json` 是 split 与权重的唯一机器可读
   合同。
2. 10 篇 dev 是按采样前 `legacy_status` 代理和 `table_complexity` 平衡的固定
   集合。已曝光论文永久属于 dev；不以 gold 真值、模型结果或调参效果重新划分。
   其余 40 篇是精确 test 补集。
3. test 默认锁定。只有 clean、sealed test run 才能获得可提交的持久 release
   manifest；没有匹配 release 不得 formal score 或生成 test report。
4. 正式评分只接受 sealed run、campaign/split/gold snapshot 绑定的 scorecard
   v0.3。非法、`review_failed`、缺失或无法解析的交付在主 L1/L2 一律视为未交付；
   可解析非法输出至多进入私有 diagnostic-only 记录。
5. 当前范围只包括 L1/L2；不设计或实现 L3。`benchmark-freeze-v2` 继续锚定
   extraction surface，不随这次基础设施变更移动。

## 后果

- dev 可用于观察和迭代，但 test 结果一旦 release 后不得用于同版本方法调参。
- 正式 dev 评分要等 10 篇 dev JSON gold twins 都完成并刷新 public gold
  manifest；当前缺口不得用部分 gold 伪装成正式结果。
- 历史 run layout 与 scorecard v0.2 保持只读历史记录，不迁移、不重算，也不得
  混入 `hvs-extraction-v1` cohort。
