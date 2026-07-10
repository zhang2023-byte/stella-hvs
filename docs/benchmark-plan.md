# Stella Benchmark — 计划与状态

> 本文件合并了原 `benchmark-master-plan.md`（2026-06-11 蓝图 + 修订记录）与
> `benchmark-task-checklist.md`（状态追踪），2026-07-06 定稿为唯一的现行计
> 划文档。已完成阶段压缩为结论；详细过程见 git 历史与
> `docs/schema-v0.2-notes.md`。
>
> **状态图例**：✅ 已完成 · ❗️ 当前焦点 · ⌛️ 待执行

## 主线一句话

为 HVS/不受束缚候选星的文献提取建立**专家金标准 benchmark**，对比三种 AI
提取方法，支撑论文发表：

- **方法 A**：skill 约束下的通用 coding agent（harness+模型记录后可复现）
- **方法 B**：直接 API 两段式管线 `stella-benchmark-extraction`（基线）
- **方法 C**：自研轻量工具驱动 ReAct 智能体 `stella-agentic-extraction`
  + 独立审核员（论文方法主张）

评分分层：**L1** 候选集合（P/R/F1）、**L2** 数值转录
（`docs/benchmark-l2-spec.md` v0.2.1，活契约）、**L3** 证据溯源（待设计）。
三条头条指标（L1 F1 / 仅配对严格一致率 / 端到端交付率）并排报告，
**明文禁止合成单一总分**（交付率已内嵌 L1 召回，合成会重复计罚）。

## 已完成（结论压缩；截至 2026-07-06）

- ✅ **A 段 技术债清理 + schema 冻结**（2026-06）：单一 `stella` 包、
  版本号归一 v0.1、schema 定向补齐（tooling/太阳参数/limit_kind）、
  1496 份数据迁移、身份对齐器；tag `benchmark-freeze-v1`。
- ✅ **Phase 1 基建**：分层抽样 manifest（框 207 → 抽 47，种子字节级可复
  算）、英文 GUIDELINE、gold 轻量 schema + 标注表单 + 升格脚本、AGENTS.md
  防污染三规则 + 静态测试。
- ✅ **Phase 2 方法 B 管线**：确定性上下文打包、两段式生成 + 冻结
  validator 把关 + 定向修复、论文级并行；pilot-01~08 验证；模型 roster
  deepseek-v4-pro（主力）+ mimo-v2.5-pro（横评）。
- ✅ **契约修订 + gold 外置**（2026-07-05）：专家先决 + AI 誊抄协议
  （`expert_led_scribe.v1`，GUIDELINE §6）；gold 迁入私有仓
  `stella-hvs-gold`（`STELLA_GOLD_DIR`），公共仓只留 SHA256 清单与 canary
  泄漏审计。
- ✅ **Phase 4 评分器 + 方法 C**（2026-07-06）：L1 评分器（三级身份匹
  配、bootstrap、泄漏防护）；方法 C v0（无框架 ReAct + mimo 审核员）；
  L2 规范逐规则专家签核并转正实现（scorecard v0.2）；HTML 报告吸收原
  comparison 看板（纯渲染 scorer 输出，写私有仓 `report/`）。
- ✅ **Schema v0.2**（2026-07-06，同日两批，正式 runs 前的一次性解冻）：
  移除 total_velocity；内联 thebibliography 证据；input_catalog 直接生产
  者；bound_assessment 只留双概率槽（escape ≡ unbound，词表 23→19）；
  unit 禁 LaTeX 标记 + 评分 normalize_unit v2。v0.1 语料经 legacy 读取模
  型零重提取。tag `benchmark-freeze-v2`（重指最终提交）。
- ✅ **gold8 dev 迭代**（8 篇 dev 集）：三轮评分暴露并修复了包含边界过度
  提取、多值选择、结构性校验高原；ai_only 分诊（2026-07-06 用户完成）：
  全部 ai_only 为 AI 幻觉、gold 正确，"gold 穷尽"假设成立；唯一 gold 侧
  修正 = 1807.00427 距离改回照抄 pc。
- ✅ **gold8/dev 同表面重跑**（v0.2 上三方法公平对比）：方法 A
  `gold8-a-01-cursor-composer25` 覆盖 8/8 dev 论文并逐篇通过
  `validate_hvs_candidates.py --require-complete`；方法 B 第三轮
  `gold8-b-03-deepseek-v4-pro`（0.6.0）覆盖 8/8 并通过校验；方法 C
  第三轮 `gold8-c-03-agentic-deepseek`（0.3.0）已跑完并生成 scorecard，
  但保留交付缺口：`1902.05061` 无 AI 输出，`1804.10179` 产物仍有 4 条
  semantic validation errors。三者公开 scorecard 均已写入 `benchmark/scoring/`；
  dev 迭代到此收手，后续不再为 8 篇 dev 集做提示词调优。

