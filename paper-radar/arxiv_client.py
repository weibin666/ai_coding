# -*- coding: utf-8 -*-
"""arXiv API 客户端。

使用官方 export API(Atom 格式),纯标准库 xml.etree 解析,
带重试与限速,遵守 arXiv 的 3 秒请求间隔建议。
"""
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import requests

import config

log = logging.getLogger("paper-radar.arxiv")

API_URL = "https://export.arxiv.org/api/query"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
HEADERS = {"User-Agent": "paper-radar/1.0 (daily paper recommendation; contact: admin@localhost)"}


@dataclass
class Paper:
    arxiv_id: str
    title: str
    authors: list
    abstract: str
    categories: list
    primary_category: str
    comment: str
    published: str   # ISO8601
    updated: str     # ISO8601
    abs_url: str
    pdf_url: str
    fields: list = field(default_factory=list)
    score: float = 0.0
    venue: str = ""
    summary_zh: str = ""


def _text(node, path):
    el = node.find(path, NS)
    return (el.text or "").strip() if el is not None and el.text else ""


def parse_atom(xml_text):
    """解析 arXiv Atom XML,返回 Paper 列表。"""
    papers = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log.error("Atom XML 解析失败: %s", e)
        return papers

    for entry in root.findall("atom:entry", NS):
        raw_id = _text(entry, "atom:id")           # http://arxiv.org/abs/2506.01234v1
        if "/abs/" not in raw_id:
            continue
        arxiv_id = raw_id.split("/abs/")[-1]
        arxiv_id = arxiv_id.rsplit("v", 1)[0] if "v" in arxiv_id.split("/")[-1] else arxiv_id

        title = " ".join(_text(entry, "atom:title").split())
        abstract = " ".join(_text(entry, "atom:summary").split())
        authors = [_text(a, "atom:name") for a in entry.findall("atom:author", NS)]
        categories = [c.get("term", "") for c in entry.findall("atom:category", NS)]
        primary = entry.find("arxiv:primary_category", NS)
        primary_cat = primary.get("term", "") if primary is not None else (categories[0] if categories else "")
        comment = _text(entry, "arxiv:comment")

        pdf_url = ""
        for link in entry.findall("atom:link", NS):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
        abs_url = "https://arxiv.org/abs/" + arxiv_id
        if not pdf_url:
            pdf_url = "https://arxiv.org/pdf/" + arxiv_id

        papers.append(Paper(
            arxiv_id=arxiv_id, title=title, authors=authors, abstract=abstract,
            categories=categories, primary_category=primary_cat, comment=comment,
            published=_text(entry, "atom:published"), updated=_text(entry, "atom:updated"),
            abs_url=abs_url, pdf_url=pdf_url,
        ))
    return papers


def fetch_category(category, max_results=None, retries=3):
    """抓取某 arXiv 类别下按提交时间倒序的最新论文。"""
    max_results = max_results or config.FETCH_PER_CATEGORY
    params = {
        "search_query": "cat:" + category,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            papers = parse_atom(resp.text)
            log.info("类别 %s 抓取到 %d 篇", category, len(papers))
            return papers
        except Exception as e:
            log.warning("抓取 %s 第 %d 次失败: %s", category, attempt, e)
            time.sleep(5 * attempt)
    log.error("类别 %s 抓取最终失败", category)
    return []


def fetch_all_categories():
    """遍历配置中的全部类别,按 arXiv 建议限速,合并去重。"""
    seen, merged = set(), []
    for i, cat in enumerate(config.ARXIV_CATEGORIES):
        if i > 0:
            time.sleep(config.ARXIV_DELAY)
        for p in fetch_category(cat):
            if p.arxiv_id not in seen:
                seen.add(p.arxiv_id)
                merged.append(p)
    log.info("全部类别合并去重后共 %d 篇", len(merged))
    return merged
