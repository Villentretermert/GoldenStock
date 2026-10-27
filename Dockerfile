FROM python:3.14.7-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock \
    && useradd --create-home --uid 10001 goldenstock \
    && mkdir -p /app/data && chown goldenstock:goldenstock /app/data
COPY pyproject.toml requirements.txt alembic.ini ./
COPY migrations ./migrations
COPY src ./src
USER goldenstock
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "goldenstock.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-proxy-headers"]
