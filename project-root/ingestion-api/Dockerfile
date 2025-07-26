FROM python:3.10

WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app ./app

# 設定環境變數
ENV AUTH_SECRET_KEY=your-production-secret-key
ENV COMPATIBILITY_MODE=true
ENV DEFAULT_ALLOWED_IPS=""

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]