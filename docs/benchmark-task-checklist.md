# Stella Benchmark 任务执行清单

> **数据来源**：本清单的任务条目提炼自 [benchmark-master-plan.md](benchmark-master-plan.md)，忠于其任务分解与原意。master-plan 是不随时间变的骨架与决策理由；本清单是**活的状态追踪**，取代 master-plan 顶部的状态快照。
>
> **状态图例**：✅ 已完成 · ❗️ 进行中 / 当前焦点 · ⌛️ 待执行（条件未满足或排在后续）
>
> **维护规则**：每次任务状态变更即更新本清单；**未经用户明确命令，只改状态标记、不改条目内容**（条目须忠于 master-plan 原意）。要新增/删除/改写条目或结构，必须先获用户批准。
>
> 最近更新：2026-06-13

## A 段 — 技术债清理 + schema 冻结 ✅
- ✅ A1 git 白名单备份（632 份判断 JSON 入 git + 远端）
- ✅ A2 工程基线（CI、pyproject 打包、小修缮包）
- ✅ A3 单一 `stella` 包 + 命名统一（删 44 处 sys.path hack）
- ✅ A4 版本号重置 `stella.<artifact>.v0.1`
- ✅ A5 schema 定向改进（tooling、`solar_position_and_motion` 步骤 + parameters、limit_kind / 范围字段）
- ✅ A6 数据迁移脚本（1496 份，幂等，候选计数对账不变 49/156/5、898）
- ✅ A7 批处理 driver 转正（`run_catalog_review_batch.py` + `stella.lit.llm_batch`）
- ✅ A8 清理 5 个未完成文件 — 走 plan 的"保留显式状态 + manifest 处理"分支：未手工补完，改指定为 Phase 2 管线试点 / 抽样难度层（待管线重提）
- ✅ A9 身份对齐器（三级匹配，历元归算 2″ / 兜底 5″）
- ✅ A10 schema 系统扫描（galactocentric_radius 并入 v0.1；余项记 v0.2 笔记）
- ✅ A11 冻结（tag `benchmark-freeze-v1` @ 281c8b4，本地 + 远端）

## Phase 1 — benchmark 基础设施 ✅
- ✅ 分层抽样 manifest（框 207 → 抽 47：盲标 12 / 校验 35；种子 20260611 字节级可复算）
- ✅ GUIDELINE.md（英文）
- ✅ gold 轻量 schema + YAML 模板 + 升格脚本（唯一可写 `benchmark/gold/` 的代码）
- ✅ 审阅工作台（35 篇构建；`--run-id` 已接新管线 `benchmark/runs/` 产物）
- ✅ 防污染三规则写入 AGENTS.md + 静态测试强制
- ❗️ 用户审核余项：模板试填、47 篇抽样名单扫描、README、防污染规则确认

## Phase 2 — 直接 API 提取管线 ✅（管线本体定稿 0.4.2）
- ✅ 确定性上下文打包 + `.bib` 按引用裁剪 + CJK 守卫
- ✅ 两段式生成 + 冻结 validator 把关 + 定向修复（修剪历史）
- ✅ provider 官方端锁定 + 模型降级 + 论文级并行
- ✅ roster 定稿（主力 `deepseek-v4-pro` + 补充 `mimo-v2.5-pro`）
- ✅ pilot-01~08 验证（温度 0 跨运行方差 / 残差错误性质 / 成本均已实证）
- ❗️ 正式 run 模型清单拍板 — 待用户充值 ~¥300–400（建议 deepseek×3 测方差 + mimo×1 横评）

## Phase 3 — 专家标注执行 ⌛️
> 触发：GUIDELINE 校准就绪 + 导师确认
- ⌛️ GUIDELINE 校准修订（2–3 篇双人校准后）
- ⌛️ 校准 2–3 篇（双人）
- ⌛️ 盲标 12 篇（含 5 篇双人重叠，报 Cohen's kappa）
- ⌛️ 校验 35 篇（看工作台，✓/✗/? + 备注）
- ⌛️ 分歧定向裁决
- 现状：`benchmark/gold/` 空

## Phase 4 — 四层评分 + 正式 runs + 分析 ⌛️
> 触发：gold 与 runs 真实形状落定
- ⌛️ 评分器 L1（候选集合 P/R + no_candidates 假阳性）
- ⌛️ L2（规范化字段值）
- ⌛️ L3（溯源 verdict）
- ⌛️ L4（方法事实 + step_type 集合 + method_refs 路由检查）
- ⌛️ 正式 runs（按拍板清单，全程存档）
- ⌛️ 方差与错误分析（主力 ×3 测方差；proxy 混淆矩阵入论文）
- 现状：`benchmark/scoring/` 空

## ⏳ 暂缓（B1，有触发条件）
- 全量重提取 211 篇 — 触发：benchmark 验证管线质量后，用已验证管线重提
- 太阳谱系 warning → error — 触发：若干真实论文在 v0.1 下跑通无误伤后
- lint / 类型检查工具（ruff 等） — 可选，冻结后任意时机，不阻塞 benchmark

## 🚫 红线（B2 明确不做，不可勾选）
- 不重提取语料 / 不推倒式重构 schema
- 不重命名磁盘数据布局（海量 source_refs 引用）
- 不自建 agent 框架 / 不开新 repo 或长期分支
- 不删 method_chain（拓扑、切分粒度、自由文本不进精确匹配评分）
- 不在冻结后改 schema / SKILL / validator（问题记 `docs/schema-v0.2-notes.md`）
- 不动网站前端与 `hvs_dynamics_calculate` 科学逻辑（重构仅改导入路径 / 脚本名）
