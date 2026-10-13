FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY conectores conectores
COPY simulador simulador
COPY sql sql
RUN useradd --no-create-home app
USER app
