# Stella 技术债清理 + 专家金标准 Benchmark — 行动方案（总蓝图）

> **归档说明**：这是 2026-06-11 plan-mode 定稿的原始结构化方案，归档进仓库
> 作永久、版本化的权威蓝图。运行进度与逐次决策记录在自动记忆文件
> `~/.claude/projects/.../memory/stella-benchmark-plan.md`（按时间线叙事）；本文件
> 保留**任务分解 + 否决清单 + 触发条件**这类不随时间变的骨架。两者互补。
>
> **执行状态快照（截至 2026-06-13）**：
> - **A 段（A1–A11 技术债清理 + schema 窗口）：全部完成并冻结**，tag `benchmark-freeze-v1`（重打至 281c8b4）。测试基线 243 → 已增至 412 全绿。
> - **Phase 1（benchmark 基础设施）：完成**（commit 2bd684d 起，含后续 GUIDELINE 修订）。抽样 manifest、英文 GUIDELINE、YAML 标注模板+升格脚本、PDF 锚点审阅工作台、AGENTS.md 防污染三规则+测试均已落地。
> - **Phase 2（直接 API 提取管线）：管线 0.4.2 定稿**。两段式生成（scaffold+roster → 批填充 → 合并 → 定向修复），.bib 按引用裁剪，Token Dance 网关，provider 官方端锁定，论文级并行。pilot-01~08 验证完毕。roster 收缩为 deepseek-v4-pro（主力）+ mimo-v2.5-pro（补充）。
> - **Phase 3（专家标注执行）：未启动**，待用户+导师就绪。
> - **Phase 4（四层评分 + 正式 runs）：未启动**，待 gold/runs 真实形状落定。
> - 偏离原计划处均有记录，详见自动记忆文件与各 commit。

## Context（背景与动机）

stella_hvs 已完成初步提取：211 篇归档、210 份 `literature_hvs_candidates.json`（49 有候选 / 156 无候选 / 5 未完成）、898 条候选。目标：建立专家金标准 benchmark 支撑论文发表。**在冻结和标注开始前，先彻底清理探索期技术债**——冻结后不可再动，这是最后窗口。

已达成的共识（2026-06-11 多轮讨论）：双人标注（用户+导师，20–50 h）、混合标注设计、同仓库 `benchmark/`、直接 API 管线（不自建框架）、method_chain 保留并降维评分、太阳参数结构化、限值字段纳入、**版本号全部重置 v0.1**（正式发布统一跳 v1.0）、**src 合并为单一 `stella` 包**、**旧文件机械迁移保留现有判断，全量重提取延后到 benchmark 验证管线之后**。

技术债盘点结论（除用户已提出的版本号/命名/结构外，系统检查新发现）：无打包配置、20/22 脚本与 24/25 测试存在 `sys.path` hack、无测试 CI、skills 目录命名画风不一（kebab 与 snake 混用）、workflows "yaml" 内容实为 JSON、`migrate_external_resource_source_refs.py` docstring 文不对题且属已完成的一次性脚本、README 与 vision.md 动机文字大段重复、`.pytest_cache` 未忽略、gitignore `!.env.example` 规则指向不存在的文件。基线：243 个测试当前全绿。

---

# A. 本次实施：技术债清理 + Schema 窗口（约 3–4 周）

## 贯穿全程的三条不变式

1. **磁盘数据布局不动**：`literature/<arxiv_id>/...`、`notes/`、`catalog/` 目录与文件名保持原样——海量 `source_refs` 引用这些路径，未来 gold 也会引用。改代码的画风，不动数据的地址。
2. **每个台阶测试绿**（基线 243 个）后才进下一步；禁止大爆炸式一次改完。
3. **生成文件只重新生成**：schema.md、索引、Markdown 视图一律脚本重建，不手改。

## A1. git 白名单备份（最先做，一切重构前的安全网）

**[.gitignore](.gitignore)**：`literature/` 整体忽略改白名单（git 需先放行父目录）：

