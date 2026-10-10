FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    # Bind all interfaces on Cloud Run. On 127.0.0.1 the MCP SDK turns on DNS-rebinding
    # protection and rejects the run.app Host header with 421.
    HOST=0.0.0.0
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY mcp_db_server ./mcp_db_server
COPY sql ./sql
RUN useradd --uid 10001 --no-create-home app
USER app
CMD ["python", "-m", "mcp_db_server"]
