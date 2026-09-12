# Build the static UI, then run the whole app (FastAPI serves web/out) in one
# process. Works on Railway / Fly.io / Render / any Docker host.
FROM node:20-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY --from=web /web/out ./web/out
# NOTE: .env and checkmato.toml are deliberately NOT copied (gitignored secrets
# + local dev quotas). Set real values as platform env vars instead:
#   PORT (host assigns), CHECKMATO_CORS_ORIGINS, BRAVEX_API_KEY, AGNES_API_KEY…
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