```gitignore
literature/**
!literature/*/
!literature/*/catalog_review.json
!literature/*/catalog_extraction.json
!literature/*/literature_hvs_candidates.json
```

`git add literature/ && git commit && git push`。验证：临时目录 clone 核对三类 JSON 数量（约 210/211/210）；commit 前核对无大文件混入。

## A2. 工程基线加固（重构的护栏，先于重构）

- **测试 CI**：新增 `.github/workflows/tests.yml`——push/PR 时装 `environment.yml` 依赖并跑 `python -m unittest discover tests`。后续每个重构台阶都有远端护栏。
- **Python 打包**：新增 `pyproject.toml`（setuptools，src layout，项目名 `stella`），`pip install -e .` 进 stella-env；`docs/setup.md`、`environment.yml`（加 `-e .`）、README 同步。
- **小修缮包**（低风险一次提交）：`.gitignore` 加 `.pytest_cache/`；`env.example` → `.env.example` 并修正 gitignore 规则与 README/docs 中的 `cp` 命令；修正 `migrate_external_resource_source_refs.py` 文不对题的 docstring（去留在 A3 inventory 决定）；README 动机段缩成摘要+链接 `docs/vision.md`，消除双份漂移。

## A3. 代码结构重构：单一 `stella` 包 + 命名统一

- **包合并**：`src/high_velocity_lit/` → `src/stella/lit/`；`src/high_velocity_dyn/` → `src/stella/dyn/`；`src/stella_html/` → `src/stella/html/`；`src/stella_benchmark/`（空）→ `src/stella/benchmark/`
- **删除全部 `sys.path.insert` hack**（约 20 个脚本 + 24 个测试），改为依赖 A2 的可编辑安装直接 `import stella.*`
- **脚本命名清理**：先 inventory 产出"旧名 → 新名"对照表（提交到 `docs/`，永久迁移记录）；统一动词_名词风格、去 `high_velocity` 残留（如 `fetch_high_velocity_lit.py` → `fetch_literature.py` 类；最终名以对照表为准）；**一次性脚本去留规则**：已完成的迁移类脚本（如 `migrate_external_resource_source_refs.py`）删除（git 历史可寻）或移入 `scripts/archive/`
- **skills 目录命名统一**：`hvs_dynamics_calculate` → kebab 风格与其余对齐（如 `hvs-dynamics-calculate`），目录名、SKILL.md frontmatter `name:` 同步
- **workflows 清单格式归一**：`workflows/stella_workflows.yaml` 内容实为 JSON——转成真 YAML（保留 .yaml 名）；`test_workflow_manifest` 同步
- **全量引用同步**：`workflows/stella_workflows.yaml` 的 commands/referenced_paths、`AGENTS.md`、各 `skills/*/SKILL.md`、`docs/usage.md`/`outputs.md`/`setup.md`/`workflows.md`、`README.md`、`.github/workflows/`、CLI 测试
- **完成判据**：grep `high_velocity_lit|high_velocity_dyn|stella_html|stella_benchmark|sys.path.insert` 及全部旧脚本名零残留（git 历史除外）；workflows 清单中每条 command 实际可执行；测试全绿

## A4. 版本号统一重置 v0.1

- `src/stella/lit/schema_specs.py`（重构后路径）中全部 `*_SCHEMA_VERSION` 改为 `stella.<artifact>.v0.1`（hvs_candidates v7、review v1、extraction v2、各索引版本全部归一）
- 约定写入 `docs/outputs.md`：0.x 期间各 schema 同步 bump；正式发布统一跳 v1.0；新旧版本对应关系记入迁移文档
- 数据文件版本字符串由 A6 迁移脚本改写；索引与视图重新生成

## A5. schema 内容定向改进（并入 v0.1；推倒式重构已否决——v7 骨架经评审是好的）

