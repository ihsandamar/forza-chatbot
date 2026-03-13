FROM python:3.11-slim

# System dependencies: MSSQL ODBC drivers + build tools for C extensions
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl gnupg2 unixodbc-dev gcc g++ && \
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y msodbcsql17 msodbcsql18 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Layer 1: PyTorch CPU (~800MB) — rarely changes, cached separately
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Layer 2: Python dependencies — only this rebuilds when requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cleanup build tools (after all pip installs are done)
# Note: autoremove removes ODBC driver .so files as side effect, so we reinstall them
RUN apt-get update && \
    apt-get purge -y curl gnupg2 gcc g++ && \
    apt-get autoremove -y && \
    ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
        unixodbc libgssapi-krb5-2 msodbcsql17 msodbcsql18 && \
    rm -rf /var/lib/apt/lists/*

# Pre-download embedding model into image cache so runtime doesn't need internet
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# Application code layer (rebuilt on code changes — fast ~5sec)
COPY api_app.py .
COPY src/ src/

# Default empty directories (overridden by volume mounts at runtime)
RUN mkdir -p config data

ENV PYTHONUNBUFFERED=1
EXPOSE 8089

CMD ["python", "api_app.py"]
