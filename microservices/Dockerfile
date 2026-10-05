FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy common library and service code
COPY common.py .
ARG SERVICE_DIR
COPY ${SERVICE_DIR}/ .

EXPOSE 8000

CMD ["python", "main.py"]
