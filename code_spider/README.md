# GitHub Code Crawler

Collect source-code files from public GitHub repositories for dataset building.
The script searches repositories by language, reads repository trees, filters
files by extension/path/size, downloads text source files, and appends one JSON
metadata record per collected file.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a GitHub fine-grained or classic personal access token with public read
access and export it before crawling:

```bash
export GITHUB_TOKEN="ghp_xxx"
```

The script can run without a token, but unauthenticated REST API limits are very
small for practical dataset collection.

## Quick Start

```bash
python github_code_crawler.py \
  --languages python java go html \
  --max-repos-per-language 20 \
  --max-files-per-language 500 \
  --max-files-per-repo 50 \
  --min-stars 50 \
  --output data/github_code
```

Output:

```text
data/github_code/
  metadata.jsonl
  files/
    python/
    java/
    go/
    html/
```

`metadata.jsonl` stores repository, path, license, source URL, blob SHA,
content hash, local path, and download timestamp. Re-running the same command
will read existing metadata and skip already collected blobs/content hashes.

## Useful Examples

Dry run a small sample:

```bash
python github_code_crawler.py \
  --languages python js ts go \
  --max-repos-per-language 3 \
  --max-files-per-language 20 \
  --dry-run
```

Collect more languages:

```bash
python github_code_crawler.py \
  --languages python java go html javascript typescript css rust cpp csharp php ruby shell sql \
  --max-files-per-language 1000 \
  --output data/multi_lang_code
```

Use custom license filters:

```bash
python github_code_crawler.py \
  --languages python go \
  --license-policy custom \
  --licenses mit apache-2.0 bsd-3-clause \
  --output data/permissive_code
```

Disable license filtering:

```bash
python github_code_crawler.py \
  --languages python java go html \
  --license-policy any \
  --output data/github_code_any_license
```

## Notes

- Public GitHub code is not automatically free to reuse. By default the crawler
  searches common permissive licenses. Keep the metadata and review license
  obligations before redistribution or model training.
- The crawler uses GitHub REST repository search plus Git tree/content APIs, and
  handles primary and secondary rate-limit responses with retries and sleeps.
- GitHub search endpoints expose at most 1,000 results for a single query. Raise
  coverage by varying languages, license policy, star thresholds, or
  `--query-extra` date qualifiers.
