FROM python:3.10-slim 

WORKDIR /code

# 先複製 requirements.txt 利用 Docker 快取
COPY requirements.txt .

# 使用 --no-cache-dir 減少映像檔大小
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    # 清理 pip 快取
    rm -rf /root/.cache/pip

COPY ./app ./app

# 設定環境變數
ENV AUTH_SECRET_KEY=your-production-secret-key-2024
ENV COMPATIBILITY_MODE=true
ENV DEFAULT_ALLOWED_IPS=""
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 🆕 新增設備指紋相關環境變數
ENV FINGERPRINT_ENABLED=true
ENV FINGERPRINT_SIMILARITY_THRESHOLD=0.7
ENV HIGH_RISK_THRESHOLD=0.7
ENV MEDIUM_RISK_THRESHOLD=0.9

ENV WHITELIST_REQUIRED=false
# 建立非 root 使用者（安全性最佳實踐）
RUN useradd --create-home --shell /bin/bash app
USER app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]