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
