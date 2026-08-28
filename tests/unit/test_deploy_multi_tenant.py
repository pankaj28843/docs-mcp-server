"""Deployment contracts for the private browser sidecar."""

from __future__ import annotations

from contextlib import nullcontext
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import deploy_multi_tenant as deploy


@pytest.mark.unit
def test_online_config_uses_private_browser_hostname(tmp_path: Path) -> None:
    source = tmp_path / "deployment.json"
    generated = tmp_path / "deployment.docker.json"
    source.write_text(
        json.dumps(
            {
                "infrastructure": {
                    "mcp_port": 8000,
                    "browser_cdp_endpoint": "http://127.0.0.1:9222",
                }
            }
        ),
        encoding="utf-8",
    )

    deploy.create_environment_config(source, generated, "online")

    assert json.loads(source.read_text(encoding="utf-8"))["infrastructure"]["browser_cdp_endpoint"] == (
        "http://127.0.0.1:9222"
    )
    assert json.loads(generated.read_text(encoding="utf-8"))["infrastructure"]["browser_cdp_endpoint"] == (
        "http://docs-mcp-browser:9222"
    )


@pytest.mark.unit
def test_browser_sidecar_is_private_pinned_and_health_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(deploy.subprocess, "run", run)

    deploy.run_browser_container("linux/amd64", "private-network")

    command = commands[0]
    assert deploy.BROWSER_IMAGE in command
    assert command[command.index("--network") + 1] == "private-network"
    assert command[command.index("--health-cmd") + 1] == deploy._BROWSER_HEALTH_COMMAND
    assert "webSocketDebuggerUrl" in deploy._BROWSER_HEALTH_COMMAND
    assert "-p" not in command
    assert "--publish" not in command


@pytest.mark.unit
def test_wait_for_browser_requires_healthy_state(monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter(
        [
            SimpleNamespace(returncode=0, stdout="starting\n"),
            SimpleNamespace(returncode=0, stdout="healthy\n"),
        ]
    )
    monkeypatch.setattr(deploy.subprocess, "run", lambda *_args, **_kwargs: next(results))
    monkeypatch.setattr(deploy.time, "sleep", lambda _seconds: None)

    deploy.wait_for_browser_container(timeout_seconds=1)


@pytest.mark.unit
def test_wait_for_application_requires_running_healthy_state(monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter(
        [
            SimpleNamespace(returncode=0, stdout="running starting\n"),
            SimpleNamespace(returncode=0, stdout="running healthy\n"),
        ]
    )
    monkeypatch.setattr(deploy.subprocess, "run", lambda *_args, **_kwargs: next(results))
    monkeypatch.setattr(deploy.time, "sleep", lambda _seconds: None)

    deploy.wait_for_application_container("app", timeout_seconds=1)


@pytest.mark.unit
def test_wait_for_port_release_retries_until_connection_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = iter([nullcontext(), OSError("connection refused")])

    def create_connection(*_args, **_kwargs):
        result = next(attempts)
        if isinstance(result, OSError):
            raise result
        return result

    monkeypatch.setattr(deploy.socket, "create_connection", create_connection)
    monkeypatch.setattr(deploy.time, "sleep", lambda _seconds: None)

    deploy.wait_for_port_release(42042, timeout_seconds=1)


@pytest.mark.unit
def test_wait_for_port_release_times_out_when_listener_remains(monkeypatch: pytest.MonkeyPatch) -> None:
    monotonic = iter([0.0, 0.0, 1.0])
    monkeypatch.setattr(deploy.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(deploy.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(deploy.socket, "create_connection", lambda *_args, **_kwargs: nullcontext())

    with pytest.raises(TimeoutError, match="Host port 42042"):
        deploy.wait_for_port_release(42042, timeout_seconds=0.5)


@pytest.mark.unit
def test_application_container_joins_network_without_browser_state_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "deployment.docker.json"
    config.write_text("{}", encoding="utf-8")
    commands: list[list[str]] = []
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command) or SimpleNamespace(returncode=0, stdout=""),
    )

    deploy.run_container(
        "app",
        8000,
        config,
        [],
        "online",
        "linux/amd64",
        "private-network",
    )

    command = commands[0]
    assert command[command.index("--network") + 1] == "private-network"
    mounts = [command[index + 1] for index, argument in enumerate(command) if argument == "-v"]
    assert mounts == [
        f"{config.resolve()}:/app/deployment.json:ro",
        f"{(Path(deploy.__file__).parent / 'config').resolve()}:/app/config:ro",
    ]
    assert not any("9222:" in argument for argument in command)
