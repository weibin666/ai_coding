# GitHub Markdown Crawler

这个脚本用于从 GitHub 公开仓库收集 Markdown 文件，并按中文、英文或中英混合分桶保存。它使用 GitHub REST API 获取仓库和目录树，再从 `raw.githubusercontent.com` 下载 `.md` 内容。

> 注意：公开仓库内容不等于可任意商用。脚本会把仓库 license、来源 URL、commit sha 写入元数据，后续做数据集时请按 license 过滤。

## 快速开始

```bash
python3 github_md_crawler.py \
  --repo rust-lang/book \
  --repo vuejs/docs \
  --limit 50
```

输出默认写入：

```text
data/github_markdown/
  en/
  zh/
  metadata.jsonl
```

如果要爬取更多仓库，建议配置 GitHub Token，避免很快碰到匿名 API 限流：

```bash
export GITHUB_TOKEN=你的_token
python3 github_md_crawler.py \
  --query '中文 文档 stars:>100' \
  --query 'documentation stars:>1000' \
  --max-repos-per-query 20 \
  --limit 500 \
  --per-repo-limit 30
```

## 常用参数

- `--repo owner/name`：指定仓库，可重复传入，也支持 GitHub 仓库 URL。
- `--repos-file repos.txt`：从文本文件读取仓库列表，一行一个 `owner/name` 或 URL。
- `--query '...'`：使用 GitHub 仓库搜索找候选仓库，可重复传入。
- `--langs zh,en,mixed`：保存哪些语言桶，默认 `zh,en`。
- `--path-include REGEX`：只收集匹配路径的 Markdown，例如 `--path-include '(^|/)docs/'`。
- `--path-exclude REGEX`：排除路径，例如 `--path-exclude 'node_modules|vendor|CHANGELOG'`。
- `--limit N`：本次最多保存多少个文件，默认 `200`。
- `--per-repo-limit N`：每个仓库最多保存多少个文件，默认 `30`。
- `--max-bytes N`：跳过过大的 Markdown 文件，默认 `1000000`。
- `--dry-run`：只下载并分类，不写入文件。

## 元数据格式

每保存一个 Markdown 文件，脚本会在 `metadata.jsonl` 追加一行 JSON，包含：

- `repo`、`path`、`commit_sha`、`source_url`、`raw_url`
- `license_spdx`、`license_name`
- `detected_lang`、`text_chars`、`cjk_chars`、`latin_words`
- `sha256`、`local_path`

这份元数据可以用来去重、追溯来源、按 license 做二次过滤。

## 示例：只抓 docs 目录

```bash
python3 github_md_crawler.py \
  --repos-file repos.txt \
  --path-include '(^|/)docs/' \
  --path-exclude 'CHANGELOG|node_modules|vendor' \
  --langs zh,en,mixed \
  --limit 1000
```

`repos.txt` 示例：

```text
# owner/name 或 GitHub URL 均可
vuejs/docs
https://github.com/rust-lang/book
```
