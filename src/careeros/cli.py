import uvicorn

from careeros.config import Settings
from careeros.main import create_app


def main():
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, reload=False)
