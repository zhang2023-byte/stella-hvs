# Benchmark 外部故障重试实施计划

1. 在 Run contract 中新增精确的外部故障资格判定和指定论文归档队列，并先用失败测试锁定封存、成功与工作流错误边界。
2. 给 Method B/C runner 增加只接受正式既有 Run 的 `--retry-external-paper`，确保不可变 Run config 仍覆盖完整 split，而执行队列只包含指定论文。
3. 扩展开发工作台摘要、资格预检、启动控制和 HTTP 路由；单篇与批量请求都要求精确确认值并在启动前二次验证。
4. 扩展前端类型、API、历史 Run 与实验组 Run 页面；只为合格外部故障展示操作，封存与工作流错误显示明确只读/新开实验提示。
5. 更新 `benchmark_dev_console` workflow contract，运行目标测试、Python 全量测试、前端测试和生产构建，并检查生成 bundle。

实施在当前尚未提交的工作树上连续完成，以保留前一轮工作台优化；本任务不创建提交，也不触发真实重试。
