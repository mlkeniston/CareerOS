import argparse
import subprocess
import sys
from pathlib import Path

import uvicorn

from careeros.config import Settings
from careeros.main import create_app
from careeros.portfolio.sandbox import DockerSandboxRunner


def main():
    settings = Settings.from_env()
    if len(sys.argv) > 1 and sys.argv[1] == "sandbox":
        return sandbox_command(sys.argv[2:], settings)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, reload=False)


def sandbox_command(arguments: list[str], settings: Settings) -> int:
    parser = argparse.ArgumentParser(prog="careeros sandbox")
    parser.add_argument("action", choices=["check", "prepare"])
    args = parser.parse_args(arguments)
    runner = DockerSandboxRunner(image=settings.sandbox_image)
    if args.action == "check":
        available, message = runner.check_available()
        print(message)
        return 0 if available else 1
    dockerfile = Path(__file__).parent / "sandbox" / "Dockerfile"
    if not dockerfile.is_file():
        print("Sandbox Dockerfile is missing from this CareerOS checkout.")
        return 1
    completed = subprocess.run(
        ["docker", "build", "--tag", settings.sandbox_image, "--file", str(dockerfile), str(dockerfile.parent)],
        shell=False,
    )
    return completed.returncode
