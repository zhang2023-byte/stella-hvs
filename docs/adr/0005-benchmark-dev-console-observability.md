# ADR 0005: Benchmark 开发控制台与精确运行追踪

状态：已接受（2026-07-14）

## 背景

Method B/C 的正式 dev run 原本主要通过 CLI、每篇 `report.json` 和 request/response
attempt 文件调试。它们可以复盘结果，却不能把并发 paper、LLM 调用、工具执行、
validator、reviewer 与 token/耗时放在同一条实时事件流中，也缺少一个受合同约束的
可视化启动入口。

## 决策

1. 增加仅绑定 loopback 的 `benchmark_dev_console`。它是
   `benchmark_extraction_run` 上方的控制与可观测层，不实现新的 extraction path。
   GUI 只生成并启动维护中的 Method B/C runner，固定 active campaign 与完整 dev split。
2. 新 run 可选写入 append-only `events.jsonl`。大 payload 以 canonical JSON、gzip 和
   SHA-256 content address 保存，event 只引用 blob；trace 根目录不进入 method
   fingerprint，因此不改变 scientific method identity。
3. 追踪真实发送给 transport 的无凭据 request、provider 原始 response、provider 明示
   的 reasoning 字段、tool call/result、validation/review/final 状态和 usage。系统不推断、
   重建或宣称访问隐藏 chain-of-thought。
4. 历史 run 统一出现在 console 中。带新 trace 的 run 标为 `exact`；旧 run 只从已有
   attempts/report 生成 `legacy_synthesized` 时间线，保持只读且不伪装成精确事件。
5. START RUN 前执行正式 preflight，包括对每篇 dev paper 实际构建 deterministic context
   pack，以验证声明的 ECSV、TeX source 和上下文大小。mutation API 需要进程级 session
   token、JSON content type 与精确 loopback Origin；所有请求还会校验当前监听端口对应的
   Host，并返回 CSP、frame denial 等浏览器安全头。
6. 子进程以 `shell=false` 和独立 process group 启动，同时继承每个 run 独占的文件锁。
   `controller.json` 保存 PID/PGID；console 重启后通过锁与进程组重新判定运行状态并继续
   STOP 控制，避免同一 run 重复启动。停止采用 SIGTERM，超时后 SIGKILL。恢复仍走相同
   fingerprint，只跳过成功 paper，并归档失败或不完整 attempt。
7. LLM request trace 与 transport 共用同一个 HTTP body builder，因而只记录真正发送的
   JSON body，不把 timeout、endpoint 或 credential 等 transport 参数误标成模型输入。

## 后果与边界

- `logs/benchmark-dev-console/` 是 ignored operational evidence，不是 canonical science
  artifact；正式输出仍由 campaign run archive 拥有。
- 打开界面和查看历史不授予网络权限；用户在 GUI 中明确点击 START RUN 只授权该次
  配置对应的 LLM 调用。
- trace schema 属于 transient observability contract，不改变候选 JSON、campaign、gold、
  scorer 或公开报告版本。
- console 不读取 `STELLA_GOLD_DIR`、gold manifest 内容、score details 或 private report。
