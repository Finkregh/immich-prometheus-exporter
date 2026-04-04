FROM python:3.13-slim@sha256:739e7213785e88c0f702dcdc12c0973afcbd606dbf021a589cab77d6b00b579d

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

# Set default environment variables for export command
ENV IMMICHEXPORTER_EXPORT_URL=""
ENV IMMICHEXPORTER_EXPORT_API_KEY=""
ENV IMMICHEXPORTER_EXPORT_INTERVAL="60"
ENV IMMICHEXPORTER_EXPORT_LOG_LEVEL="INFO"

# Default command using the installed console script
# Environment variables will be automatically picked up by typer
CMD ["immich-prometheus-exporter", "export"]
