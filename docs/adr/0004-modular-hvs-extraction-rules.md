# ADR 0004: Modular HVS extraction rule profiles

状态：已接受（2026-07-13）

## 背景

HVS candidate extraction 的共享科学规则曾同时出现在 expert guideline、
Method A skill，以及 Method B/C runner prompt 中。即使内容相近，独立维护的
自然语言副本仍会产生漂移，也使 reviewer 与 roster 阶段的规则边界难以审计。

## 决策

1. `skills/hvs-candidates-extraction/rules/*.yaml` 是共享候选边界、身份、数量、
   科学判断和 agent evidence/provenance 规则的单一规范来源。每条规则只有稳定
   `id`、`title` 和规范性 `text`。
2. `profiles.yaml` 显式、有序地声明 `hvs_extractor`、`hvs_roster`、
   `hvs_reviewer` 与 `hvs_expert_shared`；不使用 profile 继承、条件表达式、任意
   include 或独立规则版本号。
3. Method A 使用由 `hvs_extractor` 生成到 `SKILL.md` 的提交视图。Methods B/C
   在运行时直接渲染同一个 `hvs_extractor` profile，再附加各自的纯编排提示词。
   Roster 和 B/C 共享 reviewer 只渲染声明的子集。
4. `benchmark/GUIDELINE.md` 只生成 `hvs_expert_shared` 规范块；PDF-only evidence、
   scribe 边界、gold schema 和人工工作流继续手写。
5. 生成视图提交到 Git，并由 `scripts/generate_extraction_rule_views.py --check`
   以及正式 run preflight 阻止陈旧内容。B/C skill component hash 覆盖完整 HVS
   skill tree，run parameters 记录 profile id 和 canonical profile SHA-256。

## 拒绝的方案

- **只在 runtime 组装、不提交可读视图**：不利于人工审阅 Method A skill 与
  guideline，也使普通 diff 无法显示最终规范文本。
- **生成完整 guideline**：会把背景解释、PDF-only、scribe 与 gold 工作流耦合进
  extraction rule schema，扩大需要机器化维护的范围。
- **立即抽到跨领域通用仓库**：当前没有第二种特殊天体 schema 可验证抽象边界；
  先保留 HVS-local 模块，避免本次内部重构演变为产品级 schema 泛化。

## 后果与版本边界

- 修改 YAML 规则会改变 profile hash、skill component hash 和新 run 的 method
  fingerprint；已有 run、gold 与 scorecard 不变。
- Guideline 生成块变化会改变 guideline 文件 hash；新 annotation 记录新 hash，
  已有 annotation 不迁移。
- 本决策不改变 candidate JSON schema、validator、scoring 或 campaign，因此不新增
  artifact/schema/campaign 版本。任何实际候选边界、gold evidence 或 scored
  vocabulary 变化必须停止本重构并单独评审 campaign 影响。
