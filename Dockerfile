# Multi-stage build for smaller final image
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final stage
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Create non-root user for security
RUN useradd -m -u 1000 botuser && \
    mkdir -p /app/tokens && \
    chown -R botuser:botuser /app

# Copy Python dependencies from builder
COPY --from=builder /root/.local /home/botuser/.local

# Copy application code
COPY --chown=botuser:botuser src/bot.py .
COPY --chown=botuser:botuser src/webhook_server.py .
COPY --chown=botuser:botuser src/config.py .
COPY --chown=botuser:botuser src/google_auth.py .
COPY --chown=botuser:botuser src/drive_handler.py .

# Switch to non-root user
USER botuser

# Make sure scripts in .local are usable
ENV PATH=/home/botuser/.local/bin:$PATH

# Expose webhook port
EXPOSE 8443

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8443/')"

# Run the webhook server
CMD ["python", "webhook_server.py"]
