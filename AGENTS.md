# Stella 代理说明

本文件写给以后在 `stella-workspace` 中工作的 agent。

## 当前仓库内容

当前仓库主要流程：

- 按月份抓取高速星相关文献
- 用标题做相关性初筛
- 把标准结果写入 `notes/`
- 给已有月度 JSON 加上 `catalog_assessment`
- 从 JSON 生成 Markdown

## 项目愿景

Stella 的长期目标，是逐步建设一个面向高速星研究的、可追溯、可复现、
可持续更新的对象级数据与知识系统。

如果需要理解项目的长期方向、实施路线和未来扩展目标，请先阅读根目录的
`TODO.md`。

## 核心原则

JSON 是事实源。Markdown 只是从 JSON 生成的阅读视图，必须和 JSON 对应。

默认输出：

```text
notes/YYYY/YYYY-MM/YYYY-MM.json   月度标准记录
notes/YYYY/YYYY-MM/YYYY-MM.md     月度阅读笔记
notes/index.json                  全局索引
notes/index.md                    年度视图
```

不要手动改生成后的 Markdown。  
如果输出有问题，应修改 JSON 构建逻辑或 Markdown 渲染逻辑，然后重新生成。

## 文献流程

常用命令只需要 `--from`：

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py --from 2026-03
```

默认值应保持节省额度：

- `--source arxiv`
- `--classifier rules`
- `--llm-review False`
- 不抓 `DeepXiv brief`
- `--max-results 20`
- `--categories astro-ph.GA`
- `--search-mode hybrid`

默认标题规则分两层：

- `direct` / `rule-direct`：强相关
- `weak` / `rule-weak*`：弱相关，默认只保留搜索阶段元数据

如果开启 `--llm-review True`：

- 只让 LLM 判断弱匹配是否保留
- 不改变强匹配和弱匹配的分组

LLM 分类或复核时，输入应包含：

- 标题
- 搜索返回的摘要
- categories

不要只发标题，除非用户明确要求。

给已有月份补 `catalog_assessment` 时，使用：

```bash
conda run -n stella-env python scripts/annotate_catalog_data.py --on 2026-03
```

判断应结合 abstract；如果记录里已有旧的 brief 字段，也可以一起参考。完成后要刷新对应 Markdown，并重建索引。

## 工程规则

- 测试环境：`conda run -n stella-env python -m unittest discover tests`
- 除非用户明确要求重新抓数据，否则不要做真实 DeepXiv 调用
- JSON 里要保留 provenance：搜索来源、query、category、score、`run_id`
- weak 记录必须排在 direct 记录后面
- 月度 Markdown 中 direct 和 weak 之间要保留分隔线
- 遇到限额时，已经完成的月份仍然要保存 JSON、Markdown 和 partial summary
- 不要恢复无关改动，也不要回退用户已有的生成文件
- 如果改了依赖或环境步骤，要同时更新环境文件和相关文档

## 改动清单

改输出结构时，同时更新：

- `src/high_velocity_lit/records.py`
- `src/high_velocity_lit/markdown.py`
- `docs/outputs.md`
- 相关测试

改 CLI 参数或默认值时，同时更新：

- `scripts/fetch_high_velocity_lit.py`
- `docs/usage.md`
- `README.md`
- CLI 测试

改依赖或环境步骤时，同时更新：

- `environment.yml`
- `docs/setup.md`
- `README.md`

新增科学能力时，先设计机器可读 JSON，再考虑 Markdown 或其它展示层。
