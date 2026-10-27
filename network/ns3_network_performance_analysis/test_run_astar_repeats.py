import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from network.ns3_network_performance_analysis import run_astar_repeats


def test_runner_reports_missing_docker_cli(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_astar_repeats.py", "--runs", "101"])
    monkeypatch.setattr(run_astar_repeats.shutil, "which", lambda _: None)

    with pytest.raises(FileNotFoundError, match="Docker CLI not found"):
        run_astar_repeats.main()


def test_native_runner_copies_source_without_overwriting_changes(tmp_path, monkeypatch):
    source = tmp_path / "astar-multiclient.cc"
    source.write_text("scenario source", encoding="utf-8")
    scratch = tmp_path / "ns-3" / "scratch"
    scratch.mkdir(parents=True)
    target = scratch / source.name
    monkeypatch.setattr(run_astar_repeats, "SOURCE", source)

    run_astar_repeats.install_source(
        "unused", str(target), backend="native"
    )
    assert target.read_text(encoding="utf-8") == "scenario source"
    assert run_astar_repeats.remote_exists(
        "unused", str(target), backend="native"
    )

    target.write_text("another user's source", encoding="utf-8")
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        run_astar_repeats.install_source(
            "unused", str(target), backend="native"
        )


def test_native_ns3_command_runs_in_requested_installation(tmp_path, monkeypatch):
    calls = []

    def fake_run_command(command, *, capture=False, cwd=None):
        calls.append((command, capture, cwd))
        return SimpleNamespace(stdout="build output")

    monkeypatch.setattr(run_astar_repeats, "run_command", fake_run_command)

    result = run_astar_repeats.ns3_command(
        "unused",
        str(tmp_path),
        ["build", "scratch/astar-multiclient"],
        backend="native",
        capture=True,
    )

    assert result.stdout == "build output"
    assert calls == [
        (["./ns3", "build", "scratch/astar-multiclient"], True, str(tmp_path))
    ]
