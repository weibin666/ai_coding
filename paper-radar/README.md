# 论文雷达 Paper Radar

每日顶会论文推荐页面:自动从 arXiv 抓取最新论文,按「顶会接收标记 + 关键词相关度 + 新鲜度」打分排序,
覆盖 9 个领域(机器翻译 / 语音翻译 / ASR / TTS / 图像识别 / OCR / 大模型 / 机器翻译评测 / Agent),
**每天早上 06:00(Asia/Shanghai)自动更新**。

## 数据源说明

ACL、EMNLP、Interspeech、ICASSP、CVPR、NeurIPS 等顶会官网没有稳定的公开 API,而这些会议的论文
绝大多数会首发/同步到 arXiv,并在 comments 字段标注接收信息(如 "Accepted at ACL 2026")。
本系统以 **arXiv 官方 export API** 为统一数据源,抓取 cs.CL / cs.CV / cs.SD / eess.AS / cs.AI /
cs.LG / cs.MA 七个类别的最新提交,再通过顶会标记识别给予质量加分,实现"顶会优先"的排序效果。

## 快速启动

```bash
pip install -r requirements.txt
python app.py            # http://localhost:8000
```

首次启动若数据库为空,会自动在后台抓取首批论文(约 1–2 分钟,arXiv 限速 3 秒/请求)。
也可手动执行一次完整抓取:

```bash
python pipeline.py
```

## 生产部署

### 方式一:内置调度器(推荐,最简单)

调度器以后台线程运行在 Flask 进程内,因此 gunicorn 必须 **单 worker 多线程**:

```bash
gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 app:app
```

或 Docker:

```bash
docker build -t paper-radar .
docker run -d -p 8000:8000 -v $(pwd)/data:/app/data --name paper-radar paper-radar
```

### 方式二:系统 cron + 多 worker(高并发场景)

关闭内置调度器,由 cron 在每天 6 点触发更新,Web 层可任意扩 worker:

```bash
PR_ENABLE_SCHEDULER=0 PR_REFRESH_TOKEN=换成随机串 gunicorn -w 4 -b 0.0.0.0:8000 app:app
```

crontab(任选其一):

```cron
0 6 * * * cd /path/to/paper-radar && /usr/bin/python3 pipeline.py >> /var/log/paper-radar.log 2>&1
0 6 * * * curl -s -X POST -H "X-Refresh-Token: 换成随机串" http://127.0.0.1:8000/api/refresh
```

### Nginx 反代示例

```nginx
server {
    listen 80;
    server_name papers.example.com;
    location / { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; }
}
```

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `PR_DB_PATH` | `./data/papers.db` | SQLite 路径 |
| `PR_TIMEZONE` | `Asia/Shanghai` | 每日更新所用时区 |
| `PR_UPDATE_HOUR` / `PR_UPDATE_MINUTE` | `6` / `0` | 每日更新时刻 |
| `PR_FETCH_PER_CATEGORY` | `150` | 每个 arXiv 类别抓取条数 |
| `PR_RECENT_DAYS` | `7` | 只保留最近 N 天提交的论文 |
| `PR_TOP_K` | `20` | 每个领域每日最多收录篇数 |
| `PR_ENABLE_SCHEDULER` | `1` | 是否启用内置每日调度 |
| `PR_BOOTSTRAP_FETCH` | `1` | 空库启动时是否自动抓取 |
| `PR_REFRESH_TOKEN` | 空 | 配置后启用 `POST /api/refresh` 手动刷新接口 |
| `ANTHROPIC_API_KEY` | 空 | 配置后中文介绍改由 Claude 生成(失败自动回退规则式) |

## 接口

- `GET /` 推荐页面(领域标签筛选 + 站内搜索)
- `GET /api/papers?field=mt&q=关键词&date=2026-06-11&limit=100` 论文 JSON
- `GET /api/status` 最近更新时间与收录统计
- `POST /api/refresh`(头部 `X-Refresh-Token`)手动触发更新
- `GET /healthz` 健康检查

## 调整领域与关键词

全部领域定义集中在 `config.py` 的 `FIELDS`:每个领域包含强关键词(命中即归类)、
弱关键词(辅助加分)、排除词。新增领域只需加一项并写入 `FIELD_ORDER`,无需改其他代码。

## 自测

```bash
python test_e2e.py   # 32 项检查:解析 / 分类 / 打分 / 入库 / 路由 / 调度
```
