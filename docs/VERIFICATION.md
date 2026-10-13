# Verification matrix

Requirement ID to tests to status. Maintained every phase (brief section 4.6) and
checked by `scripts/check_matrix.py` (part of `make check`): every TR-/FR- ID in
the TRD and PRD, every gate rule G0..G7 and every verification check V1..V6 must
have a row, and every cited test must exist.

Status values:

- **PASS**: the requirement is fully covered by the cited, passing tests.
- **PARTIAL**: the cited tests pass and cover the part described in brackets; the rest is scheduled.
- **XFAIL**: a known limitation, kept as a strict `xfail` test with a reason.
- **TODO**: not implemented yet (target phase shown).

Last updated: Phase 1 (13 Oct 2026).

| ID | Requirement | Phase | Tests | Status |
|---|---|---|---|---|
| FR-01 | Ingestion and validation | 2 | - | TODO |
| FR-02 | Batch workflow, background progress | 8 | - | TODO |
| FR-03 | Structure-aware extraction, OCR fallback | 3 | - | TODO |
| FR-04 | Source traceability per finding | 3 | - | TODO |
| FR-05 | Layered detection | 4 | - | TODO |
| FR-06 | People vs business entities | 5 | - | TODO |
| FR-07 | Evidence tiers, calibrated routing | 5 | - | TODO |
| FR-08 | Typed tokens, batch-consistent pseudonyms | 6 | - | TODO |
| FR-09 | Secure redacted files, no overlays | 6 | - | TODO |
| FR-10 | Independent verification | 7 | - | TODO |
| FR-11 | Enforced privacy gate states (gate done; API 403/409 in Phase 8) | 1, 8 | `tests/unit/test_gate_machine.py::test_illegal_transition_raises_and_changes_nothing`<br>`tests/unit/test_db.py::test_direct_update_to_safe_from_processing_is_rejected` | PARTIAL |
| FR-12 | Human review and re-verify | 8 | - | TODO |
| FR-13 | Processing report without raw PII | 8 | - | TODO |
| FR-14 | AI handoff via SafeHandle (MockAgent) | 8 | - | TODO |
| FR-15 | Evaluation harness | 10 | - | TODO |
| FR-16 | Audit trail, policy hash per job (history and immutable hash; reports in Phase 8) | 1, 8 | `tests/unit/test_db.py::test_history_records_every_change_with_rule_reason_and_time`<br>`tests/unit/test_db.py::test_policy_hash_is_immutable` | PARTIAL |
| FR-17 | YAML policy configuration and hash (load, validate, hash; per-job recording in Phase 1) | 0 | `tests/unit/test_config.py::test_default_policy_loads`<br>`tests/unit/test_config.py::test_policy_hash_stable_across_key_reordering_in_yaml`<br>`tests/unit/test_config.py::test_invalid_policies_are_rejected` | PARTIAL |
| FR-18 | Standalone images | 3 | - | TODO |
| FR-19 | XLSX (MAY) | stretch | - | TODO |
| G0 | Exception, V1 fail, vault unavailable, missing verification, handle mint failure -> FAILED (rule logic; V-inputs arrive in Phase 7) | 1 | `tests/unit/test_gate_rules.py::test_each_rule_fires_alone`<br>`tests/unit/test_gate_rules.py::test_rule_ordering_first_match_wins`<br>`tests/unit/test_gate_machine.py::test_decide_without_sanitized_file_fails_closed` | PASS |
| G1 | V2 needle found -> BLOCKED (rule logic; V-inputs arrive in Phase 7) | 1 | `tests/unit/test_gate_rules.py::test_each_rule_fires_alone`<br>`tests/unit/test_gate_rules.py::test_rule_ordering_first_match_wins` | PASS |
| G2 | V3 new DETERMINISTIC -> BLOCKED (rule logic; V-inputs arrive in Phase 7) | 1 | `tests/unit/test_gate_rules.py::test_each_rule_fires_alone`<br>`tests/unit/test_gate_rules.py::test_rule_ordering_first_match_wins` | PASS |
| G3 | V4 uninspected part, unit counts, masked regions under block -> BLOCKED (rule logic; V-inputs arrive in Phase 7) | 1 | `tests/unit/test_gate_rules.py::test_each_rule_fires_alone`<br>`tests/unit/test_gate_rules.py::test_rule_ordering_first_match_wins` | PASS |
| G4 | Unapplied action -> BLOCKED (rule logic; V-inputs arrive in Phase 7) | 1 | `tests/unit/test_gate_rules.py::test_each_rule_fires_alone`<br>`tests/unit/test_gate_rules.py::test_rule_ordering_first_match_wins` | PASS |
| G5 | V5 failed -> BLOCKED (rule logic; V-inputs arrive in Phase 7) | 1 | `tests/unit/test_gate_rules.py::test_each_rule_fires_alone`<br>`tests/unit/test_gate_rules.py::test_rule_ordering_first_match_wins` | PASS |
| G6 | Open review item, masked regions, V3 other, SRS low or unmeasured -> REVIEW_REQUIRED (rule logic; V-inputs arrive in Phase 7) | 1 | `tests/unit/test_gate_rules.py::test_each_rule_fires_alone`<br>`tests/unit/test_gate_rules.py::test_rule_ordering_first_match_wins` | PASS |
| G7 | All pass -> VALIDATED_SAFE (rule logic; V-inputs arrive in Phase 7) | 1 | `tests/unit/test_gate_rules.py::test_safe_only_when_nothing_fires`<br>`tests/unit/test_gate_properties.py::test_safe_iff_no_rule_fires` | PASS |
| TR-DT-01 | Pre-split sub-spans before NER | 5 | - | TODO |
| TR-DT-02 | OCR text normalisation with offset map | 5 | - | TODO |
| TR-DT-10 | L1 deterministic recognizers + validators | 4 | - | TODO |
| TR-DT-11 | L2 label-anchored capture, column headers | 4 | - | TODO |
| TR-DT-12 | L2 OCR-confusion tolerance | 4 | - | TODO |
| TR-DT-13 | L3 Presidio + spaCy NER | 5 | - | TODO |
| TR-DT-14 | L4 context rules | 4-5 | - | TODO |
| TR-DT-15 | L5 registry and propagation | 5 | - | TODO |
| TR-DT-16 | Region findings (faces, unreadable) | 5 | - | TODO |
| TR-DT-30 | Calibration (k-fold) | 10 | - | TODO |
| TR-EX-01 | PDF native chars and image coverage | 3 | - | TODO |
| TR-EX-02 | PDF OCR routing rule | 3 | - | TODO |
| TR-EX-03 | OCR embedded images on native pages | 3 | - | TODO |
| TR-EX-04 | OCR 300 DPI, line segments, confidences | 3 | - | TODO |
| TR-EX-05 | Unreadable-region detection | 3 | - | TODO |
| TR-EX-06 | Face detection | 3 | - | TODO |
| TR-EX-07 | PDF metadata segments | 3 | - | TODO |
| TR-EX-08 | OCR cache key | 3 | - | TODO |
| TR-EX-10 | DOCX ordered body walk | 3 | - | TODO |
| TR-EX-11 | DOCX headers, notes, alt text, docProps | 3 | - | TODO |
| TR-EX-12 | DOCX image OCR, EMF/WMF/SVG | 3 | - | TODO |
| TR-EX-13 | DOCX heading level and lists | 3 | - | TODO |
| TR-EX-20 | PPTX recursive shapes, tables, notes | 3 | - | TODO |
| TR-EX-21 | PPTX picture OCR, logo de-duplication | 3 | - | TODO |
| TR-EX-22 | PPTX docProps | 3 | - | TODO |
| TR-EX-30 | Image EXIF and OCR path | 3 | - | TODO |
| TR-EX-40 | Coverage accounting | 3 | - | TODO |
| TR-GT-01 | Transition whitelist | 1 | `tests/unit/test_gate_machine.py::test_allowed_transition_succeeds`<br>`tests/unit/test_gate_machine.py::test_illegal_transition_raises_and_changes_nothing`<br>`tests/unit/test_gate_machine.py::test_whitelist_is_exactly_trd_gt_01`<br>`tests/unit/test_gate_properties.py::test_safe_iff_no_rule_fires` | PASS |
| TR-GT-02 | DB CHECK constraint and trigger (ticket per transaction, ADR-20) | 1 | `tests/unit/test_db.py::test_direct_update_from_received_is_rejected`<br>`tests/unit/test_db.py::test_direct_update_to_safe_from_processing_is_rejected`<br>`tests/unit/test_db.py::test_forged_history_row_without_ticket_is_rejected`<br>`tests/unit/test_db.py::test_ticket_must_point_at_newest_history_row`<br>`tests/unit/test_db.py::test_check_constraint_rejects_unknown_state`<br>`tests/unit/test_db.py::test_history_is_append_only` | PASS |
| TR-GT-03 | SafeHandle mint/verify, only via decide() (ADR-22) | 1 | `tests/unit/test_gate_handle.py::test_tampering_any_field_is_refused`<br>`tests/unit/test_gate_handle.py::test_sanitized_file_changed_on_disk_is_refused`<br>`tests/unit/test_gate_machine.py::test_decide_clean_input_mints_handle_and_is_safe`<br>`tests/unit/test_gate_machine.py::test_public_transition_can_never_enter_safe` | PASS |
| TR-GT-04 | Handoff verifies handle and hash (store checks done; AI call in Phase 8) | 1, 8 | `tests/unit/test_gate_handle.py::test_validly_signed_handle_for_non_safe_job_is_refused`<br>`tests/unit/test_gate_handle.py::test_handle_under_a_different_policy_is_refused`<br>`tests/unit/test_gate_handle.py::test_handle_not_issued_by_the_gate_is_refused` | PARTIAL |
| TR-GT-05 | MockAgent default, LLM needs approval (config rule only; MockAgent in Phase 8) | 0, 8 | `tests/unit/test_config.py::test_invalid_policies_are_rejected`<br>`tests/unit/test_config.py::test_llm_enabled_with_full_approval_is_accepted` | PARTIAL |
| TR-IN-01 | PDF detection | 2 | - | TODO |
| TR-IN-02 | DOCX detection | 2 | - | TODO |
| TR-IN-03 | PPTX detection | 2 | - | TODO |
| TR-IN-04 | PNG/JPEG/TIFF detection | 2 | - | TODO |
| TR-IN-05 | XLSX detection (MAY) | stretch | - | TODO |
| TR-IN-06 | Reject legacy, macro, encrypted | 2 | - | TODO |
| TR-PF-01 | DOCX/PPTX without images <= 15 s | 11 | - | TODO |
| TR-PF-02 | DOCX with screenshots <= 3 min | 11 | - | TODO |
| TR-PF-03 | Scanned PDF <= 20 s/page | 11 | - | TODO |
| TR-PF-04 | Progress at least every 5 s | 9 | - | TODO |
| TR-PF-05 | spaCy loaded once per worker | 5 | - | TODO |
| TR-RD-01 | Batch-scoped typed tokens | 6 | - | TODO |
| TR-RD-02 | Fernet vault, refuse start without key (key presence/format check only) | 0, 6 | `tests/unit/test_config.py::test_vault_key_validation` | PARTIAL |
| TR-RD-10 | DOCX/PPTX run-level writer | 6 | - | TODO |
| TR-RD-11 | OOXML integrity | 6 | - | TODO |
| TR-RD-20 | Scanned PDF raster burn-in | 6 | - | TODO |
| TR-RD-21 | Native PDF true redaction | 6 | - | TODO |
| TR-RD-30 | Sanitized text renderer | 6 | - | TODO |
| TR-RD-40 | Unapplied action blocks gate (G4 rule done; writers in Phase 6) | 1, 6 | `tests/unit/test_gate_rules.py::test_each_rule_fires_alone` | PARTIAL |
| TR-RV-01 | Review item contents | 8 | - | TODO |
| TR-RV-02 | Review actions, no reject of HIGH DETERMINISTIC | 8 | - | TODO |
| TR-RV-03 | Re-redact and re-verify after review | 8 | - | TODO |
| TR-RV-04 | Review log without raw values | 8 | - | TODO |
| TR-SEC-01 | No outbound network, socket-blocked tests (suite runs socket-blocked; pipeline run later) | 0, 11 | `tests/security/test_network.py::test_outbound_socket_is_blocked`<br>`tests/security/test_network.py::test_raw_socket_construction_is_blocked` | PARTIAL |
| TR-SEC-02 | Raw values only in memory and vault (models and errors; models, errors, meta.db findings; logs/reports in Phase 8) | 0, 8 | `tests/unit/test_models.py::test_segment_text_never_serialises`<br>`tests/unit/test_models.py::test_finding_value_never_serialises`<br>`tests/unit/test_models.py::test_property_any_text_is_absent_from_dumps`<br>`tests/unit/test_errors.py::test_content_like_details_are_redacted`<br>`tests/unit/test_db.py::test_findings_are_stored_without_raw_values` | PARTIAL |
| TR-SEC-03 | PiiSafeFilter and log grep (filter done; sample log grep later) | 0, 8 | `tests/unit/test_logging.py::test_record_with_active_needle_is_dropped`<br>`tests/unit/test_logging.py::test_exception_args_and_traceback_are_stripped` | PARTIAL |
| TR-SEC-04 | 0700 job dirs, O_EXCL, safe filenames | 2 | - | TODO |
| TR-SEC-05 | Server-side state enforcement on artifacts | 8 | - | TODO |
| TR-SEC-06 | TTL sweeper and batch delete (store-level delete done; sweeper and endpoint in Phase 8) | 1, 8 | `tests/unit/test_db.py::test_delete_batch_removes_jobs_history_and_findings` | PARTIAL |
| TR-SEC-07 | Parser hardening | 2, 11 | - | TODO |
| TR-SEC-08 | No original XObjects or thumbnails in output | 6 | - | TODO |
| TR-SEC-09 | Documented prototype limits | 11 | - | TODO |
| V1 | Output reopens via two parsers | 7 | - | TODO |
| V2 | Known-value leak check | 7 | - | TODO |
| V3 | Residual scan | 7 | - | TODO |
| V4 | Coverage | 7 | - | TODO |
| V5 | Overlap and consistency | 7 | - | TODO |
| V6 | Structure SRS/CRS | 7 | - | TODO |
