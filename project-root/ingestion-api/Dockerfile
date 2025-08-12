FROM python:3.10

WORKDIR /code

# 複製 requirements.txt
COPY requirements.txt .

# 🏫 使用清華大學鏡像站
RUN pip install --no-cache-dir --upgrade pip \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
    --trusted-host pypi.tuna.tsinghua.edu.cn

# 安裝套件
RUN pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    -r requirements.txt

COPY ./app ./app

# 設定環境變數
ENV AUTH_SECRET_KEY=your-production-secret-key-2024
ENV COMPATIBILITY_MODE=true
ENV DEFAULT_ALLOWED_IPS=""
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 新增設備指紋相關環境變數
ENV FINGERPRINT_ENABLED=true
ENV FINGERPRINT_SIMILARITY_THRESHOLD=0.7
ENV HIGH_RISK_THRESHOLD=0.7
ENV MEDIUM_RISK_THRESHOLD=0.9
ENV WHITELIST_REQUIRED=false

# 建立非 root 使用者
RUN useradd --create-home --shell /bin/bash app
USER app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]