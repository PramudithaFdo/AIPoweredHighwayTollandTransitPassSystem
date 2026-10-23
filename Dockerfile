# ============================================================================
#  Dockerfile — AI-Powered Highway Toll & Transit Pass System
#  IT6070 – Emerging Topics in Information Technology
#  Production image: Python 3.11-slim + OpenCV + EasyOCR + Streamlit
# ============================================================================

FROM python:3.11-slim

LABEL maintainer="Pramuditha Fernando"
LABEL description="AI-Powered Highway Toll & Transit Pass System — IT6070 PoC"
LABEL version="1.0.0"

# Prevent interactive prompts during apt installs
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Streamlit settings
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_THEME_BASE=dark \
    # EasyOCR model cache
    EASYOCR_MODULE_PATH=/app/.easyocr \
    # App data
    DB_PATH=/app/data/toll_system.db

# Install OS-level dependencies needed by OpenCV + EasyOCR
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender-dev \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python packages directly (cached in Docker layer)
COPY requirements.txt .
RUN pip install --upgrade pip --quiet && \
    pip install --no-cache-dir -r requirements.txt

# Create directories for persistent data, models, logs, tests
RUN mkdir -p /app/data /app/.easyocr /app/test_images /app/logs /app/tests

# Copy application source and test suite
COPY app.py           .
COPY test_images/     ./test_images/
COPY tests/           ./tests/

# Non-root user for security
RUN useradd -m -u 1000 tolladmin && \
    chown -R tolladmin:tolladmin /app
USER tolladmin

# Expose Streamlit port
EXPOSE 8501

# Health check — Streamlit exposes a /_stcore/health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Entry point
CMD ["python3", "-m", "streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
