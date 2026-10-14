"""Processing report, JSON and Markdown, no raw values (FR-13, TR-SEC-02, ADR-11).

Built only from content-free sources: the ``jobs``, ``state_history``, ``findings`` (masked
previews, locators, tiers, evidence rule ids), ``runs`` (verification report, action
summary, timings, stage versions) and ``review_log`` tables, plus the coverage part of the
job state (locators and codes). Per FR-13: file name and type, state and deciding rule,
entity counts by type, locations, redaction actions, verification results, unresolved
items, durations, extraction warnings, the pages and images that used OCR (exercise
prompt 1), the policy hash and the stage versions.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from cleargate.core.db import MetaStore

REDACTING = ("auto_redact", "review")


def _loc_label(loc: dict[str, Any] | None) -> str:
    if not loc:
        return "-"
    parts = [loc.get("part", "?")]
    for key in ("page", "slide", "table", "row", "col", "paragraph_index"):
        if loc.get(key) is not None:
            parts.append(f"{key} {loc[key]}")
    return ", ".join(str(p) for p in parts)


def build_report(
    store: MetaStore, job_id: str, state: dict[str, Any] | None = None
) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        return {}
    rows = store.findings(job_id)
    run = store.run(job_id)
    verification = json.loads(run["report_json"]) if run else None
    actions = json.loads(run["actions_json"]) if run else []
    timings = json.loads(run["timings_json"]) if run else {}
    versions = json.loads(run["versions_json"]) if run else {}
    redacted = [r for r in rows if r["decision"] in REDACTING]
    by_type = Counter(r["entity_type"] for r in redacted)
    tiers = Counter(r["tier"] for r in redacted)
    decisions = Counter(r["decision"] for r in rows)
    locations = [
        {
            "finding_id": r["finding_id"],
            "entity_type": r["entity_type"],
            "tier": r["tier"],
            "decision": r["decision"],
            "preview": r["preview"],
            "token": r["token"],
            "location": _loc_label(json.loads(r["locator_json"]) if r["locator_json"] else None),
        }
        for r in rows
        if r["decision"] in REDACTING
    ]
    act = Counter((a["method"], "applied" if a["applied"] else "not_applied") for a in actions)
    issues: list[dict[str, Any]] = []
    ocr_pages: list[int] = []
    ocr_images: list[str] = []
    if state:
        cov = state.get("doc", {}).get("coverage", {})
        issues = [
            {"part": i["locator"]["part"], "page": i["locator"].get("page"), "code": i["code"]}
            for i in cov.get("issues", [])
        ]
        for seg in state.get("doc", {}).get("segments", []):
            if seg.get("method") == "ocr":
                loc = seg.get("locator", {})
                if loc.get("part") == "page" and loc.get("page"):
                    ocr_pages.append(int(loc["page"]))
                elif loc.get("image_ref"):
                    ocr_images.append(str(loc["image_ref"]))
    history = [
        {
            "from": h["from_state"],
            "to": h["to_state"],
            "rule": h["rule"],
            "reason": h["reason"],
            "at": h["created_at"],
        }
        for h in store.history(job_id)
    ]
    reviews = [
        {
            "finding_id": r["finding_id"],
            "action": r["action"],
            "reviewer": r["reviewer_id"],
            "at": r["created_at"],
        }
        for r in store.review_log(job_id)
    ]
    open_items = decisions.get("review", 0) if job["state"] == "REVIEW_REQUIRED" else 0
    return {
        "job_id": job_id,
        "filename": job["filename"],
        "format": job["fmt"],
        "state": job["state"],
        "gate_decision": job["rule"],
        "gate_reason": job["reason"],
        "policy_hash": job["policy_hash"],
        "summary": _summary(job["state"], sum(by_type.values()), verification),
        "entity_counts": dict(sorted(by_type.items())),
        "tier_counts": dict(sorted(tiers.items())),
        "decision_counts": dict(sorted(decisions.items())),
        "findings_count": len(redacted),
        "locations": locations,
        "actions": {f"{m}:{a}": n for (m, a), n in sorted(act.items())},
        "verification": verification,
        "unresolved_items": open_items,
        "ocr_pages": sorted(set(ocr_pages)),
        "ocr_images": sorted(set(ocr_images)),
        "extraction_warnings": issues,
        "warnings": (state or {}).get("warnings", []),
        "timings_s": timings,
        "stage_versions": versions,
        "state_history": history,
        "review_log": reviews,
        "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
    }


def _summary(state: str, redacted: int, verification: dict[str, Any] | None) -> str:
    if verification is None:
        return f"{state}: no verification report (the file did not reach verification)."
    return (
        f"{state}: {redacted} items redacted; verification found {verification['leak_hits']} "
        f"leaked values, {verification['residual_deterministic']} new identifiers, "
        f"{verification['uninspected_unmasked']} unread parts."
    )


def to_markdown(report: dict[str, Any]) -> str:
    v = report.get("verification") or {}
    lines = [
        f"# ClearGate processing report: {report['filename']}",
        "",
        f"- **State:** {report['state']} "
        f"(rule {report['gate_decision']}, `{report['gate_reason']}`)",
        f"- **Format:** {report['format']}",
        f"- **Policy hash:** `{report['policy_hash']}`",
        f"- **Summary:** {report['summary']}",
        "",
        "## Personal data found (counts)",
        "",
        "| Type | Count |",
        "|---|---:|",
        *[f"| {t} | {n} |" for t, n in report["entity_counts"].items()],
        "",
        f"Tiers: {json.dumps(report['tier_counts'])}. "
        f"Decisions: {json.dumps(report['decision_counts'])}.",
        "",
        "## Verification",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| V1 reopen | {v.get('reopen_ok', '-')} |",
        f"| V2 leaked values | {v.get('leak_hits', '-')} |",
        f"| V3 new identifiers / other | {v.get('residual_deterministic', '-')} / "
        f"{v.get('residual_other', '-')} |",
        f"| V4 unread parts / unit counts equal | {v.get('uninspected_unmasked', '-')} / "
        f"{v.get('unit_counts_equal', '-')} |",
        f"| V5 token consistency | {v.get('consistency_ok', '-')} |",
        f"| V6 SRS / CRS | {v.get('srs', '-')} / {v.get('crs', '-')} |",
        "",
        "## Redaction actions",
        "",
        *[f"- {k}: {n}" for k, n in report["actions"].items()],
        "",
        "## OCR",
        "",
        f"Pages read with OCR: {report['ocr_pages'] or 'none'}. "
        f"Images read with OCR: {len(report['ocr_images'])}.",
        "",
        "## Extraction warnings",
        "",
        *(
            [
                f"- {w['part']} (page {w['page']}): {w['code']}"
                for w in report["extraction_warnings"]
            ]
            or ["- none"]
        ),
        "",
        "## Locations",
        "",
        "| Type | Tier | Decision | Preview | Token | Location |",
        "|---|---|---|---|---|---|",
        *[
            f"| {x['entity_type']} | {x['tier']} | {x['decision']} | `{x['preview']}` | "
            f"{x['token'] or '-'} | {x['location']} |"
            for x in report["locations"][:500]
        ],
        "",
        "## State history",
        "",
        *[
            f"- {h['at']}: {h['from']} -> {h['to']} ({h['rule']}: {h['reason']})"
            for h in report["state_history"]
        ],
        "",
        f"Generated {report['generated_at']}. Counts, types, locations and masked previews only.",
    ]
    return "\n".join(lines) + "\n"


def digest(body: str) -> str:
    return hashlib.sha256(body.encode()).hexdigest()
