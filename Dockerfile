# Python 3.11 slim
FROM python:3.11-slim

WORKDIR /app

# 依存関係をインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ソースコードをコピー
COPY . .

# Cloud Run 用ポート
ENV PORT=8080
EXPOSE 8080

# Bot を起動
CMD ["gunicorn", "main:app",
     "-b", ":8080",
     "--workers", "1",
     "--threads", "8",
     "--timeout", "120"]

