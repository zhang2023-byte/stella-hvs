# Stella Benchmark — 当前计划与执行边界

本文件只维护当前研究目标、已完成结果和下一步顺序。可执行命令、输入、输出与
validator 以 [`workflows/stella_workflows.yaml`](../workflows/stella_workflows.yaml)
及其 definitions 为准；版本与 lifecycle 以
[`schema_registry.py`](../src/stella/schema_registry.py) 为准；实时 run 状态必须从
campaign manifests、`report.json` 和 seal records 重新计算。

## 当前结论

`hvs-extraction-v4` 是唯一可写 campaign；V1/V2/V3 只读。V4 机械继承 V3 的 50 篇
顺序和固定 10 dev / 40 test，不重新抽样。`$STELLA_GOLD_DIR` 是唯一 canonical private gold；
campaign 只拥有由独立 gold-only 任务生成的 hash-only integrity manifest，不复制私有 gold。

截至 2026-07-18，正式直接提取路线为 **Method B + `core_prov`**：

- Method B/Core 是新 dev、regression 和未来获准 test run 的唯一直接主路径。
- Method C 与 FULL enrichment 是 legacy。代码、合同和历史产物保持可读，但 dev
  console 不再创建、恢复或重试它们；直接 CLI 只有在显式 legacy opt-in 后才允许。
- Method A 地位不变，待统一 adapter 的独立执行计划；它不受 B/C legacy policy
  代替或暗中转义。
- 这一选择是基于现有 dev 证据、成本和可调试性的工程优先级，不是“C 已被科学证明
  更差”。重新启动正式 C 需要新的 ADR 和明确授权。

现行取舍见
[`ADR 0009`](adr/0009-b-core-primary-method-c-and-full-legacy.md)。

## 冻结的实验合同

- **样本**：50 篇、固定 10 dev / 40 test；不能依据 gold 或模型输出替换论文。
- **迭代边界**：dev 可用于调试和方法冻结；test 保持锁定。查看 test 后若改变方法、
  prompt、schema 或 validator，必须进入新的实验版本和 held-out 设计。
- **任务面**：V4 新 Method B 正式 run 只使用 `core_prov`。run manifest v3 分开记录
  CORE 与 enrichment delivery；legacy FULL 不得使有效 CORE 降级。
- **评分**：scorecard v4 并列报告 L1 micro F1、
  `agreement_over_compared_strict` 和 `delivery_end_to_end_strict`，不合成一个总分。
- **release gate**：test run 只有 clean、sealed、leakage audit clean 且存在匹配的
  release manifest 时才可评分或构建报告。
- **gold 边界**：提取过程不读取 gold、scorecard、报告或历史 run 输出；gold 只由
  PDF-only、expert-led annotation workflow 写入外部私有仓。

详细评分口径见 [`benchmark-l2-spec.md`](benchmark-l2-spec.md)，完整反污染协议见
[`benchmark/GUIDELINE.md`](../benchmark/GUIDELINE.md)。

## 已完成的 V3 历史 dev 结果

下表是当前仓库中的正式公开 scorecard，不把未 seal/未评分的 attempts 当成结果：

| 实验标签 | 交付 | L1 P / R / F1 | L2 compared agreement | L2 end-to-end |
|---|---:|---:|---:|---:|
| `v3-dev-baseline-b-core-r1` | 8/10 | 0.889 / 0.444 / 0.593 | 0.987 | 0.556 |
| `v3-dev-baseline-c-core-r1` | 6/10 | 0.171 / 0.333 / 0.226 | 0.982 | 0.406 |
| `v3-dev-hardened-b-core-r1` | 7/10 | 1.000 / 0.167 / 0.286 | 1.000 | 0.248 |

解释边界：

- 前两行是 **V3 pre-architecture baseline**；第三行是
  **V3 post-architecture hardened-B validation**。
- hardened-B 相比 baseline-B recall 和端到端交付明显回退，当前不能据此接受新
  roster-review architecture。
- hardened-B 的 roster reviewers 全部返回 accepted、没有 challenge；“reviewer
  过度收紧 roster”目前没有运行证据支持。根因仍需按 paper/stage 分解。
