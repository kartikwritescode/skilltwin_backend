FROM python:3.12-slim

# Set environment variables for Python in container
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    HOST=0.0.0.0

WORKDIR /app

# Install curl for healthchecks and container maintenance
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy backend application source code
COPY . .

# Expose Render standard container port
EXPOSE 10000

# Start server dynamically using Render's $PORT env variable (defaults to 10000)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
