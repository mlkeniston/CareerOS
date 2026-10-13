"""Fail-closed Docker runner for untrusted portfolio project checks."""
from __future__ import annotations

import os
import selectors
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
    def __init__(self, image: str = "careeros-sandbox:1", docker_executable: str = "docker", run=None):
        self.image = image
        self.docker_executable = docker_executable
        self._run = run or _bounded_subprocess_run

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
                limit_exceeded=bool(getattr(result, "output_limited", False) or result.returncode in {137, 143}),
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


def _bounded_subprocess_run(argv, *, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, shell=False):
    """Run Docker while retaining at most 64 KB for each output stream."""
    if shell or not capture_output:
        raise ValueError("Docker sandbox requires captured output and shell=False")
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    selector = selectors.DefaultSelector()
    streams = {process.stdout: bytearray(), process.stderr: bytearray()}
    for stream in streams:
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    expired = False
    output_limited = False
    while selector.get_map():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            expired = True
            if process.poll() is None:
                process.kill()
            remaining = 0.1
        events = selector.select(min(max(remaining, 0.01), 0.1))
        for key, _ in events:
            stream = key.fileobj
            try:
                chunk = os.read(stream.fileno(), 8192)
            except BlockingIOError:
                continue
            if not chunk:
                selector.unregister(stream)
                stream.close()
                continue
            buffer = streams[stream]
            if len(buffer) < MAX_OUTPUT:
                kept = chunk[: MAX_OUTPUT - len(buffer)]
                buffer.extend(kept)
                output_limited = output_limited or len(kept) < len(chunk)
            elif chunk:
                output_limited = True
        if process.poll() is not None and not events:
            # Keep draining until both descriptors reach EOF.
            continue
    return_code = process.wait()
    selector.close()
    # Streams are closed at EOF; the keys remain available on the map.
    values = list(streams.values())
    stdout, stderr = bytes(values[0]), bytes(values[1])
    if expired:
        raise subprocess.TimeoutExpired(argv, timeout, output=stdout, stderr=stderr)
    if text:
        stdout = stdout.decode("utf-8", errors="replace")
        stderr = stderr.decode("utf-8", errors="replace")
    completed = subprocess.CompletedProcess(argv, return_code, stdout=stdout, stderr=stderr)
    completed.output_limited = output_limited
    return completed
