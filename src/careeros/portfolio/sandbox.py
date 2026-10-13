"""Fail-closed Docker runner for untrusted portfolio project checks."""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT = 65_536
TIMEOUT_SECONDS = 75


@dataclass(slots=True)
class SandboxResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    limit_exceeded: bool = False
    available: bool = True
    error: str | None = None


class DockerSandboxRunner:
    def __init__(self, image: str = "careeros-sandbox:1", docker_executable: str = "docker", run=subprocess.run):
        self.image = image
        self.docker_executable = docker_executable
        self._run = run

    def check_available(self) -> tuple[bool, str]:
        try:
            daemon = self._run([self.docker_executable, "info"], capture_output=True, text=True, timeout=8, shell=False)
            if daemon.returncode != 0:
                return False, "Docker daemon is unavailable. Project QA remains on hold."
            image = self._run([self.docker_executable, "image", "inspect", self.image], capture_output=True, text=True, timeout=8, shell=False)
            if image.returncode != 0:
                return False, f"Sandbox image {self.image} is not installed. Run `careeros sandbox prepare`."
            probe = self._run(
                [self.docker_executable, "run", "--rm", "--network=none", "--read-only", "--cap-drop=ALL",
                 "--security-opt=no-new-privileges", "--pids-limit=16", "--memory=128m", "--memory-swap=128m",
                 "--cpus=1", "--user=10001:10001", self.image, "python3", "-c", "print('sandbox-ok')"],
                capture_output=True, text=True, timeout=12, shell=False,
            )
            if probe.returncode != 0:
                return False, "Docker sandbox probe failed. Project QA remains on hold."
            return True, "Docker sandbox is ready."
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired, OSError):
            return False, "Docker is unavailable. Project QA remains on hold."

    def run(self, project_dir: Path, manifest) -> SandboxResult:
        started = time.monotonic()
        try:
            root = Path(project_dir).resolve(strict=True)
            if not root.is_dir() or Path(project_dir).is_symlink():
                raise ValueError("Project staging path is unsafe")
            files = list(root.rglob("*"))
            for path in files:
                if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root) or not path.is_file() and not path.is_dir():
                    raise ValueError("Staged project contains an unsafe path")
            test_files = list(manifest.test_files)
            if not test_files:
                raise ValueError("Project manifest has no test files")
            for relative in test_files:
                if not isinstance(relative, str) or "\\" in relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
                    raise ValueError("Project manifest contains an unsafe test path")
                candidate = root.joinpath(*relative.split("/"))
                if candidate.is_symlink() or not candidate.resolve(strict=True).is_relative_to(root) or not candidate.is_file():
                    raise ValueError("Project test file is missing or unsafe")
            runtime = manifest.runtime
            if runtime == "python":
                command = ["python3", "-m", "unittest", "discover", "-s", "/workspace", "-p", "test*.py"]
            elif runtime == "node":
                command = ["node", "--test", *[f"/workspace/{p}" for p in test_files]]
            elif runtime == "static":
                command = ["python3", "-m", "compileall", "-q", "/workspace"]
            else:
                raise ValueError("Unsupported sandbox runtime")
            argv = [
                self.docker_executable, "run", "--rm", "--network=none", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--pids-limit=64", "--cpus=1", "--memory=512m",
                "--memory-swap=512m", "--user=10001:10001", "--mount", f"type=bind,src={root},dst=/workspace,readonly",
                "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m", self.image, *command,
            ]
            try:
                result = self._run(argv, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, shell=False)
            except subprocess.TimeoutExpired as exc:
                return SandboxResult(None, _text(exc.stdout)[:MAX_OUTPUT], _text(exc.stderr)[:MAX_OUTPUT],
                                     int((time.monotonic() - started) * 1000), timed_out=True)
            return SandboxResult(
                result.returncode, _text(result.stdout)[:MAX_OUTPUT], _text(result.stderr)[:MAX_OUTPUT],
                int((time.monotonic() - started) * 1000),
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            return SandboxResult(None, "", "", int((time.monotonic() - started) * 1000), available=False,
                                 error=f"Docker sandbox is unavailable: {exc}")
        except (ValueError, RuntimeError) as exc:
            return SandboxResult(None, "", "", int((time.monotonic() - started) * 1000), available=False,
                                 error=f"Docker sandbox rejected the project: {exc}")


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
