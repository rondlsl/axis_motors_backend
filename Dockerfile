FROM python:3.12

# Отключаем буферизацию Python для корректного вывода логов в Docker
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip3 install -r requirements.txt

COPY . .

CMD uvicorn main:app --host 0.0.0.0 --port 7138 --ws auto