# Docker Migration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PyInstaller build with Docker containerization so the app builds in seconds, runs reliably, and config/data can be updated without rebuilds.

**Architecture:** Single `Dockerfile` with layer-cached pip install, `docker-compose.yml` with volume mounts for `.env`, `config/`, and `data/`. No application code changes — existing `api_app.py` and `src/` work as-is.

**Tech Stack:** Docker, docker-compose, python:3.11-slim, msodbcsql18

**Spec:** `docs/superpowers/specs/2026-03-12-docker-migration-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `Dockerfile` | Container image: system deps, pip install, copy app code |
| Create | `docker-compose.yml` | Service definition: ports, volumes, healthcheck, logging |
| Create | `.dockerignore` | Exclude build artifacts, data, venv from Docker context |
| Create | `.env.example` | Template with placeholder values for operators |
| Create | `deploy/README.md` | Server deployment guide |
| Modify | `requirements.txt` | Add explicit `uvicorn` and `fastapi` deps |

---

## Chunk 1: Docker Infrastructure

### Task 1: Create .dockerignore

**Files:**
- Create: `.dockerignore`

- [ ] **Step 1: Create the .dockerignore file**

```
# Build artifacts (PyInstaller)
dist/
build/
*.spec
.build_cache

# Virtual environment
.venv/
venv/
__pycache__/

# Data (mounted as volumes, not baked into image)
data/
config/
.env

# IDE and dev files
.git/
.idea/
.vscode/
*.pyc
*.pyo

# Documentation and tests
docs/
tests/
*.md
hooks/
```

- [ ] **Step 2: Commit**

```bash
git add .dockerignore
git commit -m "chore: add .dockerignore for Docker build context"
```

---

### Task 2: Add explicit dependencies to requirements.txt

**Files:**
- Modify: `requirements.txt`

These are currently installed as transitive dependencies but must be explicit for a clean Docker `pip install`.

- [ ] **Step 1: Add uvicorn and fastapi to requirements.txt**

Add these lines to the `# Web Interfaces` section (after line 27):

```
uvicorn==0.34.3
fastapi==0.115.12
```

- [ ] **Step 2: Verify versions match current environment**

Run: `pip show uvicorn fastapi`

Check that versions match what's added. If different, use the installed versions.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add explicit uvicorn and fastapi to requirements.txt"
```

---

### Task 3: Create Dockerfile

**Files:**
- Create: `Dockerfile`

- [ ] **Step 1: Create the Dockerfile**

```dockerfile
FROM python:3.11-slim

# System dependencies: MSSQL ODBC driver + build tools for C extensions
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl gnupg2 unixodbc-dev gcc g++ && \
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y msodbcsql18 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies layer (cached unless requirements.txt changes)
# gcc/g++ still available for C extension compilation (chroma-hnswlib etc.)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    apt-get update && \
    apt-get purge -y curl gnupg2 gcc g++ && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Application code layer (rebuilt on code changes — fast ~5sec)
COPY api_app.py .
COPY src/ src/

# Default empty directories (overridden by volume mounts at runtime)
RUN mkdir -p config data

ENV PYTHONUNBUFFERED=1
EXPOSE 8089

CMD ["python", "api_app.py"]
```

- [ ] **Step 2: Commit**

```bash
git add Dockerfile
git commit -m "feat: add Dockerfile for containerized deployment"
```

---

### Task 4: Create docker-compose.yml

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Create docker-compose.yml**

```yaml
services:
  chatbot-api:
    build: .
    container_name: chatbot-api
    ports:
      - "${API_PORT:-8089}:8089"
    env_file:
      - .env
    volumes:
      - ./config:/app/config:ro
      - ./.env:/app/.env:ro
      - ./data:/app/data
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8089/api/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add docker-compose.yml with volume mounts and healthcheck"
```

---

### Task 5: Create .env.example

**Files:**
- Create: `.env.example`

- [ ] **Step 1: Create .env.example with placeholder values**

```
# Required: OpenAI API key for LLM and embeddings
OPENAI_API_KEY=sk-your-api-key-here

