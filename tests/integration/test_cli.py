"""Typer CLI: process, status, extract (brief Phase 2)."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from cleargate.cli import app
from tests import filegen

runner = CliRunner()


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    return {
        "CLEARGATE_VAULT_KEY": Fernet.generate_key().decode(),
        "CLEARGATE_GATE_KEY": secrets.token_urlsafe(32),
        "CLEARGATE_DATA_DIR": str(tmp_path / "data"),
    }


def test_process_prints_blocked_g3(tmp_path: Path, env: dict[str, str]) -> None:
    f = filegen.docx(tmp_path / "a.docx")
    result = runner.invoke(app, ["process", str(f)], env=env)
    assert result.exit_code == 0, result.output
    assert "BLOCKED" in result.output
    assert " G3 " in result.output


def test_process_json_and_status(tmp_path: Path, env: dict[str, str]) -> None:
    files = [str(filegen.docx(tmp_path / "a.docx")), str(filegen.pdf(tmp_path / "b.docx"))]
    result = runner.invoke(app, ["process", *files, "--json"], env=env)
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert [j["state"] for j in data["jobs"]] == ["BLOCKED", "FAILED"]
    assert data["jobs"][1]["reason"] == "EXTENSION_MISMATCH"
    status = runner.invoke(app, ["status", data["batch_id"]], env=env)
    assert status.exit_code == 0
    assert "RECEIVED -> PROCESSING" in status.output
    assert "RECEIVED -> FAILED" in status.output


def test_status_unknown_id(env: dict[str, str]) -> None:
    result = runner.invoke(app, ["status", "job-doesnotexist"], env=env)
    assert result.exit_code == 1


def test_process_refuses_without_keys(tmp_path: Path, env: dict[str, str]) -> None:
    env = {**env, "CLEARGATE_GATE_KEY": ""}
    result = runner.invoke(app, ["process", str(filegen.docx(tmp_path / "a.docx"))], env=env)
    assert result.exit_code == 2
    assert "KEY_MISSING" in result.output


def test_extract_dump_hides_text_by_default(tmp_path: Path, env: dict[str, str]) -> None:
    f = filegen.docx(tmp_path / "a.docx", text="Invented Person Quillon")
    result = runner.invoke(app, ["extract", str(f), "--dump"], env=env)
    assert result.exit_code == 0, result.output
    assert "coverage:" in result.output
    assert "Quillon" not in result.output


def test_extract_rejects_invalid_file(tmp_path: Path, env: dict[str, str]) -> None:
    f = filegen.docx(tmp_path / "a.pdf")
    result = runner.invoke(app, ["extract", str(f)], env=env)
    assert result.exit_code == 2
    assert "EXTENSION_MISMATCH" in result.output


def test_extract_dump_on_fixture_hides_planted_values(env: dict[str, str]) -> None:
    from tests.fixtures.manifest import SYNTHETIC, planted_items

    result = runner.invoke(app, ["extract", str(SYNTHETIC / "planted.pptx"), "--dump"], env=env)
    assert result.exit_code == 0, result.output
    assert '"slides": 3' in result.output
    assert not [
        i.value for i in planted_items() if i.file == "planted.pptx" and i.value in result.output
    ]
    shown = runner.invoke(app, ["extract", str(SYNTHETIC / "planted.pptx"), "--show-text"], env=env)
    assert "Anselm Kittredge" in shown.output
