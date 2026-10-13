import subprocess
from pathlib import Path

from careeros.portfolio.sandbox import DockerSandboxRunner


class Manifest:
    runtime = "python"
    test_files = ["tests/test_app.py"]


def test_runner_uses_a_locked_down_container_and_fixed_test_command(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_app.py").write_text("import unittest\n")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    runner = DockerSandboxRunner("careeros-sandbox:1", run=fake_run)
    result = runner.run(tmp_path, Manifest())

    assert result.available is True
    argv, kwargs = calls[0]
    assert "--network=none" in argv
    assert "--read-only" in argv
    assert "--cap-drop=ALL" in argv
    assert "--security-opt=no-new-privileges" in argv
    assert "--pids-limit=64" in argv
    assert "--memory=512m" in argv
    assert "--cpus=1" in argv
    assert "--user=10001:10001" in argv
    assert "python3" in argv and "-m" in argv and "unittest" in argv
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 75


def test_missing_docker_fails_closed_and_never_runs_host_code(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_app.py").write_text("import unittest\n")
    calls = []

    def unavailable(argv, **kwargs):
        calls.append(argv)
        raise FileNotFoundError("docker")

    runner = DockerSandboxRunner("careeros-sandbox:1", run=unavailable)
    result = runner.run(tmp_path, Manifest())
    assert result.available is False
    assert result.exit_code is None
    assert "sandbox" in result.error.lower()
    assert calls and calls[0][0] == "docker"


def test_check_available_requires_daemon_image_and_no_network_probe():
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    available, message = DockerSandboxRunner("careeros-sandbox:1", run=fake_run).check_available()
    assert available is True
    assert "ready" in message
    probe = calls[-1]
    assert "--network=none" in probe
    assert "--read-only" in probe
    assert "--cap-drop=ALL" in probe


def test_runner_rejects_symlinks_before_starting_container(tmp_path):
    outside = tmp_path.parent / "outside.py"
    outside.write_text("print('unsafe')")
    (tmp_path / "linked.py").symlink_to(outside)
    manifest = Manifest()
    manifest.test_files = ["linked.py"]
    calls = []
    runner = DockerSandboxRunner("careeros-sandbox:1", run=lambda *a, **k: calls.append(a))
    result = runner.run(tmp_path, manifest)
    assert result.available is False
    assert calls == []


def test_runner_caps_output_and_reports_timeout(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_app.py").write_text("import unittest\n")
    def timed_out(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=b"x" * 100_000, stderr=b"y" * 100_000)

    runner = DockerSandboxRunner("careeros-sandbox:1", run=timed_out)
    result = runner.run(tmp_path, Manifest())
    assert result.timed_out is True
    assert len(result.stdout) <= 65_536
    assert len(result.stderr) <= 65_536