# Required: MSSQL connection string
# For Docker: use host.docker.internal instead of localhost/machine-name
DATABASE_URL=mssql+pyodbc://sa:password@host.docker.internal/dbname?driver=ODBC+Driver+18+for+SQL+Server

# Server configuration
HOST=0.0.0.0
PORT=8089
API_PORT=8089

# Logging
DEBUG=false
LOG_LEVEL=INFO

# LangSmith tracing (optional)
LANGSMITH_TRACING=false
LANGCHAIN_TRACING_V2=false
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=

# Background job isolation
BG_JOB_ISOLATED_LOOPS=true

# Forza API token (for routing parameter extraction)
FORZA_API_TOKEN=
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "chore: add .env.example template for Docker deployment"
```

---

## Chunk 2: Documentation and Validation

### Task 6: Create deployment guide

**Files:**
- Create: `deploy/README.md`

- [ ] **Step 1: Create deploy directory and README**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
mkdir -p deploy
git add deploy/README.md
git commit -m "docs: add Docker deployment guide"
```

---

### Task 7: Build and validate Docker image locally

This task has no code changes — it validates that everything works.

- [ ] **Step 1: Build the Docker image**

Run: `docker compose build`

Expected: Build completes without errors. Watch for:
- ODBC driver installation succeeds
- `pip install` completes (chroma-hnswlib compiles with gcc)
- No missing modules or import errors

- [ ] **Step 2: Start the container**

Run: `docker compose up -d`

Expected: Container starts and stays running.

Verify: `docker compose ps` shows status `Up` (not `Restarting`).

- [ ] **Step 3: Check startup logs**

Run: `docker compose logs`

Expected output includes:
```
[OK] Loaded environment from: /app/.env
[OK] Config file found: /app/config/config.yaml
[START] Starting Chatbot API Server
INFO:     Started server process
INFO:     Application startup complete.
```

No `UnicodeEncodeError` or `[WARNING] .env file not found` messages.

- [ ] **Step 4: Test health endpoint**

Run: `curl http://localhost:8089/api/health`

Expected: `{"success": true, "message": "API is running"}`

- [ ] **Step 5: Test healthcheck is passing**

Run: `docker inspect chatbot-api --format='{{.State.Health.Status}}'`

Expected: `healthy` (may need to wait up to 60s for start_period)

- [ ] **Step 6: Verify volume mounts**

Run: `docker exec chatbot-api ls -la /app/config/ /app/data/ /app/.env`

Expected: Shows `config.yaml`, `.env` file, and `data/` contents (forza.json etc.)

- [ ] **Step 7: Test container restart with config change**

Edit a comment in `.env` on host, then:

Run: `docker compose restart`

Run: `docker compose logs --tail 5`

Expected: Container restarts cleanly, picks up the same config.

- [ ] **Step 8: Commit final state (if any adjustments were needed)**

If any files were adjusted during validation:
```bash
git add -A
git commit -m "fix: adjustments from Docker validation testing"
```

---

## Impact Summary

### Before (PyInstaller):
| Metric | Value |
|--------|-------|
| Full build | 10-15 min |
| Incremental build | 2-5 min |
| Runtime errors | emoji encoding, ChromaDB corruption, tiktoken paths |
| New package added | Update api_app.spec hidden imports |
| Debugging | Opaque frozen tracebacks |
| Dist size | ~500MB |

### After (Docker):
| Metric | Value |
|--------|-------|
| First build | ~5-10 min (one-time) |
| Code change rebuild | ~15-30 sec |
| Config/data update | ~5 sec (restart only) |
| Runtime errors | None (Linux UTF-8, native Python) |
| New package added | Just `pip install` in requirements.txt |
| Debugging | `docker logs`, `docker exec bash` |
| Image size | ~3-4GB (layer cached) |
