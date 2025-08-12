FROM python:3.10-slim

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

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100", "--reload"]