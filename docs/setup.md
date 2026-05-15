# 环境准备

## 创建环境

```bash
conda env create -f environment.yml
conda activate stella-env
```

如果环境已存在，但依赖有变化：

```bash
conda env update -f environment.yml --prune
conda activate stella-env
```

这个环境现在也包含本地资料归档流程需要的 HTML 解析、网络请求、Pydantic
schema 校验，以及外部 catalog 表格解析依赖；FITS、VOTable 和 CDS/MRT ASCII
通过 `astropy` 读取。

## 可选外部工具

表格提取流程优先使用 LaTeXML，把论文 LaTeX 表格转换为 HTML 后再生成 ECSV。
macOS 推荐安装：

```bash
brew install latexml
```

确认工具可用：

```bash
which latexmlc
latexmlc --VERSION
```

如果没有 LaTeXML，`scripts/extract_catalog_tables.py` 会尝试 Pandoc；
如果 Pandoc 也不可用，则回退到项目内的轻量 LaTeX parser，但复杂表格保真度会下降。

## 配置 `.env`

项目密钥写在 `.env` 中，这个文件不会进入 Git：

```bash
cp env.example .env
```

如果你要使用 `--source deepxiv`，或运行带 DeepXiv 增强阅读的 `catalog_assessment`，建议填写：

```env
DEEPXIV_TOKEN=
```

可选。只有在这些步骤中才需要：

- 标题没有明显证据的论文做 LLM 复核
- `catalog_assessment`

```env
LLM_API_KEY=
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_THINKING=
LLM_REASONING_EFFORT=
```

主要 Python CLI 共用同一个 `.env` loader，会按下面顺序读取环境变量：

- `~/.env`
- 项目根目录 `.env`
- 当前工作目录 `.env`

不要把密钥写进 `environment.yml`。
`environment.yml` 只放可复现的依赖。
