# Stella Agent Guide

这份文件给后续参与 `stella-workspace` 的 Agent 使用。请先读它，再改代码或跑任务。

## 项目目标

Stella 的目标不是只做文献列表，而是建设高速星领域的数据集成基础设施。文献检索是前置能力：先准确找到高速星相关论文，再从论文中抽取方法、数据集、恒星对象、观测量、轨道积分和化学信息，最终形成可追溯、可复现、可持续更新的高速星知识库和对象级 catalog。

长期方向包括：

- 每日或定期推送领域新文献。
- 整理 Gaia Era 以来高速星文献，对每颗星整合不同文献中的相空间、光谱、轨道、化学元素和可能起源。
- 新数据集发布后，与已有高速星对象库交叉匹配和校准。
- 新文章发布后，把新发现候选体与已有数据集比对、入库，并更新知识库。
- 保存可复现的物理验证流程，例如速度转换、轨道积分、起源回溯和多模型交叉验证。
- 逐步建设数据库和网站，让 catalog 与知识整理可以被检索、验证和复用。

## 当前核心原则

JSON 是唯一事实源。Markdown 只是从 JSON 生成的人类阅读视图，必须与 JSON 完全对应。

默认输出：

```text
data/literature/monthly/YYYY-MM.json   月度 canonical record
data/literature/index.json             月度集合索引
data/literature/papers.jsonl           扁平论文流，方便机器处理
notes/YYYY-MM.md                       从月度 JSON 生成的阅读笔记
notes/index.md                         从 index JSON 生成的索引
```

不要为了修正文案直接手改生成的 Markdown。如果数据或展示不对，优先修改 JSON record 生成逻辑或 Markdown renderer，然后重新生成。

## 文献工作流

默认命令只需要 `--from`：

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py --from 2026-03
```

默认值应保持配额友好：

- `--source deepxiv`
- `--classifier rules`
- `--llm-review False`
- `--brief True`
- `--max-results 20`
- `--categories astro-ph.GA`
- `--search-mode hybrid`

默认规则分类分两层：

- `direct` / `rule-direct`：强相关，拉取 DeepXiv brief。
- `weak` / `rule-weak*`：弱相关，只保留 search 阶段已有信息，除非用户明确开启 LLM 复核。

LLM 分类或复核应同时使用 title、search-returned abstract 和 categories。不要只给标题，除非用户明确要求做标题-only 对照实验。

## 工程约定

- 在 `stella-env` 中测试：`conda run -n stella-env python -m unittest discover tests`。
- 避免真实 DeepXiv 调用，除非用户明确要求重新跑数据；DeepXiv 有配额限制。
- 保留 provenance：搜索源、关键词、分类、score、brief 是否拉取、跳过原因、run_id 都要留在 JSON 中。
- 弱相关条目必须排在强相关之后；Markdown 中两者之间保留分割线。
- 遇到 rate limit 时，已经完成的月份必须保存 JSON、Markdown 和 partial summary。
- 不要回滚用户已有的生成笔记或工作区改动。只提交与你任务相关的代码、测试和文档。

## 后续 Agent 做事方式

改动输出结构时，同步更新：

- `src/high_velocity_lit/records.py`
- `src/high_velocity_lit/markdown.py`
- `docs/outputs.md`
- 相关测试

改动 CLI 参数或默认值时，同步更新：

- `scripts/fetch_high_velocity_lit.py`
- `docs/usage.md`
- `README.md` 中必要的最短说明
- CLI 解析测试

新增科研能力时，优先把结果设计成机器可读 JSON，再考虑 Markdown、人类说明或网站展示。
