FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# Create data directory for SQLite
RUN mkdir -p /app/data

# Set environment variable for database path
ENV DB_PATH=/app/data/gym.db

# Run the bot
CMD ["python", "-m", "src.bot"]
