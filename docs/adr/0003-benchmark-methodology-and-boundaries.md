# ADR 0003: Benchmark methodology and operating boundaries

状态：已接受，适用于 `hvs-extraction-v2`

## 决策

1. 比较三种可复现范式：方法 A 是 skill + 隔离 harness 约束的通用 coding agent；
   方法 B 是直接 API 两段式 extractor + 独立 reviewer；方法 C 是 Stella 的工具驱动
   ReAct extractor + 同一独立 reviewer。B/C 默认共享 reviewer model、规则、只读工具、
   challenge 格式和一次修订政策，使两者的主要差异保持为 direct batch 与 agentic 编排。
   no-reviewer 只作为后续 removal ablation，不替代默认方法。正式 run 必须记录对应
   model、prompt、harness、reviewer、代码和 method fingerprint。
2. 并列报告 L1 micro F1、匹配候选严格 L2 一致率和端到端严格交付率，不合成总分；
   端到端指标已经包含 L1 漏检影响。
3. Gold 由专家基于 PDF 完成科学判断，保存在 `STELLA_GOLD_DIR` 指向的外部私有仓。
   单篇 scribe session 只做同一 PDF 的机械誊抄，之后不得复用于 extraction、scoring、
   report 或 toolchain 开发。
4. 当前正式范围只有 L1/L2。`method_chain` 保留为产品和诊断信息但不参与评分；L3
   evidence scoring 必须形成独立 rubric 和新合同，不能临时加入当前 scorecard。
5. Dev 可以迭代；test 只有在 clean leakage audit、seal 和显式 release 后才能评分。
   查看 test 后再改变方法，必须使用新的实验版本和 held-out 设计。
6. 当前 campaign 不授权全量语料重提取、catalog 网页改造、dynamics 科学逻辑修改或
   深层 schema 重构；这些工作需要独立目标、迁移与验证方案。

## 后果

- workflow YAML 负责执行合同，campaign/gold manifests 负责样本与进度，本 ADR 只
  保存跨 workflow 的方法学决定。
- 方法条件变化使用新 run；样本、split、评分口径或 extraction surface 变化使用新
  campaign。
- v1、gold8 和旧 run layout 只用于历史追溯，不得混入 v2 formal cohort。
