# Use the official Python 3.10 image as a base
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APP_HOME=/app
ENV DATA_DIR=/app/data

# Set the working directory in the container
WORKDIR $APP_HOME
RUN mkdir -p $DATA_DIR

# Install system dependencies (if needed)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        fontconfig \
        gcc \
        pkg-config \
        libcairo2-dev \
        libgirepository1.0-dev \
    && rm -rf /var/lib/apt/lists/*  # Clean up to reduce image size

# Create fonts directory
RUN mkdir -p /usr/share/fonts/truetype/custom

# Copy your font files (replace with your font files)
COPY ./app/NotoSansTC-Regular.ttf /usr/share/fonts/truetype/custom/

# Update font cache
RUN fc-cache -f -v

ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

# Copy requirements file first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

EXPOSE 8080

# Command to run when the container starts (modify as needed)
# CMD ["python"]
CMD ["gunicorn", "-c", "gunicorn.py", "--bind", "0.0.0.0:8080", "main:app"]