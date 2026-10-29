FROM python:3.12.14-slim-trixie@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements-prod.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements-prod.txt
COPY common.py .
ARG SERVICE
COPY services/${SERVICE}.py service.py
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
