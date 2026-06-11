# -*- coding: utf-8 -*-
"""每日更新 pipeline:抓取 → 过滤近期 → 分类打分 → 截取各领域 Top-K → 生成中文介绍 → 入库。

支持命令行手动执行:python pipeline.py
"""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import arxiv_client
import config
import ranker
import storage
import summarizer

log = logging.getLogger("paper-radar.pipeline")


def _is_recent(paper, now, days):
    try:
        dt = datetime.fromisoformat(paper.published.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    return now - dt <= timedelta(days=days)


def run_update(papers=None):
    """执行一次完整更新。papers 参数用于测试时注入 mock 数据。

    返回 (入库篇数, 抓取日期字符串)。
    """
    tz = ZoneInfo(config.TIMEZONE)
    now_utc = datetime.now(timezone.utc)
    fetched_date = datetime.now(tz).strftime("%Y-%m-%d")
    log.info("===== 开始更新 %s =====", fetched_date)

    storage.init_db()
    if papers is None:
        papers = arxiv_client.fetch_all_categories()
    if not papers:
        log.error("没有抓取到任何论文,本次更新跳过(保留昨日数据)")
        return 0, fetched_date

    recent = [p for p in papers if _is_recent(p, now_utc, config.RECENT_DAYS)]
    log.info("近 %d 天内的论文 %d / %d 篇", config.RECENT_DAYS, len(recent), len(papers))

    ranked = ranker.rank(recent, now=now_utc)
    log.info("命中目标领域的论文 %d 篇", len(ranked))

    # 每个领域取 Top-K(一篇论文可属于多个领域,去重保留)
    selected, seen = [], set()
    for field_key in config.FIELD_ORDER:
        in_field = [p for p in ranked if field_key in p.fields][:config.TOP_K_PER_FIELD]
        for p in in_field:
            if p.arxiv_id not in seen:
                seen.add(p.arxiv_id)
                selected.append(p)

    for p in selected:
        summarizer.summarize(p)

    storage.upsert_papers(selected, fetched_date)
    storage.set_meta("last_update", datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z"))
    log.info("===== 更新完成,入库 %d 篇 =====", len(selected))
    return len(selected), fetched_date


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    run_update()
