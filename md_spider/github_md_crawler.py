#!/usr/bin/env python3
"""Collect Chinese and English Markdown files from public GitHub repositories.

The crawler uses GitHub's REST API for repository metadata and git trees, then
downloads Markdown blobs from raw.githubusercontent.com. It avoids webpage
scraping, keeps rate limits visible, and writes a JSONL manifest for provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


GITHUB_API = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd"}
RETRY_STATUSES = {429, 500, 502, 503, 504}

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
LATIN_WORD_RE = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)?")
LATIN_LETTER_RE = re.compile(r"[A-Za-z]")
FENCED_CODE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
URL_RE = re.compile(r"https?://\S+")


class GitHubError(RuntimeError):
    """Raised for GitHub API or raw download failures."""


@dataclass(frozen=True)
class RepoRef:
    owner: str
    name: str
    default_branch: str | None = None
    stars: int | None = None
    html_url: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class MarkdownBlob:
    path: str
    sha: str
    size: int


@dataclass(frozen=True)
class LanguageStats:
    detected_lang: str
    text_chars: int
    cjk_chars: int
    cjk_ratio: float
    latin_words: int
    latin_ratio: float
    sha256: str


class GitHubClient:
    def __init__(
        self,
        token: str | None,
        sleep_seconds: float,
        max_rate_wait: int,
        timeout: int = 30,
        retries: int = 3,
    ) -> None:
        self.token = token
        self.sleep_seconds = sleep_seconds
        self.max_rate_wait = max_rate_wait
        self.timeout = timeout
        self.retries = retries

    def api_get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> tuple[Any, dict[str, str]]:
        if path.startswith("https://"):
            url = path
        else:
            url = f"{GITHUB_API}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "md-spider/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        data, response_headers = self._request_bytes(url, headers=headers)
        try:
            return json.loads(data.decode("utf-8")), response_headers
        except json.JSONDecodeError as exc:
            raise GitHubError(f"GitHub API returned invalid JSON for {url}") from exc

    def download_raw(self, url: str, max_bytes: int) -> bytes:
        headers = {"User-Agent": "md-spider/1.0"}
        data, _ = self._request_bytes(url, headers=headers, max_bytes=max_bytes)
        return data

    def _request_bytes(
        self,
        url: str,
        headers: dict[str, str],
        max_bytes: int | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        for attempt in range(self.retries + 1):
            if self.sleep_seconds > 0:
                time.sleep(self.sleep_seconds)

            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    response_headers = dict(response.headers.items())
                    if max_bytes is not None:
                        length = response.headers.get("Content-Length")
                        if length and int(length) > max_bytes:
                            raise GitHubError(
                                f"Skipping oversized file ({length} bytes): {url}"
                            )
                        data = response.read(max_bytes + 1)
                        if len(data) > max_bytes:
                            raise GitHubError(
                                f"Skipping oversized file (> {max_bytes} bytes): {url}"
                            )
                    else:
                        data = response.read()
                    return data, response_headers
            except urllib.error.HTTPError as exc:
                response_headers = dict(exc.headers.items())
                body = exc.read().decode("utf-8", errors="replace")[:600]
                if self._handle_rate_limit(exc.code, response_headers, url):
                    continue
                if exc.code in RETRY_STATUSES and attempt < self.retries:
                    self._backoff(attempt)
                    continue
                raise GitHubError(f"HTTP {exc.code} for {url}: {body}") from exc
            except urllib.error.URLError as exc:
                if attempt < self.retries:
                    self._backoff(attempt)
                    continue
                raise GitHubError(f"Network error for {url}: {exc}") from exc

        raise GitHubError(f"Request failed after retries: {url}")

    def _handle_rate_limit(
        self, status_code: int, headers: dict[str, str], url: str
    ) -> bool:
        remaining = headers.get("X-RateLimit-Remaining")
        reset = headers.get("X-RateLimit-Reset")
        if status_code not in {403, 429} or remaining != "0" or not reset:
            return False

        wait_seconds = max(0, int(reset) - int(time.time()) + 3)
        if wait_seconds > self.max_rate_wait:
            raise GitHubError(
                "GitHub API rate limit reached. "
                f"Reset is in {wait_seconds}s, above --max-rate-wait. "
                "Set GITHUB_TOKEN or reduce the crawl size."
            )

        print(
            f"[rate-limit] waiting {wait_seconds}s before retrying {url}",
            file=sys.stderr,
        )
        time.sleep(wait_seconds)
        return True

    @staticmethod
    def _backoff(attempt: int) -> None:
        time.sleep(min(30, 2**attempt))


def parse_repo_ref(value: str) -> RepoRef:
    value = value.strip()
    if not value:
        raise ValueError("empty repository value")

    if value.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(value)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2 or parsed.netloc.lower() not in {
            "github.com",
            "www.github.com",
        }:
            raise ValueError(f"not a GitHub repository URL: {value}")
        owner, name = parts[0], parts[1]
    else:
        parts = value.split("/")
        if len(parts) != 2:
            raise ValueError(f"expected owner/repo, got: {value}")
        owner, name = parts

    if name.endswith(".git"):
        name = name[:-4]
    if not owner or not name:
        raise ValueError(f"invalid repository reference: {value}")
    return RepoRef(owner=owner, name=name)


def read_repo_file(path: Path) -> list[RepoRef]:
    repos: list[RepoRef] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            repos.append(parse_repo_ref(stripped))
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
    return repos


def search_repositories(
    client: GitHubClient,
    queries: Iterable[str],
    max_repos_per_query: int,
) -> list[RepoRef]:
    repos: list[RepoRef] = []
    seen: set[str] = set()

    for query in queries:
        remaining = max_repos_per_query
        page = 1
        while remaining > 0:
            per_page = min(100, remaining)
            payload, _ = client.api_get(
                "/search/repositories",
                {
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": per_page,
                    "page": page,
                },
            )
            items = payload.get("items", [])
            if not items:
                break

            for item in items:
                full_name = item["full_name"].lower()
                if full_name in seen:
                    continue
                seen.add(full_name)
                repos.append(
                    RepoRef(
                        owner=item["owner"]["login"],
                        name=item["name"],
                        default_branch=item.get("default_branch"),
                        stars=item.get("stargazers_count"),
                        html_url=item.get("html_url"),
                    )
                )

            remaining -= len(items)
            page += 1
            if len(items) < per_page:
                break

    return repos


def repo_metadata(client: GitHubClient, repo: RepoRef) -> dict[str, Any]:
    payload, _ = client.api_get(f"/repos/{repo.owner}/{repo.name}")
    if payload.get("private"):
        raise GitHubError(f"Skipping private repository: {repo.full_name}")
    return payload


def default_branch_commit_sha(
    client: GitHubClient, repo: RepoRef, default_branch: str
) -> str:
    encoded_branch = urllib.parse.quote(default_branch, safe="")
    payload, _ = client.api_get(
        f"/repos/{repo.owner}/{repo.name}/branches/{encoded_branch}"
    )
    return payload["commit"]["sha"]


def markdown_blobs(
    client: GitHubClient,
    repo: RepoRef,
    tree_sha: str,
    include_patterns: list[re.Pattern[str]],
    exclude_patterns: list[re.Pattern[str]],
) -> tuple[list[MarkdownBlob], bool]:
    payload, _ = client.api_get(
        f"/repos/{repo.owner}/{repo.name}/git/trees/{tree_sha}",
        {"recursive": "1"},
    )
    truncated = bool(payload.get("truncated"))
    blobs: list[MarkdownBlob] = []

    for item in payload.get("tree", []):
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")
        extension = Path(path).suffix.lower()
        if extension not in MARKDOWN_EXTENSIONS:
            continue
        if include_patterns and not any(pattern.search(path) for pattern in include_patterns):
            continue
        if exclude_patterns and any(pattern.search(path) for pattern in exclude_patterns):
            continue
        blobs.append(
            MarkdownBlob(
                path=path,
                sha=item.get("sha", ""),
                size=int(item.get("size") or 0),
            )
        )

    blobs.sort(key=lambda blob: (blob.path.count("/"), blob.path.lower()))
    return blobs, truncated


def raw_url(repo: RepoRef, commit_sha: str, path: str) -> str:
    quoted_path = urllib.parse.quote(path, safe="/")
    return f"{RAW_BASE}/{repo.owner}/{repo.name}/{commit_sha}/{quoted_path}"


def blob_url(repo: RepoRef, commit_sha: str, path: str) -> str:
    quoted_path = urllib.parse.quote(path, safe="/")
    return f"https://github.com/{repo.owner}/{repo.name}/blob/{commit_sha}/{quoted_path}"


def decode_markdown(data: bytes) -> str | None:
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass

    text = data.decode("utf-8", errors="replace")
    replacement_ratio = text.count("\ufffd") / max(1, len(text))
    if replacement_ratio > 0.01:
        return None
    return text


def visible_markdown_text(text: str) -> str:
    text = HTML_COMMENT_RE.sub(" ", text)
    text = FENCED_CODE_RE.sub(" ", text)
    text = INLINE_CODE_RE.sub(" ", text)
    text = URL_RE.sub(" ", text)
    return text


def classify_language(
    text: str,
    *,
    min_chars: int,
    min_cjk_chars: int,
    min_cjk_ratio: float,
    min_en_words: int,
    min_latin_ratio: float,
) -> LanguageStats:
    visible = visible_markdown_text(text)
    compact_chars = [char for char in visible if not char.isspace()]
    text_chars = len(compact_chars)
    cjk_chars = len(CJK_RE.findall(visible))
    latin_words = len(LATIN_WORD_RE.findall(visible))
    latin_letters = len(LATIN_LETTER_RE.findall(visible))
    cjk_ratio = cjk_chars / max(1, text_chars)
    latin_ratio = latin_letters / max(1, text_chars)

    detected_lang = "unknown"
    if text_chars >= min_chars:
        is_zh = cjk_chars >= min_cjk_chars and cjk_ratio >= min_cjk_ratio
        is_en = latin_words >= min_en_words and latin_ratio >= min_latin_ratio
        if is_zh and is_en and cjk_ratio < 0.20:
            detected_lang = "mixed"
        elif is_zh:
            detected_lang = "zh"
        elif is_en and cjk_chars < max(10, min_cjk_chars // 2):
            detected_lang = "en"
        elif cjk_chars >= max(20, min_cjk_chars // 2) and latin_words >= min_en_words // 2:
            detected_lang = "mixed"

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return LanguageStats(
        detected_lang=detected_lang,
        text_chars=text_chars,
        cjk_chars=cjk_chars,
        cjk_ratio=round(cjk_ratio, 6),
        latin_words=latin_words,
        latin_ratio=round(latin_ratio, 6),
        sha256=digest,
    )


def safe_output_name(repo: RepoRef, blob: MarkdownBlob, content_hash: str) -> str:
    normalized_path = blob.path.replace("/", "__")
    normalized_path = re.sub(r"[^A-Za-z0-9._-]+", "_", normalized_path)
    prefix = f"{repo.owner}__{repo.name}__"
    suffix = f"__{blob.sha[:8]}__{content_hash[:12]}.md"
    max_path_len = 180 - len(prefix) - len(suffix)
    if len(normalized_path) > max_path_len:
        normalized_path = normalized_path[: max(20, max_path_len)]
    return f"{prefix}{normalized_path}{suffix}"


def write_markdown(
    output_dir: Path,
    lang: str,
    filename: str,
    text: str,
    overwrite: bool,
) -> Path:
    target_dir = output_dir / lang
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename
    if target.exists() and not overwrite:
        return target
    target.write_text(text, encoding="utf-8")
    return target


def load_seen_sources(metadata_path: Path) -> set[str]:
    if not metadata_path.exists():
        return set()

    seen: set[str] = set()
    with metadata_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            source_id = item.get("source_id")
            if source_id:
                seen.add(source_id)
    return seen


def append_metadata(metadata_path: Path, item: dict[str, Any]) -> None:
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with metadata_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def compile_patterns(values: list[str]) -> list[re.Pattern[str]]:
    patterns = []
    for value in values:
        try:
            patterns.append(re.compile(value))
        except re.error as exc:
            raise ValueError(f"invalid regex {value!r}: {exc}") from exc
    return patterns


def parse_langs(value: str) -> set[str]:
    langs = {part.strip() for part in value.split(",") if part.strip()}
    allowed = {"zh", "en", "mixed"}
    unknown = langs - allowed
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown language bucket(s): {', '.join(sorted(unknown))}"
        )
    if not langs:
        raise argparse.ArgumentTypeError("at least one language bucket is required")
    return langs


def unique_repos(repos: Iterable[RepoRef]) -> list[RepoRef]:
    result: list[RepoRef] = []
    seen: set[str] = set()
    for repo in repos:
        key = repo.full_name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(repo)
    return result


def collect_repositories(args: argparse.Namespace, client: GitHubClient) -> list[RepoRef]:
    repos: list[RepoRef] = []
    for value in args.repo:
        repos.append(parse_repo_ref(value))
    if args.repos_file:
        repos.extend(read_repo_file(args.repos_file))
    if args.query:
        repos.extend(search_repositories(client, args.query, args.max_repos_per_query))
    return unique_repos(repos)


def crawl_repo(
    client: GitHubClient,
    repo: RepoRef,
    args: argparse.Namespace,
    accepted_langs: set[str],
    seen_sources: set[str],
) -> tuple[int, int]:
    metadata = repo_metadata(client, repo)
    default_branch = metadata["default_branch"]
    commit_sha = default_branch_commit_sha(client, repo, default_branch)
    license_info = metadata.get("license") or {}
    blobs, truncated = markdown_blobs(
        client,
        repo,
        commit_sha,
        args.path_include_patterns,
        args.path_exclude_patterns,
    )

    if truncated:
        print(
            f"[warn] {repo.full_name}: git tree was truncated by GitHub; "
            "some files may be missing",
            file=sys.stderr,
        )
    print(
        f"[repo] {repo.full_name}: {len(blobs)} markdown candidates",
        file=sys.stderr,
    )

    saved = 0
    checked = 0
    for blob in blobs:
        if saved >= args.per_repo_limit:
            break
        if args.total_saved >= args.limit:
            break
        if blob.size > args.max_bytes:
            continue

        source_id = f"{repo.full_name}@{commit_sha}:{blob.path}"
        if source_id in seen_sources and not args.overwrite:
            continue

        checked += 1
        try:
            data = client.download_raw(raw_url(repo, commit_sha, blob.path), args.max_bytes)
        except GitHubError as exc:
            print(f"[skip] {repo.full_name}:{blob.path}: {exc}", file=sys.stderr)
            continue

        text = decode_markdown(data)
        if text is None:
            print(
                f"[skip] {repo.full_name}:{blob.path}: not valid UTF-8 markdown",
                file=sys.stderr,
            )
            continue

        stats = classify_language(
            text,
            min_chars=args.min_chars,
            min_cjk_chars=args.min_cjk_chars,
            min_cjk_ratio=args.min_cjk_ratio,
            min_en_words=args.min_en_words,
            min_latin_ratio=args.min_latin_ratio,
        )
        if stats.detected_lang not in accepted_langs:
            continue

        filename = safe_output_name(repo, blob, stats.sha256)
        local_path = args.output_dir / stats.detected_lang / filename
        if not args.dry_run:
            local_path = write_markdown(
                args.output_dir,
                stats.detected_lang,
                filename,
                text,
                args.overwrite,
            )
            append_metadata(
                args.metadata_path,
                {
                    "source_id": source_id,
                    "repo": repo.full_name,
                    "repo_description": metadata.get("description"),
                    "repo_stars": metadata.get("stargazers_count"),
                    "repo_fork": metadata.get("fork"),
                    "license_spdx": license_info.get("spdx_id"),
                    "license_name": license_info.get("name"),
                    "default_branch": default_branch,
                    "commit_sha": commit_sha,
                    "path": blob.path,
                    "blob_sha": blob.sha,
                    "size_bytes": len(data),
                    "detected_lang": stats.detected_lang,
                    "text_chars": stats.text_chars,
                    "cjk_chars": stats.cjk_chars,
                    "cjk_ratio": stats.cjk_ratio,
                    "latin_words": stats.latin_words,
                    "latin_ratio": stats.latin_ratio,
                    "sha256": stats.sha256,
                    "source_url": blob_url(repo, commit_sha, blob.path),
                    "raw_url": raw_url(repo, commit_sha, blob.path),
                    "local_path": str(local_path),
                },
            )
        seen_sources.add(source_id)
        saved += 1
        args.total_saved += 1
        print(
            f"[save] {stats.detected_lang} {repo.full_name}:{blob.path}",
            file=sys.stderr,
        )

    return saved, checked


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Crawl Markdown files from public GitHub repositories and split them "
            "into Chinese/English language buckets."
        )
    )
    source_group = parser.add_argument_group("sources")
    source_group.add_argument(
        "--repo",
        action="append",
        default=[],
        help="Repository in owner/name form or a GitHub URL. Repeatable.",
    )
    source_group.add_argument(
        "--repos-file",
        type=Path,
        help="Text file with one owner/name or GitHub repository URL per line.",
    )
    source_group.add_argument(
        "--query",
        action="append",
        default=[],
        help=(
            "GitHub repository search query, for example "
            "'中文 文档 stars:>100'. Repeatable."
        ),
    )
    source_group.add_argument(
        "--max-repos-per-query",
        type=int,
        default=10,
        help="Maximum repositories to collect for each --query.",
    )

    output_group = parser.add_argument_group("output")
    output_group.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/github_markdown"),
        help="Directory where zh/en/mixed folders and metadata are written.",
    )
    output_group.add_argument(
        "--metadata",
        type=Path,
        help="JSONL metadata path. Defaults to <output-dir>/metadata.jsonl.",
    )
    output_group.add_argument(
        "--langs",
        type=parse_langs,
        default=parse_langs("zh,en"),
        help="Comma-separated buckets to save: zh,en,mixed. Default: zh,en.",
    )
    output_group.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing local files and allow duplicate metadata rows.",
    )
    output_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Download and classify but do not write files.",
    )

    limit_group = parser.add_argument_group("limits")
    limit_group.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Maximum files to save across the whole run.",
    )
    limit_group.add_argument(
        "--per-repo-limit",
        type=int,
        default=30,
        help="Maximum files to save per repository.",
    )
    limit_group.add_argument(
        "--max-bytes",
        type=int,
        default=1_000_000,
        help="Skip Markdown files larger than this many bytes.",
    )
    limit_group.add_argument(
        "--path-include",
        action="append",
        default=[],
        help="Only include paths matching this regex. Repeatable.",
    )
    limit_group.add_argument(
        "--path-exclude",
        action="append",
        default=[],
        help="Exclude paths matching this regex. Repeatable.",
    )

    lang_group = parser.add_argument_group("language detection")
    lang_group.add_argument(
        "--min-chars",
        type=int,
        default=300,
        help="Minimum visible non-whitespace characters after removing code blocks.",
    )
    lang_group.add_argument(
        "--min-cjk-chars",
        type=int,
        default=80,
        help="Minimum CJK characters for Chinese classification.",
    )
    lang_group.add_argument(
        "--min-cjk-ratio",
        type=float,
        default=0.05,
        help="Minimum CJK character ratio for Chinese classification.",
    )
    lang_group.add_argument(
        "--min-en-words",
        type=int,
        default=80,
        help="Minimum Latin words for English classification.",
    )
    lang_group.add_argument(
        "--min-latin-ratio",
        type=float,
        default=0.30,
        help="Minimum Latin-letter ratio for English classification.",
    )

    github_group = parser.add_argument_group("github")
    github_group.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub token. Defaults to GITHUB_TOKEN environment variable.",
    )
    github_group.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        help="Seconds to sleep between HTTP requests.",
    )
    github_group.add_argument(
        "--max-rate-wait",
        type=int,
        default=300,
        help="Maximum seconds to wait automatically when GitHub rate limit is hit.",
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if not args.repo and not args.repos_file and not args.query:
        raise ValueError("provide at least one source: --repo, --repos-file, or --query")
    if args.limit <= 0:
        raise ValueError("--limit must be positive")
    if args.per_repo_limit <= 0:
        raise ValueError("--per-repo-limit must be positive")
    if args.max_repos_per_query <= 0:
        raise ValueError("--max-repos-per-query must be positive")
    if args.max_bytes <= 0:
        raise ValueError("--max-bytes must be positive")
    if args.sleep < 0:
        raise ValueError("--sleep cannot be negative")

    args.path_include_patterns = compile_patterns(args.path_include)
    args.path_exclude_patterns = compile_patterns(args.path_exclude)
    args.output_dir = args.output_dir.resolve()
    args.metadata_path = (
        args.metadata.resolve() if args.metadata else args.output_dir / "metadata.jsonl"
    )
    args.total_saved = 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        validate_args(args)
    except ValueError as exc:
        parser.error(str(exc))

    client = GitHubClient(
        token=args.token,
        sleep_seconds=args.sleep,
        max_rate_wait=args.max_rate_wait,
    )

    try:
        repos = collect_repositories(args, client)
    except (GitHubError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    if not repos:
        print("[error] no repositories found", file=sys.stderr)
        return 2

    seen_sources = set() if args.overwrite else load_seen_sources(args.metadata_path)
    print(
        f"[start] repos={len(repos)} limit={args.limit} "
        f"langs={','.join(sorted(args.langs))} output={args.output_dir}",
        file=sys.stderr,
    )

    total_checked = 0
    failed_repos = 0
    for repo in repos:
        if args.total_saved >= args.limit:
            break
        try:
            _, checked = crawl_repo(client, repo, args, args.langs, seen_sources)
            total_checked += checked
        except GitHubError as exc:
            failed_repos += 1
            print(f"[repo-skip] {repo.full_name}: {exc}", file=sys.stderr)
            continue

    print(
        f"[done] saved={args.total_saved} checked={total_checked} "
        f"failed_repos={failed_repos} metadata={args.metadata_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
