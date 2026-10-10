"""python -m mcp_db_server  ->  Streamable HTTP on $HOST:$PORT/mcp"""

import uvicorn

from .config import get_settings
from .server import build_app

if __name__ == "__main__":
    s = get_settings()
    uvicorn.run(build_app(), host=s.host, port=s.port, log_level="warning")
