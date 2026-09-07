FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY config.yaml .
COPY src/ src/

RUN pip install --no-cache-dir .

ENTRYPOINT ["python", "-m", "second_brain.main"]
