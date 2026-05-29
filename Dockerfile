# ---- Stage 1: build the React frontend ----
FROM node:20-slim AS frontend
WORKDIR /app
# Install deps first (cached unless package files change).
COPY frontend/package*.json ./
RUN npm ci
# Build the app -> produces /app/dist (index.html + assets/).
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime (API + pipeline) ----
FROM python:3.12-slim
WORKDIR /app

# Python deps first (cached unless requirements change).
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Backend source.
COPY backend/ ./

# Frontend: the built SPA + the two standalone admin pages, all into ./static,
# which is where api.py looks (STATIC_DIR = backend/static).
COPY --from=frontend /app/dist/ ./static/
COPY frontend/static/review.html frontend/static/crawl.html ./static/

EXPOSE 8000

# Default command runs the API. The pipeline service overrides this in compose.
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
