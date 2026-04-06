# Use official Python lightweight image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system utilities (some dependencies might need compile tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Critical LLMOps Step:
# Pre-download the lightweight 12MB Spacy model into the Docker layer.
# This prevents it from downloading dynamically on every container start/scale.
RUN python -m spacy download en_core_web_sm

# Copy application files
COPY . .

# Expose ports for both the Gateway and the UI
EXPOSE 8000 8501

# Default command (will be overridden by docker-compose for the UI service)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
