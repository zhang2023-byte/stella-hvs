# 标题分类

默认流程是先用规则做标题初筛，再按需用 LLM 复核“标题没有明显证据”的论文。

## 规则直判相关

命中明确高速星标题规则的论文会被归入 `rule-related`，直接进入最终月度 note。

常见标题词：

```text
hypervelocity star
high-velocity star
high-velocity RR Lyrae stars
extreme-velocity stars
fastest stars in the Galaxy
runaway star
hyper-runaway star
unbound star
escaping/ejected star
stellar escaper
walkaway star
hypervelocity/high-velocity star surveys, searches, candidates, catalogues
```

## 标题没有明显证据

凡是没有命中明确高速星标题规则的标题，都会被归入 `no-clear-title-evidence`。

这里故意不再单独区分 `rejected`。也就是说，哪怕标题看起来更像泛工具、泛方法或泛天文论文，只要没有命中“直接相关”规则，也先放进这一桶。

这类论文不会直接进入最终月度 note，但会被保存到月度标题分类文件：

```text
notes/YYYY/YYYY-MM/YYYY-MM.title-triage.json
```

常见例子包括：

```text
Stellar Escape from Globular Clusters
Where do they come from? Identification of globular cluster escaped stars
galpy: A Python Library for Galactic Dynamics
emcee: The MCMC Hammer
Galaxy formation and evolution
Gaia Early Data Release 3 summary papers
Joint inference from parallax and proper motions
```

## 用 LLM 复核“标题没有明显证据”的论文

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03 \
  --llm-review True
```

这个模式下：

- `rule-related` 直接进入最终月度 note
- `no-clear-title-evidence` 会送给 LLM 复核
- 被 LLM 确认相关的论文会进入最终月度 note
- 被 LLM 否决或未返回结果的论文不会进入最终月度 note
