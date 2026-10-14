"""Microsoft Office opens the synthetic fixtures and their redacted outputs (FR-09, TR-RD-11).

Python parsers are more lenient than Word: a fixture text box without the anchor and
shape children Word requires parsed everywhere in the suite but did not open in Word.
This test drives the installed Word and PowerPoint through COM (PowerShell), read-only
and hidden. Opt-in (``-m e2e``); skipped where Office is not installed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from cleargate.core.config import load_policy, load_settings
from cleargate.core.db import MetaStore
from cleargate.pipeline import Pipeline
from tests.fixtures.manifest import SYNTHETIC
from tests.integration.test_redact_fixtures import make_settings

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.skipif(sys.platform != "win32", reason="Office COM is Windows only"),
    pytest.mark.skipif(not load_settings({}).tesseract_cmd, reason="Tesseract not installed"),
]

SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$path = '__PATH__'
if ($path.EndsWith('.docx')) {
  $app = New-Object -ComObject Word.Application
  $app.Visible = $false; $app.DisplayAlerts = 0
  try { $d = $app.Documents.Open($path, $false, $true, $false); $d.Close(0); 'OK' }
  catch { 'FAILED' }
} else {
  $app = New-Object -ComObject PowerPoint.Application
  try { $d = $app.Presentations.Open($path, -1, 0, 0); $d.Close(); 'OK' } catch { 'FAILED' }
}
$app.Quit()
"""


def office_available(progid: str) -> bool:
    r = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"[type]::GetTypeFromProgID('{progid}') -ne $null",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return r.stdout.strip() == "True"


def opens(path: Path) -> bool:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", SCRIPT.replace("__PATH__", str(path))],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    return r.stdout.strip().endswith("OK")


@pytest.mark.parametrize(
    ("name", "progid"),
    [("planted.docx", "Word.Application"), ("planted.pptx", "PowerPoint.Application")],
)
def test_fixture_and_redacted_output_open_in_office(name: str, progid: str, tmp_path: Path) -> None:
    if not office_available(progid):
        pytest.skip(f"{progid} not installed")
    assert opens(SYNTHETIC / name), f"Office rejects the fixture {name}"
    settings = make_settings(tmp_path)
    store = MetaStore.open(settings.data_dir / "meta.db")
    pipeline = Pipeline(settings, load_policy(), store)
    try:
        job = pipeline.process_batch([SYNTHETIC / name]).jobs[0]
    finally:
        pipeline.close()
        store.close()
    out = next((settings.data_dir / "jobs" / job.job_id / "out").glob("redacted.*"))
    assert opens(out), f"Office rejects the redacted {name}"
