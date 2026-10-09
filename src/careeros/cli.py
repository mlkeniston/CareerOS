import uvicorn

from careeros.config import Settings


def main():
    settings = Settings.from_env()
    uvicorn.run("careeros.main:app", host=settings.host, port=settings.port, reload=False)
