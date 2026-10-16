import subprocess

import pytest

from careeros import cli
from careeros.config import Settings


@pytest.mark.parametrize(('error', 'message'), [
    (FileNotFoundError('docker'), 'Docker was not found'),
    (PermissionError('docker'), 'CareerOS cannot execute Docker'),
])
def test_sandbox_prepare_explains_docker_launch_errors(tmp_path, monkeypatch, capsys, error, message):
    monkeypatch.setattr(cli, "__file__", str(tmp_path / "cli.py"))
    (tmp_path / "sandbox").mkdir()
    (tmp_path / "sandbox" / "Dockerfile").write_text("FROM scratch\n")

    def failed_docker(*args, **kwargs):
        raise error

    monkeypatch.setattr(cli.subprocess, "run", failed_docker)

    result = cli.sandbox_command(["prepare"], Settings())

    assert result == 1
    assert message in capsys.readouterr().out


def test_sandbox_uses_docker_desktop_when_cli_is_missing_from_path(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "__file__", str(tmp_path / "cli.py"))
    (tmp_path / "sandbox").mkdir()
    (tmp_path / "sandbox" / "Dockerfile").write_text("FROM scratch\n")
    docker = tmp_path / "Docker.app" / "Contents" / "Resources" / "bin" / "docker"
    docker.parent.mkdir(parents=True)
    docker.write_text("")
    docker.chmod(0o755)
    monkeypatch.setattr(cli, "MAC_DOCKER_EXECUTABLE", docker)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda argv, **kwargs: calls.append(argv) or subprocess.CompletedProcess(argv, 0))

    assert cli.sandbox_command(["prepare"], Settings()) == 0
    assert calls[0][0] == str(docker)
