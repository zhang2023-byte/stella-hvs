# ADR 0006: Method-specific end-to-end reviewer orchestration

状态：已接受，适用于 `hvs-extraction-v2` 的后续新 run

## 背景

首轮 dev 运行让 Methods B/C 复用了同一个 read-tool reviewer agent。三次 reviewer
恰好耗尽 48 calls 仍未调用 `submit_review`：它们持续搜索和读取，却没有明确的停止、
强制提交或正式失败原因。这也让纯工作流 Method B 在末端混入了 agentic 机制，与
方法定义不一致。

## 决策

1. Method B 全程保持纯工作流。Reviewer 接收完整 packed paper context 和已通过
   validator 的 extraction，不获得任何 tool schema；一次完整响应后只允许最多两次
   结构化 JSON 纠正。Transport 失败是 `transport_error`，纠正耗尽但仍无合法 review
   是带明确原因的 `review_failed`。
2. Method C 保留 read-only reviewer agent，但总预算从 48 收紧为 32 calls，并为最后
   2 calls 保留 finalization。连续重复同一非提交工具批次、`finish_reason=length` 或
   research budget 用尽时，停止执行读取工具，强制选择 `submit_review`；保留调用耗尽
   后仍未提交的具体 stop reason。
3. 两种方法仅在 pre-review validator 和 CJK gate 都通过后运行 reviewer。上游结果
   仍无效时直接保留 `validator_errors`，不把 reviewer 当作第二套 validator repair。
4. B/C 继续共享 reviewer model、`hvs_reviewer` 科学规则、review JSON schema、high
   severity 政策和一次 extractor revision。这些是受控共同因素，不代表共享编排。
5. Method fingerprint 必须记录 `reviewer_orchestration` 及对应 retry/budget/stop policy。
   本变更之后必须创建新 run ID；已有 run 只读保留，不得用 retry 混入新实现。

## 后果

- Method B 与 Method C 现在比较端到端工作流范式与端到端 agentic 范式；结果不能再
  解释成只由 extractor 编排造成的差异。
- B 的请求可能较大，但调用数和失败面更确定；C 仍可按需探索，但不会无限读取到预算
  耗尽而没有结论。
- `review.json` 只在合法 review 完成后生成；失败原因进入 per-paper `report.json` 和
  stage log，工作台无需读取额外 trace 才能解释 reviewer 失败。