### A5.1 枚举 — `schema_specs.py`
- `LITERATURE_HVS_METHOD_STEP_TYPES` 加 `"solar_position_and_motion"`
- 新增 `LITERATURE_HVS_METHOD_PARAMETER_NAMES = ("R0", "z0", "v_circ_sun", "solar_motion_u", "solar_motion_v", "solar_motion_w", "potential_name", "escape_velocity_definition", "other")`
- 新增 `LITERATURE_HVS_LIMIT_KINDS = ("", "lower_limit", "upper_limit", "range")`

### A5.2 模型 — `schema_models.py`
- **`ToolingMeta(StrictModel)`**：`agent_runtime`、`model_id`（带日期快照）、`prompt_version`（git commit/tag）、`request_parameters: dict`；`HvsExtractionMeta` 加 `tooling: ToolingMeta | None = None`
- **`MethodParameterRecord(StrictModel)`**：`name`（受控枚举）、`raw_value`、`value`、`error/lower_error/upper_error`、`unit`、`source_refs`；**不含 `method_refs`**。`MethodStep` 加 `parameters: list[MethodParameterRecord] = []` 与新 step_type
- **`QuantityRecord`** 加 `limit_kind`（默认 `""`）、`range_lower`、`range_upper`。语义：lower/upper 限值时界值在 `value` 并以 `limit_kind` 标记；range 时 `value` 留空
- schema_version Literal 与 `MODEL_BY_SCHEMA_VERSION` 同步 v0.1

### A5.3 谱系与验证 — `hvs_method_provenance.py`、validator
- 太阳步骤谱系要求**先 warning**（不进 `CATEGORY_REQUIRED_LINEAGE_STEP_TYPES` 硬规则）：银心/静止系速度与 bound_assessment 量谱系缺 `solar_position_and_motion` 时告警；跑通真实论文后再升 error
- `STEP_TYPE_COARSE_SIGNALS` 加空信号集条目（同 `galactic_potential_model`）
- validator 新规则：`--require-complete` 下 `tooling` 必须存在且 `model_id`/`prompt_version` 非空（迁移旧文件填 `"unknown_legacy"` 显式可审计）；太阳步骤 `parameters[]` 非空或 summary 明确 not_reported；限值一致性（`limit_kind` 非空 ⇒ `raw_value` 含相应记号；range ⇒ `value` 空且界值非空）

### A5.4 文档与提示词
- `generate_schema_docs.py` 重新生成 schema.md；SKILL.md 第 8 步加太阳假设、parameters 填写规则、限值用法；`docs/outputs.md` 同步

## A6. 数据迁移脚本（保留全部现有判断）

新增 `scripts/migrate_data_to_v0_1.py`：三类 JSON 就地迁移——版本字符串、`tooling=unknown_legacy`、新字段默认值。机械且幂等。迁移后：全量 validate 零 error（旧运动学文件的太阳谱系 warning 属预期）；重建索引与视图；候选计数对账（49/156/5、898 条不变）。

## A7. 批处理 driver 转正

`logs/catalog_review_driver_2023_2026.py` → `scripts/`（按 A3 新命名）：月份窗口与日志路径改 CLI 参数；可复用部分（JSON 解析、LLM 重试、分片）抽到 `src/stella/lit/llm_batch.py` 供 Phase 2 复用；配 `tests/test_llm_batch.py`。

## A8. 清理 5 个未完成文件

2101.10878、2011.10206、2003.12766（needs_review）、1901.04559（partial）、2206.13002（source_missing）：逐一补完（v0.1 validator 复检）；确实无法补的保留显式状态、后续 manifest 排除。

## A9. 身份对齐器

`src/stella/benchmark/identity.py` + CLI `scripts/match_candidate_identities.py`：确定性三级匹配（Gaia source_id 精确含 DR 区分 → 名字别名规范化 → 坐标容差；容差与历元实施时与用户确认）。合成用例覆盖别名冲突、DR 不一致、坐标边界。

## A10. schema 系统扫描（冻结前最后工序）

对 schema + 抽 20 份真实产物系统检查，残余 gap 一次过堂（三问：科学必要性 / 每篇提取边际成本 / 评分影响）；通过并入 v0.1，否则记 v0.2 笔记。

