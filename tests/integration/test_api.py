"""API end to end on synthetic files (TRD 10, FR-02, FR-11..14, TR-RV-01..04, TR-SEC-02/05/06).

Upload -> poll -> review -> SAFE -> download -> handoff, plus the 401/403/409/422 rules.
Runs in-process (no sockets: ``--disable-socket`` stays on).
"""

from __future__ import annotations

import io
import json
import logging
import secrets
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from cleargate.api.main import create_app
from cleargate.core.config import Settings, load_policy, load_settings
from tests import filegen
from tests.fixtures.manifest import SYNTHETIC, planted_items

TESS = load_settings({}).tesseract_cmd
# asyncio's event loop needs a loopback socket pair on Windows: loopback only, every other
# host stays blocked (TR-SEC-01; see test_outbound_connection_is_still_blocked).
pytestmark = [
    pytest.mark.skipif(not TESS, reason="Tesseract not installed"),
    pytest.mark.allow_hosts(["127.0.0.1", "::1"]),
]
SUB, REV = "sub-" + secrets.token_hex(8), "rev-" + secrets.token_hex(8)
TERMINAL = {"VALIDATED_SAFE", "BLOCKED", "FAILED", "REVIEW_REQUIRED"}


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    settings = Settings(
        data_dir=tmp_path_factory.mktemp("api"),
        vault_key=SecretStr(Fernet.generate_key().decode()),
        gate_key=SecretStr(secrets.token_urlsafe(32)),
        submitter_token=SecretStr(SUB),
        reviewer_token=SecretStr(REV),
        tesseract_cmd=TESS,
        ocr_workers=1,
    )
    app = create_app(settings, load_policy(), background=False, ui_dir=None)
    with TestClient(app) as c:
        yield c


def upload(client: TestClient, *files: tuple[str, bytes]) -> dict[str, Any]:
    r = client.post(
        "/api/v1/batches", headers=auth(SUB), files=[("files[]", (n, d)) for n, d in files]
    )
    assert r.status_code == 200, r.text
    return r.json()


def wait(client: TestClient, job_id: str, timeout: float = 240) -> dict[str, Any]:
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/v1/jobs/{job_id}", headers=auth(SUB)).json()
        if job["state"] in TERMINAL:
            return job
        time.sleep(0.5)
    raise AssertionError("job did not finish")


def docx_bytes(tmp: Path, text: str) -> bytes:
    return filegen.docx(tmp / "x.docx", text=text).read_bytes()


