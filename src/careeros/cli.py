import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import uvicorn

from careeros.config import Settings
from careeros.main import create_app
from careeros.portfolio.sandbox import DockerSandboxRunner

MAC_DOCKER_EXECUTABLE = Path('/Applications/Docker.app/Contents/Resources/bin/docker')


def main():
    settings = Settings.from_env()
    if len(sys.argv) > 1 and sys.argv[1] == "sandbox":
        return sandbox_command(sys.argv[2:], settings)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, reload=False)


def sandbox_command(arguments: list[str], settings: Settings) -> int:
    parser = argparse.ArgumentParser(prog="careeros sandbox")
    parser.add_argument("action", choices=["check", "prepare"])
    args = parser.parse_args(arguments)
    docker_executable = shutil.which('docker') or (str(MAC_DOCKER_EXECUTABLE) if MAC_DOCKER_EXECUTABLE.is_file() else 'docker')
    runner = DockerSandboxRunner(image=settings.sandbox_image, docker_executable=docker_executable)
    if args.action == "check":
        available, message = runner.check_available()
        print(message)
        return 0 if available else 1
    dockerfile = Path(__file__).parent / "sandbox" / "Dockerfile"
    if not dockerfile.is_file():
        print("Sandbox Dockerfile is missing from this CareerOS checkout.")
        return 1
    try:
        completed = subprocess.run(
            [docker_executable, "build", "--tag", settings.sandbox_image, "--file", str(dockerfile), str(dockerfile.parent)],
            shell=False,
        )
    except FileNotFoundError:
        print("Docker was not found. Install and start Docker Desktop, then run `careeros sandbox prepare` again.")
        return 1
    except PermissionError:
        print("CareerOS cannot execute Docker. Check Docker Desktop and the Docker executable's file permissions.")
        return 1
    return completed.returncode
