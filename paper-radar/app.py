# -*- coding: utf-8 -*-
"""Paper Radar — 每日顶会论文推荐

启动方式:
  开发: python app.py
  生产: gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 app:app
        (调度器内置于进程,故 -w 1;多 worker 请用 cron 方案,见 README)
"""
import logging
import os
import threading

from flask import Flask, abort, jsonify, render_template, request

import config
import pipeline
import scheduler
import storage

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("paper-radar.app")

app = Flask(__name__)
_refresh_lock = threading.Lock()


def _bootstrap():
    """启动时初始化数据库;如库为空则后台先跑一次抓取;启动每日调度。"""
    storage.init_db()
    if os.environ.get("PR_ENABLE_SCHEDULER", "1") == "1":
        scheduler.start()
    if not storage.latest_date() and os.environ.get("PR_BOOTSTRAP_FETCH", "1") == "1":
        threading.Thread(target=_safe_update, name="bootstrap-fetch", daemon=True).start()


def _safe_update():
    if not _refresh_lock.acquire(blocking=False):
        log.info("已有更新任务在执行,跳过")
        return False
    try:
        pipeline.run_update()
        return True
    except Exception:
        log.exception("更新失败")
        return False
    finally:
        _refresh_lock.release()


# ---------------------------------------------------------------- 页面
@app.route("/")
def index():
    date = request.args.get("date") or storage.latest_date()
    papers = storage.query_papers(date=date) if date else []
    counts = {key: sum(1 for p in papers if key in p["fields"]) for key in config.FIELD_ORDER}
    return render_template(
        "index.html",
        papers=papers,
        fields=[(k, config.FIELDS[k]["name"]) for k in config.FIELD_ORDER],
        counts=counts,
        stats=storage.stats(),
        date=date,
        update_time="%02d:%02d" % (config.UPDATE_HOUR, config.UPDATE_MINUTE),
        timezone=config.TIMEZONE,
    )


# ---------------------------------------------------------------- API
@app.route("/api/papers")
def api_papers():
    field = request.args.get("field") or None
    if field and field not in config.FIELDS:
        abort(400, "未知领域: " + field)
    papers = storage.query_papers(
        field=field,
        date=request.args.get("date") or storage.latest_date(),
        search=request.args.get("q") or None,
        limit=min(int(request.args.get("limit", 200)), 500),
    )
    return jsonify({"count": len(papers), "papers": papers})


@app.route("/api/status")
def api_status():
    s = storage.stats()
    s["next_update"] = "每日 %02d:%02d %s" % (config.UPDATE_HOUR, config.UPDATE_MINUTE, config.TIMEZONE)
    return jsonify(s)


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """手动/外部 cron 触发更新。需配置 PR_REFRESH_TOKEN 并在请求头携带。"""
    if not config.REFRESH_TOKEN:
        abort(403, "未配置 PR_REFRESH_TOKEN,该接口已禁用")
    if request.headers.get("X-Refresh-Token") != config.REFRESH_TOKEN:
        abort(401, "token 无效")
    started = threading.Thread(target=_safe_update, daemon=True)
    started.start()
    return jsonify({"status": "started"}), 202


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


_bootstrap()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=False)
