FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PR_TIMEZONE=Asia/Shanghai PR_UPDATE_HOUR=6
EXPOSE 8000
# 内置调度器方案:单 worker 多线程
CMD ["gunicorn", "-w", "1", "--threads", "8", "-b", "0.0.0.0:8000", "--access-logfile", "-", "app:app"]
