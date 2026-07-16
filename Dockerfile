# OMNIX POC API — FastAPI backend + YOLOv8/ByteTrack pipeline
#
# NOTE: This container runs the API and the detection pipeline (run_pipeline.py,
# launched as a subprocess by the API — see DEPLOY.md for details on that model).
# It does NOT include Ollama (the local LLM used for rule generation) — that
# needs its own container/host with GPU access. See DEPLOY.md.

FROM python:3.11-slim

# System deps needed by opencv-python and psycopg2-binary at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Ensure stdout/stderr aren't buffered, so logs appear immediately in `docker compose logs`
ENV PYTHONUNBUFFERED=1

# Install Python deps first so this layer is cached unless requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

# Copy the rest of the application
COPY . .

# Directories the app writes to at runtime (incidents/screenshots, pipeline state)
RUN mkdir -p incidents

EXPOSE 8000

CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]