# -*- coding: utf-8 -*-
"""每日定时更新调度器。

纯标准库实现(threading + zoneinfo),无 APScheduler 依赖:
后台守护线程计算到下一个 06:00(配置时区)的秒数,睡眠后执行 pipeline。
带异常隔离,单次更新失败不影响后续调度。

注意:若用 gunicorn 多 worker 部署,应只在一个进程内启动调度
(默认通过 PR_ENABLE_SCHEDULER=1 控制),或改用系统 cron 调用
`python pipeline.py` / POST /api/refresh。README 中有两种部署方式说明。
"""
import logging
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
import pipeline

log = logging.getLogger("paper-radar.scheduler")
_started = threading.Lock()
_thread = None


def seconds_until_next_run(now=None):
    tz = ZoneInfo(config.TIMEZONE)
    now = now or datetime.now(tz)
    target = now.replace(hour=config.UPDATE_HOUR, minute=config.UPDATE_MINUTE,
                         second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds(), target


def _loop():
    while True:
        wait, target = seconds_until_next_run()
        log.info("下次更新时间: %s(%.0f 秒后)", target.strftime("%Y-%m-%d %H:%M %Z"), wait)
        time.sleep(wait)
        try:
            pipeline.run_update()
        except Exception:
            log.exception("定时更新执行失败,等待下一周期")
        time.sleep(60)  # 防止边界抖动导致同一分钟重复触发


def start():
    """启动调度线程(幂等)。"""
    global _thread
    with _started:
        if _thread and _thread.is_alive():
            return _thread
        _thread = threading.Thread(target=_loop, name="daily-updater", daemon=True)
        _thread.start()
        log.info("每日 %02d:%02d (%s) 自动更新调度已启动",
                 config.UPDATE_HOUR, config.UPDATE_MINUTE, config.TIMEZONE)
        return _thread