@pytest.fixture(scope="module")
def jobs(client: TestClient, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("files")
    batch = upload(
        client,
        ("refund.docx", docx_bytes(tmp, "Refund to SSN 900-12-3456 approved by the desk.")),
        ("planted.docx", (SYNTHETIC / "planted.docx").read_bytes()),
        ("wrong.pdf", docx_bytes(tmp, "not a pdf")),
    )
    ids = {j["filename"]: j["job_id"] for j in batch["jobs"]}
    assert [j["state"] for j in batch["jobs"]] == ["PROCESSING", "PROCESSING", "FAILED"]
    return {
        "batch": batch["batch_id"],
        "ids": ids,
        "final": {n: wait(client, i) for n, i in ids.items()},
    }


def test_health_is_public(client: TestClient) -> None:
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["vault_key_present"]
    assert body["tesseract_version"]


def test_tokens_and_roles(client: TestClient, jobs: dict[str, Any]) -> None:
    jid = jobs["ids"]["refund.docx"]
    assert client.get(f"/api/v1/jobs/{jid}").status_code == 401
    assert client.get(f"/api/v1/jobs/{jid}", headers=auth("wrong")).status_code == 401
    assert client.get(f"/api/v1/jobs/{jid}/review", headers=auth(SUB)).status_code == 403
    assert (
        client.get(f"/api/v1/jobs/{jid}/findings?include_text=true", headers=auth(SUB)).status_code
        == 403
    )
    r = client.post(f"/api/v1/jobs/{jid}/review", headers=auth(SUB), json={"decisions": []})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN_REVIEWER_REQUIRED"


def test_invalid_upload_fails_with_its_code(jobs: dict[str, Any]) -> None:
    job = jobs["final"]["wrong.pdf"]
    assert (job["state"], job["deciding_rule"], job["reason"]) == (
        "FAILED",
        "ingest",
        "EXTENSION_MISMATCH",
    )


def test_safe_job_downloads_report_and_handoff(client: TestClient, jobs: dict[str, Any]) -> None:
    jid = jobs["ids"]["refund.docx"]
    job = jobs["final"]["refund.docx"]
    assert (job["state"], job["deciding_rule"]) == ("VALIDATED_SAFE", "G7")
    assert job["counts_by_type"]["US_SSN"] == 1  # plus docProps author fields (PERSON)
    text = client.get(f"/api/v1/jobs/{jid}/artifacts/sanitized.txt", headers=auth(SUB)).text
    assert "[SSN]" in text
    assert "900-12-3456" not in text
    r = client.get(f"/api/v1/jobs/{jid}/artifacts/redacted.docx", headers=auth(SUB))
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert b"900-12-3456" not in zf.read("word/document.xml")
    assert (
        client.get(f"/api/v1/jobs/{jid}/artifacts/redacted.pdf", headers=auth(SUB)).status_code
        == 404
    )
    report = client.get(f"/api/v1/jobs/{jid}/report?format=json", headers=auth(SUB)).json()
    assert report["state"] == "VALIDATED_SAFE"
    assert report["verification"]["leak_hits"] == 0
    md = client.get(f"/api/v1/jobs/{jid}/report?format=md", headers=auth(SUB))
    assert md.headers["content-type"].startswith("text/markdown")
    assert "US_SSN" in md.text
    handoff = client.post(f"/api/v1/jobs/{jid}/handoff", headers=auth(SUB)).json()
    assert handoff["status"] == "completed"
    assert handoff["token_counts"] == {"SSN": 1}
    assert "900-12-3456" not in json.dumps(handoff)


def test_non_safe_job_refuses_outputs(client: TestClient, jobs: dict[str, Any]) -> None:
    jid = jobs["ids"]["planted.docx"]
    assert jobs["final"]["planted.docx"]["state"] == "REVIEW_REQUIRED"
    for name in ("sanitized.txt", "redacted.docx"):
        r = client.get(f"/api/v1/jobs/{jid}/artifacts/{name}", headers=auth(SUB))
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN_OUTPUT_UNVERIFIED"
    assert client.post(f"/api/v1/jobs/{jid}/handoff", headers=auth(SUB)).status_code == 409
    report = client.get(f"/api/v1/jobs/{jid}/report?format=md", headers=auth(SUB))
    assert report.status_code == 200  # reports are safe in every state


def test_reports_and_logs_never_carry_planted_values(
    client: TestClient, jobs: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    jid = jobs["ids"]["planted.docx"]
    body = client.get(f"/api/v1/jobs/{jid}/report?format=json", headers=auth(SUB)).text
    body += client.get(f"/api/v1/jobs/{jid}/report?format=md", headers=auth(SUB)).text
    body += client.get(f"/api/v1/jobs/{jid}", headers=auth(SUB)).text
    body += client.get(f"/api/v1/jobs/{jid}/findings", headers=auth(SUB)).text
    body += caplog.text
    for item in (i for i in planted_items() if i.file == "planted.docx"):
        assert item.value not in body, item.id


def test_review_path_reaches_safe(client: TestClient, jobs: dict[str, Any]) -> None:
    jid = jobs["ids"]["planted.docx"]
    items = client.get(f"/api/v1/jobs/{jid}/review", headers=auth(REV)).json()
    assert items, "the planted DOCX needs review"
    kinds = {i["kind"] for i in items}
    assert "finding" in kinds
    assert "region" in kinds
    region = next(i for i in items if i["kind"] == "region")
    assert region["thumbnail_data"].startswith("data:image/png;base64,")
    person = next(i for i in items if i["kind"] == "finding")
    assert person["segment_text"]  # reviewer sees the raw segment (TR-RV-01)
    bad = client.post(
        f"/api/v1/jobs/{jid}/review",
        headers=auth(REV),
        json={
            "decisions": [
                {"finding_id": region["finding_id"], "action": "reject", "justification": "x"}
            ]
        },
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "REJECT_FORBIDDEN"
    no_reason = client.post(
        f"/api/v1/jobs/{jid}/review",
        headers=auth(REV),
        json={"decisions": [{"finding_id": person["finding_id"], "action": "reject"}]},
    )
    assert no_reason.json()["error"]["code"] == "JUSTIFICATION_REQUIRED"
    decisions = [{"finding_id": i["finding_id"], "action": "confirm"} for i in items]
    r = client.post(f"/api/v1/jobs/{jid}/review", headers=auth(REV), json={"decisions": decisions})
    assert r.status_code == 200, r.text
    job = wait(client, jid)
    assert (job["state"], job["deciding_rule"]) == ("VALIDATED_SAFE", "G7")
    text = client.get(f"/api/v1/jobs/{jid}/artifacts/sanitized.txt", headers=auth(SUB)).text
    for item in (i for i in planted_items() if i.file == "planted.docx"):
        assert item.value not in text, item.id
    again = client.post(
        f"/api/v1/jobs/{jid}/review", headers=auth(REV), json={"decisions": decisions}
    )
    assert again.status_code == 409  # only in REVIEW_REQUIRED
    history = client.get(f"/api/v1/jobs/{jid}/report?format=json", headers=auth(SUB)).json()[
        "state_history"
    ]
    assert [h["to"] for h in history] == [
        "PROCESSING",
        "REVIEW_REQUIRED",
        "PROCESSING",
        "VALIDATED_SAFE",
    ]


def test_reviewer_can_reject_a_document(client: TestClient, tmp_path: Path) -> None:
    batch = upload(client, ("p.pptx", (SYNTHETIC / "planted.pptx").read_bytes()))
    jid = batch["jobs"][0]["job_id"]
    assert wait(client, jid)["state"] == "REVIEW_REQUIRED"
    r = client.post(
        f"/api/v1/jobs/{jid}/review",
        headers=auth(REV),
        json={"decisions": [{"action": "reject_document", "reason": "out of scope"}]},
    )
    assert r.status_code == 200
    job = client.get(f"/api/v1/jobs/{jid}", headers=auth(SUB)).json()
    assert (job["state"], job["deciding_rule"], job["reason"]) == (
        "BLOCKED",
        "review",
        "REVIEWER_REJECTED",
    )


def test_delete_batch(client: TestClient, tmp_path: Path) -> None:
    batch = upload(client, ("a.docx", docx_bytes(tmp_path, "Quarterly vendor review.")))
    jid = batch["jobs"][0]["job_id"]
    wait(client, jid)
    assert client.delete(f"/api/v1/batches/{batch['batch_id']}", headers=auth(SUB)).json()[
        "deleted"
    ]
    assert client.get(f"/api/v1/jobs/{jid}", headers=auth(SUB)).status_code == 404


def test_outbound_connection_is_still_blocked() -> None:
    import socket

    with pytest.raises(Exception, match=r"(?i)socket|host|allowed"):
        socket.create_connection(("192.0.2.1", 443), timeout=1)  # TEST-NET-1: never routable
