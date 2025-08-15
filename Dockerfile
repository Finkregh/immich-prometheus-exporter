FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Copy pyproject.toml and install the package
COPY pyproject.toml .
COPY src/ src/
COPY README.md .

# Install the package in editable mode
RUN --mount=type=cache,mode=777,id=pip_cache,target=/var/cache/pip \
    pip install --cache-dir=/var/cache/pip -e .

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

# Set default environment variables
ENV IMMICH_URL=""
ENV IMMICH_API_KEY=""
ENV IMMICH_INTERVAL="60"

# Default command using the installed console script
CMD ["immich-prometheus-exporter", "export", "--url", "${IMMICH_URL}", "--api-key", "${IMMICH_API_KEY}", "--interval", "${IMMICH_INTERVAL}"]
