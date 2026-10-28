# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md requirements.lock ./
COPY src ./src
RUN --mount=type=secret,id=build_ca_bundle \
    if [ -s /run/secrets/build_ca_bundle ]; then export PIP_CERT=/run/secrets/build_ca_bundle; fi; \
    python -m pip install --no-cache-dir -r requirements.lock && \
    python -m pip install --no-cache-dir --no-deps .
COPY config ./config
COPY assets ./assets
RUN useradd --create-home --uid 10001 engine && chown -R engine:engine /app
USER engine
ENTRYPOINT ["python", "-m", "incubrix_engine"]
CMD ["run", "--config", "config/production.json"]

