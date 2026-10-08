# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=secret,id=local_ca \
    if [ -s /run/secrets/local_ca ]; then \
      python -c "import pip._vendor.certifi; from pathlib import Path; print(Path(pip._vendor.certifi.where()).read_text())" > /tmp/build-ca.pem && \
      cat /run/secrets/local_ca >> /tmp/build-ca.pem && \
      PIP_CERT=/tmp/build-ca.pem pip install --no-cache-dir -r requirements.txt && rm /tmp/build-ca.pem; \
    else pip install --no-cache-dir -r requirements.txt; fi
COPY service.py .
RUN useradd --create-home service
USER service
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
