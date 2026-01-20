FROM python:3.12

# Устанавливаем системные зависимости для deepface/opencv и dlib (без X-сервера)
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libopenblas-dev \
    liblapack-dev \
    libx11-6 \
    libgl1 \
    libglib2.0-0 \
    postgresql-client \
 && rm -rf /var/lib/apt/lists/*

# Отключаем буферизацию Python для корректного вывода логов в Docker
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .

# Настраиваем pip для работы с таймаутами и retry
RUN pip3 install --upgrade pip
RUN pip3 install --timeout=1000 --retries=5 -r requirements.txt

COPY . .

CMD uvicorn main:app --host 0.0.0.0 --port 7138 --ws auto