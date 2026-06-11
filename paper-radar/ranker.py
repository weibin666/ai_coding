# -*- coding: utf-8 -*-
"""领域分类与质量评分。

评分 = 关键词相关度(标题权重 3 倍) + 顶会接收加分 + 新鲜度衰减。
分数归一化到 0–10,前端展示为"质量评分"。
"""
import math
import re
from datetime import datetime, timezone

import config

_VENUE_RE = re.compile(
    r"\b(" + "|".join(re.escape(v) for v in config.TOP_VENUES) + r")\b[\s'’]*((20)\d{2})?",
    re.IGNORECASE,
)
_ACCEPT_RE = re.compile(r"\b(accept|to appear|camera[- ]ready|published in|proceedings of|findings of)\b", re.IGNORECASE)


def _pad(text):
    """前后补空格,保证 ' nmt ' 这类边界关键词可命中。"""
    return " " + text.lower() + " "


def detect_venue(comment):
    """从 arXiv comments 中识别顶会接收信息,返回 (venue字符串, 是否明确接收)。"""
    if not comment:
        return "", False
    m = _VENUE_RE.search(comment)
    if not m:
        return "", False
    venue = m.group(1).upper()
    year = m.group(2) or ""
    accepted = bool(_ACCEPT_RE.search(comment))
    return (venue + (" " + year if year else "")).strip(), accepted


def classify(paper):
    """把论文归入一个或多个领域,返回 {field_key: 相关度原始分}。"""
    title = _pad(paper.title)
    abstract = _pad(paper.abstract)
    hits = {}
    for key, spec in config.FIELDS.items():
        if any(ex in title or ex in abstract for ex in (e.lower() for e in spec["exclude"])):
            # 排除词命中标题时直接跳过;命中摘要仅降权
            if any(ex in title for ex in (e.lower() for e in spec["exclude"])):
                continue
        score = 0.0
        for kw in spec["strong"]:
            k = kw.lower()
            if k in title:
                score += 3.0
            if k in abstract:
                score += 1.0
        for kw in spec["weak"]:
            k = kw.lower()
            if k in title:
                score += 0.8
            if k in abstract:
                score += 0.3
        # 必须至少命中一个强关键词才算属于该领域
        strong_hit = any(kw.lower() in title or kw.lower() in abstract for kw in spec["strong"])
        if strong_hit and score > 0:
            hits[key] = score
    return hits


def freshness(published_iso, now=None):
    """新鲜度 0–1,按天指数衰减(半衰期约 3 天)。"""
    try:
        dt = datetime.fromisoformat(published_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 0.5
    now = now or datetime.now(timezone.utc)
    days = max((now - dt).total_seconds() / 86400.0, 0.0)
    return math.exp(-days / 4.0)


def score_paper(paper, relevance_raw, now=None):
    """综合评分,归一化到 0–10。"""
    rel = min(relevance_raw / 12.0, 1.0)          # 相关度,封顶
    venue, accepted = detect_venue(paper.comment)
    venue_bonus = 0.0
    if venue:
        venue_bonus = 1.0 if accepted else 0.6
    fresh = freshness(paper.published, now=now)
    raw = rel * 5.0 + venue_bonus * 3.0 + fresh * 2.0
    paper.venue = venue
    return round(min(raw, 10.0), 2)


def rank(papers, now=None):
    """对论文做领域归类与打分,返回带 fields/score 的论文列表(过滤掉无领域命中的)。"""
    ranked = []
    for p in papers:
        hits = classify(p)
        if not hits:
            continue
        p.fields = sorted(hits, key=hits.get, reverse=True)
        p.score = score_paper(p, max(hits.values()), now=now)
        ranked.append(p)
    ranked.sort(key=lambda x: x.score, reverse=True)
    return ranked
