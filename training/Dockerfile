FROM python:3.12-slim

FROM python:3.12-slim

WORKDIR /app

# instalar dependencias
COPY training/requirements.txt .
RUN pip install --no-cache-dir --timeout=180 -r requirements.txt

# copiar todo el repo
COPY . .
