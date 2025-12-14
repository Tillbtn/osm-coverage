FROM python:3.10-slim

# Install system dependencies for GDAL/Geopandas
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables for GDAL
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

# Workdir
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy scripts
COPY scripts/ scripts/
# Copy script runner
COPY run_updates.sh .
RUN chmod +x run_updates.sh

# Entrypoint
CMD ["./run_updates.sh"]
