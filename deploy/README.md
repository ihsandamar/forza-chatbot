# Chatbot API - Docker Deployment Guide

## Prerequisites

- Docker Desktop or Docker Engine installed
- Access to MSSQL database from the server network
- OpenAI API key

## First-Time Setup

### 1. Copy project files to server

Copy these to your deployment directory (e.g., `C:\chatbot-api\`):
- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`
- `requirements.txt`
- `api_app.py`
- `src/` (entire directory)

### 2. Create configuration

```powershell
mkdir config
mkdir data
```

- Copy `config.yaml` into `config\`
- Copy `.env.example` to `.env` and fill in real values
- Copy `forza.json` into `data\`
- Copy `vector_index\` into `data\` (if pre-built indices exist)

**Important:** In `.env`, change the database host from machine name to `host.docker.internal`:
```
DATABASE_URL=mssql+pyodbc://sa:password@host.docker.internal/dbname?driver=ODBC+Driver+18+for+SQL+Server
```

### 3. Build and start

```powershell
docker compose up -d --build
```

First build takes ~5-10 minutes (downloads Python packages). Subsequent builds take ~15-30 seconds.

### 4. Verify

```powershell
# Check container is running
docker compose ps

# Check logs
docker compose logs -f

# Test health endpoint
curl http://localhost:8089/api/health
```

## Common Operations

### Update application code
```powershell
# After copying new src/ and api_app.py:
docker compose build
docker compose up -d
```

### Update configuration
```powershell
# After editing .env or config\config.yaml:
docker compose restart
```

### Update data (forza.json, vector store)
```powershell
# After copying new files to data\:
# Optionally delete data\vector_store\ to force re-creation
docker compose restart
```

### View logs
```powershell
docker compose logs -f              # Stream all logs
docker compose logs --tail 100      # Last 100 lines
```

### Debug inside container
```powershell
docker exec -it chatbot-api bash
```

### Stop
```powershell
docker compose down
```

### Full rebuild (clear cache)
```powershell
docker compose build --no-cache
docker compose up -d
```

## Troubleshooting

### Database connection fails
- Ensure MSSQL allows TCP/IP connections
- Use `host.docker.internal` as hostname (not `localhost` or machine name)
- Use ODBC Driver **18** (installed in container), not Driver 17

### Container keeps restarting
```powershell
docker compose logs --tail 50
```
Check for missing `.env` variables or `config.yaml` issues.

### ChromaDB vectorstore errors
```powershell
# Delete and let it auto-recreate from forza.json:
rmdir /S /Q data\vector_store
docker compose restart
```