## A11. 冻结

全部完成、CI 与本地测试绿、生成文件无 diff 残留后，打 tag `benchmark-freeze-v1`。此后 schema/SKILL/validator 问题一律记笔记不动手。

**实施顺序**：A1 → A2 → A3 → A4+A5（同一窗口）→ A6 → A7/A8/A9（可并行）→ A10 → A11。

---

# B. 现在不实施的改动（明确清单）

## B1. 暂缓 — 有明确触发条件

| 改动 | 触发条件 |
|---|---|
| **全量重提取 211 篇**（已共识延后：重提的真实成本是质量未知；机械迁移已保留现有判断） | benchmark 验证管线质量后，用已验证管线重提——届时是升级而非抽奖 |
| **Phase 1**：`benchmark/{GUIDELINE, manifest, gold/, runs/, scoring/}`、分层抽样、专家模板+升格脚本、证据并排审阅渲染器、AGENTS.md 防污染三规则+测试 | A11 冻结后启动 |
| **Phase 2**：直接 API 候选提取管线（确定性上下文打包、多模型、asyncio、tooling 入档），复用 A7 的 `llm_batch.py` | 冻结后；先在 2–3 篇非 benchmark 论文调通 |
| **Phase 3**：专家标注（校准 2–3 篇 → 盲标 ~10+5 重叠报 kappa → 校验 30–35 → 分歧裁决） | GUIDELINE 就绪 + 导师确认 |
| **Phase 4**：四层评分（L1 候选集合 / L2 规范化字段值 / L3 溯源 / L4 方法事实+step_type 集合+路由检查）、正式 runs（2–4 模型 ×1 + 主力 ×3）、方差与错误分析 | gold 与 runs 就绪后 |
| 太阳谱系 warning → error | 若干真实论文在 v0.1 下跑通无误伤后 |
| lint/类型检查工具（ruff 等）引入 | 可选项，冻结后任意时机；不阻塞 benchmark |

## B2. 明确不做（已讨论否决，记录防反复）

- **不**现在重提取语料；**不**对 schema 内容做推倒式重构（改进 = A5 定向补齐 + A10 扫描过堂）
- **不**重命名磁盘数据布局（`literature/<arxiv_id>/` 等被海量 source_refs 引用）
- **不**从零自建 agent 框架；**不**开新 repo 或长期分支
- **不**删除 method_chain；其 `depends_on` 拓扑、切分粒度、自由文本不进精确匹配评分
- **不**在冻结后修改 schema/SKILL/validator（记 v0.2 笔记）
- **不**动网站/前端与 `hvs_dynamics_calculate` 的科学逻辑（重构仅改其导入路径与脚本名）

---

# 验证方式

1. 每台阶后本地 `python -m unittest discover tests`（基线 243 绿）+ A2 起的 CI 远端护栏
2. A1：临时 clone 核对三类 JSON 数量
3. A3：grep 旧名与 `sys.path.insert` 零残留；workflows 清单 commands 逐条可执行
4. A6：迁移幂等（跑两遍一致）；全量 validate 零 error；候选计数对账（49/156/5、898）
5. A5 整体：选 1–2 篇含运动学的真实论文按新 SKILL 完整提取 + `--require-complete`，确认太阳步骤/参数/tooling/限值端到端可用
6. A11 前：git status 干净、schema.md 重新生成无 diff、CI 绿

# 风险与对策

- **重构遗漏引用**：grep 零残留 + 全量测试 + workflows 命令试跑为完成判据；CI 先行
- **gitignore 白名单写错**：commit 前核对新增文件清单
- **迁移损坏数据**：A1 先入 git 备份；前后计数对账；脚本幂等
- **scope creep**：A10 扫描有截止；schema 推倒式重构、数据布局改名已明确否决
- **锚定效应/共模错误**（Phase 3–4 风险，记录备查）：校验集结论连同盲标校准偏差一起报告；多模型一致项仍抽查
