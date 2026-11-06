# Static site plus the Python job that refreshes it.
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY src ./src
COPY README.md METHODOLOGY.md ./
COPY --from=web /web/dist /app/site
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV CAPITOL_SITE_DATA=/app/site/data
ENV CAPITOL_DATA_DIR=/app/data
EXPOSE 8080
CMD ["python", "-m", "capitol_gains", "serve", "--site", "/app/site", "--host", "0.0.0.0", "--port", "8080"]