## 当前焦点与后续任务

- ❗️ **L3 证据溯源评分设计**（设计稿供专家审：定位符比对口径、抽查 vs
  全查）。
- ⌛️ **测试集专家标注**（主瓶颈）：39 篇 held-out；建议先按分层比例标
  15–20 篇即可跑首次正式评估（带置信区间），余量后续补充只收窄区间；
  每篇走誊抄协议约 20–40 分钟。
- ⌛️ **正式 runs**：deepseek-v4-pro ×3（测方差）+ mimo-v2.5-pro ×1（横
  评）+ 方法 A；全程存档 `benchmark/runs/`。正式 run 前不再调 dev 提示
  词；若方法 C 的 dev 交付缺口需要进入论文方法描述，作为 run outcome 记录
  而非继续修提示词。
- ⌛️ **方差与错误分析**：主力 ×3 方差、proxy 混淆矩阵、逐方法错误分类，
  入论文。

**dev/test 划分**：8 篇已标注 gold（1804.10179、1807.00427、1807.02028、
1902.05061、2209.03560、2401.02017、2403.03311、2602.16925）为 dev 集；
manifest 其余 39 篇为 held-out test，仅在 milestone 由用户人工触发评估。

## 暂缓（有触发条件）

- 全量重提取 211 篇 — 触发：benchmark 验证管线质量后，用已验证管线重提。
- 太阳谱系 warning → error — 触发：若干真实论文跑通无误伤后。
- lint / 类型检查工具（ruff 等）— 可选，任意时机，不阻塞 benchmark。
- schema 深层形状改造（l/b 字段、多值多估计等）—
  见 `docs/schema-v0.2-notes.md` 的 deferred 清单。

## 红线（明确不做；历次修订后的现行版）

- 不重提取语料 / 不推倒式重构 schema；不重命名磁盘数据布局（海量
  source_refs 引用）。
- 不删 method_chain（只作诊断展示，不进专家 benchmark 评分）。
- **正式活动锚点 `benchmark-freeze-v2`，此后至活动结束不再改 AI
  extraction schema / SKILL / validator**（v0.2 两批修复均发生在任何正式
  run 之前）。
- 提示词不做 fine-tuning 式调优（防 dev 集过拟合）；只允许修复明显设计缺
  陷并记录版本。
- 对 coding agent 的限制只用工具无关机制（目录拓扑、git、环境变量、
  AGENTS.md），不引入特定工具配置。
- 不动网站前端与 `hvs_dynamics_calculate` 科学逻辑。
- （已按批准解禁的原红线：自建轻量 agent = 方法 C；私有 gold 新仓；冻结
  后 schema 一次性解冻 = v0.2。）

## 关键决策记录（压缩；完整推理见 git 历史对应提交与讨论）

1. **专家先决 + AI 誊抄**取代纯手工 PDF 标注（2026-07-05）：专家先独立完
   成全部判断与定位，誊抄 agent 只做机械转录（同一 PDF），专家逐值核对。
2. **gold 外置私有仓**（2026-07-05）：公开仓 + 联网 agent 环境下静态白名
   单不构成运行时隔离；公共仓历史不重写，已暴露的 8 篇校准标注论文中脚注
   标记。
3. **方法 C 无框架**（2026-07-06）：手写工具驱动 ReAct，不引 LangGraph
   等编排框架。
4. **dev/test 划分 + `benchmark/runs/` 退出 git**（2026-07-06）；长时任
   务一律 `tmux + caffeinate` 后台守护。
5. **L1 包含边界**（首轮 dev 发现）：再评估终局为 bound 不构成候选；gold
   为准；共享 TASK_CLARIFICATIONS 注入两管线。
6. **L2 契约要点**（逐规则签核，v0.2.1）：gold 在 19 记分字段内穷尽，AI
   多填记 `ai_only` 入"填写精确率"；无仲裁层（专家漏记→改 gold 重跑）；
   严格档只认完全一致；单位只拼写归一；0.5″ 坐标桥；limit_kind 翻转判
   错；概率归一是唯一数值换算；多值分歧计错 + `gold_note_present` 分诊。
7. **版本号裁决**（2026-07-06）：v0.2 第二批曾短暂记作 "v0.3"；因首批零
   实例化，并为同一个 v0.2，`benchmark-freeze-v2` 重指最终提交（旧 tag
   哈希见提交信息，未锚定任何 run）。