- `v3-dev-hardened-c-core-r1` 保留 6 篇 `report.json`，但未完成、未 seal、未评分；它是
  legacy diagnostic，不纳入结果表，也不计划继续补跑。

所有数值来自对应的公开 scorecard；失败原因和单篇细节仍以本地 run archive 的
`report.json` 为准。scorecard 只含 counts/rates，不承载 private gold 明细。

## 当前工程基线

- run-manifest v3、scorecard v4、append-only public gold manifest、component-hash
  seal gate 与 CORE/enrichment delivery envelopes 已实现。
- roster-bundle v2 在 seal 前允许一次独立 membership review；shared-roster cache key
  包含 extractor/reviewer 的 model、provider、prompt/rule、context 与 code identity。
- 新 UI 与正常 workflow 只创建 B/Core；历史 C/Full 仍可浏览，但为 read-only。
- C 与 Full 的实现没有删除或搬迁历史产物；legacy 是受控兼容层，不是破坏式清理。
- 当前 0.5.1 边界、兼容行为和迁移说明见
  [`releases/0.5.1.md`](releases/0.5.1.md)。

## 接下来怎么做

严格按以下顺序推进，前一步没有证据闭环时不提前进入 test：

1. **已完成：建立 V4 public campaign。** V4 复用 V3 固定 sample/split；V3 转为只读，
   且 public setup 不创建 V4 gold manifest。
2. **运行并 seal V4 pre-engineering B/Core baseline。** 使用 clean V4 commit、独立空
   roster cache、`deepseek-v4-pro` extractor、`glm-5.2` reviewer 和 `parallel=1`；不评分。
3. **独立 gold-only scoring。** 由隔离任务从唯一 private gold 生成 V4 hash index，
   核验 seal 后评分；本 no-gold extraction 上下文不进入该阶段。
4. **再做最小 B/Core 工程修复。** 修复必须是通用架构或规则改动，先跑合成测试和历史难例；
   禁止 paper ID、object name、表格专用阈值或 ad-hoc regex。
5. **做 isolated cold-cache repeat。** 使用新的 run ID 和独立空 roster cache，报告逐篇
   roster-set agreement；cache hit 不能充当 repeatability 证据。
6. **预注册并冻结 B/Core。** 只有 dev 达到既定 delivery/FP/数量一致性门槛，才冻结
   model、provider、prompt、rules、预算和 code revision。
7. **等待显式 test release。** test gold 完成且用户授权后，再运行一次 sealed B/Core
   test、leak audit、release、score 和论文报告。

## 运行与数据红线

- 正式 run 只能由 campaign + split 创建。method、model、prompt、rules、reviewer、
  task surface 或 code 改变时必须使用新 run ID。
- seal 前仅允许同一 fingerprint 的 infrastructure retry；成功论文不可覆盖，sealed run
  不可修改。
- public repo 只提交 hash-only manifest、release 和 scorecard。gold、run archive、
  private details 与 report HTML 永不提交。
- C/Full 历史 run 不删除、不重写、不补 seal；需要复现时必须显式 legacy opt-in，并使用
  新 run ID。
- benchmark 调试不顺手重构 catalog UI、动力学科学逻辑或 literature schema。
- L3 evidence scoring、全量语料重提取、深层 schema 调整和 validator warning 升级均为
  独立后续决策，不混入当前 B/Core 调试。

## 历史入口

- [`ADR 0003`](adr/0003-benchmark-methodology-and-boundaries.md)：方法与分层评分边界。
- [`ADR 0006`](adr/0006-end-to-end-reviewer-orchestration.md)：B/C reviewer 编排历史。
- [`ADR 0008`](adr/0008-core-first-delivery-envelopes.md)：CORE-first delivery envelopes。
- [`ADR 0009`](adr/0009-b-core-primary-method-c-and-full-legacy.md)：当前 B/Core 主路径与
  C/Full legacy 决定。
- [`2026-07-16 hardening plan`](plans/2026-07-16-benchmark-bc-evaluation-hardening.md)：
  已实施基础设施与仍待执行的 Task 6/7；其中旧 B/C 对称目标由 ADR 0009 收口。
