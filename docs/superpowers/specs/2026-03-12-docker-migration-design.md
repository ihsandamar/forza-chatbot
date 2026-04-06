# Docker Migration Design Spec

## Problem

PyInstaller-based build/deployment has 6 critical pain points:
1. **Build time**: 10-15 min full, 2-5 min incremental
2. **Runtime errors**: emoji encoding (cp1254), ChromaDB sqlite3 corruption, tiktoken path issues
3. **Spec maintenance**: 120+ hidden imports, manual data file management in `api_app.spec`
4. **Build output size**: ~500MB dist folder with duplicated DLLs
5. **Debugging difficulty**: frozen exe tracebacks are opaque, no shell access
6. **Fragility**: every new pip package may require spec file updates

## Solution

Replace PyInstaller with Docker containerization. Application runs as normal Python inside a Linux container. External configuration, secrets, and data are mounted as volumes — updatable without image rebuild.

## Target Environment

- Windows servers with Docker Desktop/Engine installed
- Team has server access and can run Docker commands
- MSSQL database accessible from container network

## Architecture

```
Host (Windows Server)                    Container (Linux)
─────────────────────                    ─────────────────
C:\chatbot-api\                          /app/
  ├── docker-compose.yml                   ├── api_app.py        (baked in image)
  ├── .env                  ── mount ──►   ├── .env
  ├── config\                              ├── config/
  │   └── config.yaml       ── mount ──►   │   └── config.yaml
  └── data\                                └── data/
      ├── forza.json         ── mount ──►      ├── forza.json
      ├── vector_store/      ── mount ──►      ├── vector_store/   (ChromaDB persist)
      └── vector_index/      ── mount ──►      └── vector_index/
```

### What's IN the image (immutable, changes with code):
- Python 3.11 runtime
- All pip dependencies (requirements.txt)
- Application source code (`src/`, `api_app.py`)
- System dependencies (ODBC driver for MSSQL)

### What's OUTSIDE the image (mutable, mounted as volumes):
- `.env` — API keys, database connection string, port config
- `config/config.yaml` — LLM settings, vector store config, feature flags
- `data/` — forza.json catalog, ChromaDB vector_store, vector_index

## File Structure

### New Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Container image definition |
| `docker-compose.yml` | Service orchestration with volume mounts |
| `.dockerignore` | Exclude build artifacts, venv, data from image context |
| `deploy/README.md` | Deployment guide for server setup |
| `.env.example` | Template with placeholder values for operators |

### Existing Files

| File | Change | Reason |
|------|--------|--------|
| `api_app.py` | None | Works as-is — frozen detection is a no-op in container |
| `src/**` | None | No changes — normal Python execution |
| `requirements.txt` | Add `uvicorn`, `fastapi` | Currently implicit transitive deps — must be explicit for Docker |
| `config/config.yaml` | Mounted at runtime |
| `build_api.bat` | Keep for backwards compatibility, not used in Docker flow |
| `api_app.spec` | Keep for backwards compatibility, not used in Docker flow |

## Dockerfile Design

Single-stage build. Compiler tools (`gcc`, `g++`) are kept through pip install (needed for C extensions like chroma-hnswlib) and purged afterward to reduce image size.

```dockerfile
FROM python:3.11-slim

# System dependencies: ODBC driver + build tools for C extensions
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
# NOTE: gcc/g++ still available here for C extension compilation
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    apt-get purge -y curl gnupg2 gcc g++ && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Application code layer (rebuilt on code changes)
COPY api_app.py .
COPY src/ src/

# Default empty directories (overridden by volume mounts)
RUN mkdir -p config data

# Runtime
ENV PYTHONUNBUFFERED=1
EXPOSE 8089

CMD ["python", "api_app.py"]
```

**Layer caching strategy:**
- System deps layer: rebuilt only when Dockerfile changes (~3 min)
- pip install layer: rebuilt only when requirements.txt changes (~2-3 min)
- Code layer: rebuilt on any src/ change (~5 sec)

**Important notes:**
- `WORKDIR /app` must stay aligned with `api_app.py`'s `os.chdir(application_path)` — both resolve to `/app` in container mode
- `sentence-transformers` pulls PyTorch (~2GB). Image size will be ~3-4GB, not ~1.5GB. Layer caching mitigates update pain.
- Consider using `--extra-index-url https://download.pytorch.org/whl/cpu` for CPU-only PyTorch to save ~1GB if GPU is not used

## docker-compose.yml Design

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

Notes:
- `config` mounted read-only (`:ro`) — app doesn't write config
- `data` mounted read-write — ChromaDB writes to `data/vector_store/`
- `.env` loaded two ways: `env_file` injects as env vars, file mount makes it available to `load_dotenv()` in `api_app.py`
- Health check uses Python stdlib (no curl needed in slim image)
- `start_period: 60s` allows embedding model preload time
- Log rotation configured (50MB x 5 files) to prevent unbounded disk growth

## .dockerignore Design

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

# Data (mounted as volumes)
data/
config/

# IDE and dev files
.git/
.idea/
.vscode/
*.pyc
*.pyo

# Documentation
docs/
tests/
*.md
```

## Operations Guide

### First Deployment
```powershell
# 1. Copy project files to server (via RDP, shared folder, or git clone)
# Place in C:\chatbot-api\: Dockerfile, docker-compose.yml, .dockerignore,
#   requirements.txt, api_app.py, src/

# 2. Create config and data directories on server
mkdir config, data
# Place config.yaml in config\, .env in root, forza.json + vector_index\ in data\

# 3. Build and start
docker compose up -d --build
docker compose logs -f
```

### Code Update (src/ changes)
```bash
docker compose build    # ~15-30 sec (only code layer rebuilds)
docker compose up -d    # ~5 sec restart
```

### Config/Env Update
```bash
# Edit .env or config/config.yaml on host
docker compose restart  # ~5 sec, no rebuild needed
```

### Data Update (forza.json, vector_store)
```bash
# Copy new forza.json to data/ on host
# Optionally delete data/vector_store/ to force re-creation
docker compose restart
```

### Debugging
```bash
docker compose logs -f                    # Stream logs
docker compose logs --tail 100            # Last 100 lines
docker exec -it chatbot-api bash          # Shell into container
docker exec -it chatbot-api python -c "import chromadb; print(chromadb.__version__)"
```

### Monitoring
```bash
docker compose ps       # Container status
docker compose top      # Running processes
# Health endpoint: http://server:8089/api/health
```

## Migration Checklist

1. Create Dockerfile, docker-compose.yml, .dockerignore
2. Test local build: `docker compose up --build`
3. Verify health endpoint responds
4. Verify routing works (vectorstore auto-init from mounted forza.json)
5. Verify report agent works (MSSQL connectivity from container)
6. Write deploy/README.md with server setup instructions
7. Keep build_api.bat and api_app.spec for fallback (do not delete)

## What This Does NOT Change

- Application source code (src/) — zero changes
- api_app.py — works as-is (frozen detection is harmless no-op)
- API endpoints, behavior, or state management
- LangGraph graph structure or node logic
- Database schema or queries
- Config file format
- .env file format

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| MSSQL connectivity from Linux container | ODBC driver 18 installed; connection string uses TCP/IP |
| ChromaDB Linux vs Windows sqlite3 | Fresh vector_store created in container — no migration needed |
| Image size (~3-4GB due to PyTorch) | Layer caching means code updates are ~5sec; consider CPU-only torch to save ~1GB |
| Docker learning curve | docker-compose abstracts complexity to 3 commands |
| Fallback if Docker fails | build_api.bat + api_app.spec preserved, can revert to PyInstaller |
