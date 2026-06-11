# -*- coding: utf-8 -*-
"""SQLite 存储层(标准库 sqlite3,WAL 模式,线程安全的短连接用法)。"""
import json
import logging
import os
import sqlite3
from contextlib import contextmanager

import config

log = logging.getLogger("paper-radar.storage")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    arxiv_id     TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    authors      TEXT NOT NULL,         -- JSON 数组
    abstract     TEXT NOT NULL,
    summary_zh   TEXT NOT NULL DEFAULT '',
    fields       TEXT NOT NULL,         -- JSON 数组
    score        REAL NOT NULL DEFAULT 0,
    venue        TEXT NOT NULL DEFAULT '',
    comment      TEXT NOT NULL DEFAULT '',
    published    TEXT NOT NULL,
    updated      TEXT NOT NULL,
    abs_url      TEXT NOT NULL,
    pdf_url      TEXT NOT NULL,
    fetched_date TEXT NOT NULL          -- 入库日期 YYYY-MM-DD
);
CREATE INDEX IF NOT EXISTS idx_papers_date  ON papers(fetched_date);
CREATE INDEX IF NOT EXISTS idx_papers_score ON papers(score DESC);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@contextmanager
def connect():
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.executescript(_SCHEMA)
    log.info("数据库初始化完成: %s", config.DB_PATH)


def upsert_papers(papers, fetched_date):
    """批量写入/更新论文。"""
    rows = [(
        p.arxiv_id, p.title, json.dumps(p.authors, ensure_ascii=False), p.abstract,
        p.summary_zh, json.dumps(p.fields), p.score, p.venue, p.comment,
        p.published, p.updated, p.abs_url, p.pdf_url, fetched_date,
    ) for p in papers]
    with connect() as conn:
        conn.executemany("""
            INSERT INTO papers (arxiv_id, title, authors, abstract, summary_zh, fields,
                                score, venue, comment, published, updated, abs_url, pdf_url, fetched_date)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(arxiv_id) DO UPDATE SET
                title=excluded.title, authors=excluded.authors, abstract=excluded.abstract,
                summary_zh=excluded.summary_zh, fields=excluded.fields, score=excluded.score,
                venue=excluded.venue, comment=excluded.comment, published=excluded.published,
                updated=excluded.updated, fetched_date=excluded.fetched_date
        """, rows)
    log.info("入库 %d 篇 (date=%s)", len(rows), fetched_date)


def _row_to_dict(row):
    d = dict(row)
    d["authors"] = json.loads(d["authors"])
    d["fields"] = json.loads(d["fields"])
    return d


def latest_date():
    with connect() as conn:
        row = conn.execute("SELECT MAX(fetched_date) AS d FROM papers").fetchone()
        return row["d"] if row and row["d"] else None


def query_papers(field=None, date=None, limit=200, search=None):
    """按领域 / 日期 / 关键词查询,按评分倒序。"""
    sql = "SELECT * FROM papers WHERE 1=1"
    args = []
    if date:
        sql += " AND fetched_date = ?"
        args.append(date)
    if field:
        sql += " AND fields LIKE ?"
        args.append('%"' + field + '"%')
    if search:
        sql += " AND (title LIKE ? OR abstract LIKE ?)"
        args += ["%" + search + "%"] * 2
    sql += " ORDER BY score DESC, published DESC LIMIT ?"
    args.append(limit)
    with connect() as conn:
        return [_row_to_dict(r) for r in conn.execute(sql, args).fetchall()]


def set_meta(key, value):
    with connect() as conn:
        conn.execute("INSERT INTO meta (key, value) VALUES (?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def get_meta(key, default=None):
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def stats():
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM papers").fetchone()["c"]
        today = latest_date()
        today_count = 0
        if today:
            today_count = conn.execute(
                "SELECT COUNT(*) AS c FROM papers WHERE fetched_date=?", (today,)).fetchone()["c"]
        return {"total": total, "latest_date": today, "latest_count": today_count,
                "last_update": get_meta("last_update")}
