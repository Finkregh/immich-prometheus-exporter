FROM python:3.13-slim@sha256:32919c165487b858e003c8296c12920e8c94c243227f8546e23d4cc5aaa9e044

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
