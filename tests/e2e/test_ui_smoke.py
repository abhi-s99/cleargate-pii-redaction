"""Browser smoke test of the React UI against the real API (brief Phase 9 exit, ADR-32).

Starts ``cleargate serve`` in-process on a free localhost port and drives Microsoft Edge
(installed with Windows; Playwright uses it via ``channel="msedge"``, no browser download)
through the happy path and the review path on a synthetic PPTX:

connect -> upload -> batch -> job (REVIEW_REQUIRED) -> review workspace -> confirm all ->
submit & re-verify -> VALIDATED_SAFE -> download the redacted file -> AI handoff (mock).

Screenshots (synthetic data only) are written to ``docs/img/``. Opt-in: ``-m e2e``.
"""

from __future__ import annotations

import secrets
import socket
import threading
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from cleargate.api.main import UI_DIST, create_app
from cleargate.core.config import REPO_ROOT, Settings, load_policy, load_settings
from tests.fixtures.manifest import SYNTHETIC, planted_items

playwright = pytest.importorskip("playwright.sync_api")
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
TESS = load_settings({}).tesseract_cmd
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.enable_socket,  # a real HTTP server and a real browser, both on localhost
    pytest.mark.skipif(not (UI_DIST / "index.html").is_file(), reason="UI not built (make ui)"),
    pytest.mark.skipif(not EDGE.is_file(), reason="Microsoft Edge not installed"),
    pytest.mark.skipif(not TESS, reason="Tesseract not installed"),
]
REVIEWER = "rev-" + secrets.token_hex(12)
IMG = REPO_ROOT / "docs" / "img"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    import uvicorn

    settings = Settings(
        data_dir=tmp_path_factory.mktemp("e2e"),
        vault_key=SecretStr(Fernet.generate_key().decode()),
        gate_key=SecretStr(secrets.token_urlsafe(32)),
        submitter_token=SecretStr("sub-" + secrets.token_hex(12)),
        reviewer_token=SecretStr(REVIEWER),
        tesseract_cmd=TESS,
        ocr_workers=1,
    )
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings, load_policy()), host="127.0.0.1", port=port, log_level="warning"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_upload_review_download_handoff(base_url: str, tmp_path: Path) -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 900}, accept_downloads=True)
        page.set_default_timeout(180_000)

        page.goto(f"{base_url}/connect")
        page.get_by_role("button", name="Privacy Reviewer").click()
        page.fill("#bearerToken", REVIEWER)
        page.check("#persistInTab")  # keep the token across the page loads below
        page.get_by_role("button", name="Connect & Authorize").click()

        page.goto(f"{base_url}/")
        page.set_input_files("input[type=file]", str(SYNTHETIC / "planted.pptx"))
        page.get_by_role("button", name="Process Batch").click()
        page.wait_for_url("**/batches/*")
        page.get_by_text("planted.pptx").first.click()
        page.wait_for_url("**/jobs/*")
        job_url = page.url

        page.get_by_text("Open Review Workspace").click()  # appears once REVIEW_REQUIRED
        page.wait_for_url("**/review")
        page.get_by_text("Confirm all remaining").wait_for()
        page.screenshot(path=str(IMG / "ui-review-workspace.png"), full_page=True)
        page.get_by_text("Confirm all remaining").click()
        page.get_by_role("button", name="Submit Decisions").click()
        page.get_by_role("button", name="Submit & Re-verify").click()
        page.wait_for_url(job_url)

        for _ in range(180):  # re-redaction and re-verification run in the background
            page.reload()
            page.wait_for_load_state("networkidle")
            if (
                page.get_by_text("Downloads").first.is_enabled()
                and page.locator("text=/validated safe/i").count()
            ):
                break
            time.sleep(1)
        page.get_by_text("Downloads").first.click()
        with page.expect_download() as dl:
            page.get_by_text("Download Redacted Document").click()
        out = tmp_path / "redacted.pptx"
        dl.value.save_as(out)
        with zipfile.ZipFile(out) as zf:
            xml = "\n".join(
                zf.read(n).decode("utf-8", "ignore") for n in zf.namelist() if n.endswith(".xml")
            )
        for item in (i for i in planted_items() if i.file == "planted.pptx" and i.channel != "ocr"):
            assert item.value not in xml, item.id

        page.get_by_text("AI Handoff").first.click()
        page.get_by_text("Send sanitized text to the AI agent (mock)").click()
        page.get_by_text("Personal data seen only as tokens").wait_for()
        page.screenshot(path=str(IMG / "ui-handoff.png"), full_page=True)
        browser.close()
