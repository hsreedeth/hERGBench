from pathlib import Path

import pytest

import hergbench.chemprop_runner as runner


def test_resolve_chemprop_python_from_absolute_shebang(tmp_path: Path) -> None:
    exe = tmp_path / "chemprop"
    exe.write_text("#!/opt/chemprop/bin/python3\nprint('noop')\n")

    assert runner._resolve_chemprop_python(str(exe)) == "/opt/chemprop/bin/python3"


def test_resolve_chemprop_python_from_env_shebang(tmp_path: Path, monkeypatch) -> None:
    exe = tmp_path / "chemprop"
    exe.write_text("#!/usr/bin/env python3\nprint('noop')\n")
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/local/bin/python3" if name == "python3" else None)

    assert runner._resolve_chemprop_python(str(exe)) == "/usr/local/bin/python3"


def test_chemprop_train_base_uses_patched_cli_for_prc_tracking(monkeypatch) -> None:
    fake_exe = "/tmp/fake-chemprop"
    monkeypatch.setattr(runner.shutil, "which", lambda name: fake_exe if name == "chemprop" else None)
    monkeypatch.setattr(runner, "_resolve_chemprop_python", lambda _: "/opt/chemprop/bin/python3")

    base = runner._chemprop_train_base("prc")

    assert base == ["/opt/chemprop/bin/python3", str(runner._PATCHED_CHEMPROP_CLI)]


def test_chemprop_train_base_uses_cli_for_auroc_tracking(monkeypatch) -> None:
    fake_exe = "/tmp/fake-chemprop"
    monkeypatch.setattr(runner.shutil, "which", lambda name: fake_exe if name == "chemprop" else None)

    base = runner._chemprop_train_base("auroc")

    assert base == [fake_exe]


def test_chemprop_cli_tracking_metric_maps_auroc_to_roc() -> None:
    assert runner._chemprop_cli_tracking_metric("auroc") == "roc"


def test_stream_chemprop_output_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("HERGBENCH_STREAM_CHEMPROP", raising=False)
    assert runner._stream_chemprop_output_enabled() is False


def test_stream_chemprop_output_enabled(monkeypatch) -> None:
    monkeypatch.setenv("HERGBENCH_STREAM_CHEMPROP", "1")
    assert runner._stream_chemprop_output_enabled() is True


def test_chemprop_train_base_rejects_unsupported_tracking_metric() -> None:
    with pytest.raises(ValueError, match="Supported values are 'auroc' and 'prc'"):
        runner._chemprop_train_base("roc")
