FROM python:3.11-slim

WORKDIR /app

# System deps (minimal for sqlite + nba_api http calls)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install project in editable mode
COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir -e ".[dev]"

# Copy remaining files
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY .env.example .env

# Create data directories
RUN mkdir -p data/raw data/processed data/models

EXPOSE 8000

CMD ["uvicorn", "court_edge_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
