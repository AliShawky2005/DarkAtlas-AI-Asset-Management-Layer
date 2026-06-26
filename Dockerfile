FROM python:3.12-slim

WORKDIR /app

# Install system-level build tools.
# `asyncpg` is a C extension — it needs `gcc` and `libpq-dev` to compile.
# We clean up the apt cache immediately to keep the image small.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements FIRST — this is a Docker caching trick.
# Docker builds images in layers. If requirements.txt hasn't changed,
# Docker reuses the cached pip install layer and skips it on the next build.
# This makes rebuilds fast when you only change your Python code.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code.
COPY . .

EXPOSE 8000

# Production command (no --reload).
# docker-compose.yml overrides this with --reload for development.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
