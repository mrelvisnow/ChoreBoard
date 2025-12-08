# ChoreBoard Dockerfile
FROM python:3.11-slim

# Build arguments for metadata
ARG BUILD_DATE
ARG VERSION
ARG REVISION

# OCI Image metadata
LABEL org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.authors="ChoreBoard Contributors" \
      org.opencontainers.image.url="https://github.com/PhunkMaster/ChoreBoard" \
      org.opencontainers.image.documentation="https://github.com/PhunkMaster/ChoreBoard/blob/main/README.md" \
      org.opencontainers.image.source="https://github.com/PhunkMaster/ChoreBoard" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.vendor="ChoreBoard" \
      org.opencontainers.image.title="ChoreBoard" \
      org.opencontainers.image.description="A smart household chore management system that makes chores fair, fun, and rewarding"

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create directory for SQLite database with proper permissions
RUN mkdir -p /app/data && chmod 755 /app/data

# Copy entrypoint script and make it executable
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose port
EXPOSE 8000

# Run entrypoint script
ENTRYPOINT ["/entrypoint.sh"]

# Default command
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
