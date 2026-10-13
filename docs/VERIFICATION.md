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

Last updated: Phase 5 (14 Oct 2026).

| ID | Requirement | Phase | Tests | Status |
|---|---|---|---|---|
| FR-01 | Ingestion and validation | 2 | `tests/integration/test_pipeline.py::test_invalid_input_ends_failed_with_specific_code`<br>`tests/unit/test_validator.py::test_samples_are_accepted` | PASS |
| FR-02 | Batch workflow, background progress | 8 | - | TODO |
| FR-03 | Structure-aware extraction (extraction done; report listing OCR pages in Phase 8) | 3, 8 | `tests/integration/test_extract_fixtures.py::test_planted_item_extracted_at_expected_locator`<br>`tests/integration/test_extract_samples.py::test_docx_structure_matches_profile` | PARTIAL |
| FR-04 | Source traceability (locators on every segment; report and review in Phase 8) | 3, 8 | `tests/integration/test_extract_fixtures.py::test_planted_item_extracted_at_expected_locator` | PARTIAL |
| FR-05 | Layered detection: L1 validators, L2 labels, L3 NER, L4 context, L5 registry | 4, 5 | `tests/integration/test_detect_fixtures.py::test_planted_item_detected_with_type_and_redacted`<br>`tests/unit/test_recognizers.py::test_label_anchored_positives`<br>`tests/unit/test_detect_context.py::test_three_names_in_one_cell_give_three_person_findings` | PASS |
| FR-06 | People vs business entities (allowlist suppresses NER-only terms; people in the same sentence redacted) | 5 | `tests/unit/test_detect_context.py::test_products_kept_while_people_in_same_sentence_are_redacted`<br>`tests/unit/test_detect_context.py::test_allowlist_term_that_is_a_registered_person_is_redacted`<br>`tests/integration/test_detect_fixtures.py::test_decoys_are_not_redacted` | PASS |
| FR-07 | Evidence tiers, threshold-driven routing (calibration itself is Phase 10, ADR-28) | 5, 10 | `tests/unit/test_merge.py::test_threshold_changes_routing`<br>`tests/unit/test_merge.py::test_tiers` | PARTIAL |
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
| FR-18 | Standalone images (extraction done; redaction in Phase 6) | 3, 6 | `tests/integration/test_extract_fixtures.py::test_coverage_is_complete` | PARTIAL |
| FR-19 | XLSX (MAY) | stretch | - | TODO |
| G0 | Exception, V1 fail, vault unavailable, missing verification, handle mint failure -> FAILED (rule logic; V-inputs arrive in Phase 7) | 1 | `tests/unit/test_gate_rules.py::test_each_rule_fires_alone`<br>`tests/unit/test_gate_rules.py::test_rule_ordering_first_match_wins`<br>`tests/unit/test_gate_machine.py::test_decide_without_sanitized_file_fails_closed`<br>`tests/integration/test_pipeline.py::test_crash_in_any_stage_ends_failed`<br>`tests/integration/test_pipeline.py::test_crash_in_gate_decision_ends_failed` | PASS |
| G1 | V2 needle found -> BLOCKED (rule logic; V-inputs arrive in Phase 7) | 1 | `tests/unit/test_gate_rules.py::test_each_rule_fires_alone`<br>`tests/unit/test_gate_rules.py::test_rule_ordering_first_match_wins` | PASS |
| G2 | V3 new DETERMINISTIC -> BLOCKED (rule logic; V-inputs arrive in Phase 7) | 1 | `tests/unit/test_gate_rules.py::test_each_rule_fires_alone`<br>`tests/unit/test_gate_rules.py::test_rule_ordering_first_match_wins` | PASS |
| G3 | V4 uninspected part, unit counts, masked regions under block -> BLOCKED (rule logic; V-inputs arrive in Phase 7) | 1 | `tests/unit/test_gate_rules.py::test_each_rule_fires_alone`<br>`tests/unit/test_gate_rules.py::test_rule_ordering_first_match_wins`<br>`tests/integration/test_pipeline.py::test_valid_file_ends_blocked_by_g3`<br>`tests/unit/test_gate_rules.py::test_partial_verifier_blocks_via_g3`<br>`tests/integration/test_extract_failclosed.py::test_ocr_disabled_scanned_pdf_ends_blocked_g3` | PASS |
| G4 | Unapplied action -> BLOCKED (rule logic; V-inputs arrive in Phase 7) | 1 | `tests/unit/test_gate_rules.py::test_each_rule_fires_alone`<br>`tests/unit/test_gate_rules.py::test_rule_ordering_first_match_wins` | PASS |
| G5 | V5 failed -> BLOCKED (rule logic; V-inputs arrive in Phase 7) | 1 | `tests/unit/test_gate_rules.py::test_each_rule_fires_alone`<br>`tests/unit/test_gate_rules.py::test_rule_ordering_first_match_wins` | PASS |
| G6 | Open review item, masked regions, V3 other, SRS low or unmeasured -> REVIEW_REQUIRED (rule logic; V-inputs arrive in Phase 7) | 1 | `tests/unit/test_gate_rules.py::test_each_rule_fires_alone`<br>`tests/unit/test_gate_rules.py::test_rule_ordering_first_match_wins` | PASS |
| G7 | All pass -> VALIDATED_SAFE (rule logic; V-inputs arrive in Phase 7) | 1 | `tests/unit/test_gate_rules.py::test_safe_only_when_nothing_fires`<br>`tests/unit/test_gate_properties.py::test_safe_iff_no_rule_fires` | PASS |
| TR-DT-01 | Pre-split sub-spans before NER | 5 | `tests/unit/test_detect_context.py::test_presplit_cell_offsets`<br>`tests/unit/test_detect_context.py::test_three_names_without_header_still_split` | PASS |
| TR-DT-02 | OCR text normalisation with offset map | 5 | `tests/unit/test_detect_context.py::test_ocr_normalisation_maps_back` | PASS |
| TR-DT-10 | L1 deterministic recognizers + validators (5+ positives, 5+ negatives, OCR-damaged cases each) | 4 | `tests/unit/test_recognizers.py::test_ssn_positives`<br>`tests/unit/test_recognizers.py::test_ssn_negatives`<br>`tests/unit/test_recognizers.py::test_business_pan_is_discarded_with_reason`<br>`tests/unit/test_recognizers.py::test_pesel_checksum_positives`<br>`tests/unit/test_recognizers.py::test_card_positives`<br>`tests/unit/test_recognizers.py::test_phone_negatives` | PASS |
| TR-DT-11 | L2 label-anchored capture, column headers and row labels | 4 | `tests/unit/test_recognizers.py::test_label_anchored_positives`<br>`tests/unit/test_recognizers.py::test_label_anchored_negatives`<br>`tests/unit/test_recognizers.py::test_column_header_applies_to_every_cell`<br>`tests/unit/test_recognizers.py::test_row_label_applies_to_value_cell` | PASS |
| TR-DT-12 | L2 OCR-confusion tolerance (OCR segments only, at most 2 substitutions) | 4 | `tests/unit/test_recognizers.py::test_ocr_confusion_repairs_value_on_ocr_segments`<br>`tests/unit/test_recognizers.py::test_ocr_confusion_not_applied_to_native_text`<br>`tests/unit/test_recognizers.py::test_ocr_confusion_limited_to_two_substitutions` | PASS |
| TR-DT-13 | L3 Presidio + spaCy NER (PERSON; ORG for allowlist learning; digit spans dropped) | 5 | `tests/unit/test_detect_context.py::test_incident_ids_are_not_people`<br>`tests/unit/test_detect_context.py::test_model_unavailable_fails_closed` | PASS |
| TR-DT-14 | L4 context rules: person labels and headers, honorifics, initials, partial financial, SSN last-4, home address | 4, 5 | `tests/unit/test_recognizers.py::test_partial_financial_positives`<br>`tests/unit/test_recognizers.py::test_ssn_last_four`<br>`tests/unit/test_recognizers.py::test_home_address_with_trigger`<br>`tests/unit/test_recognizers.py::test_corporate_addresses_are_kept`<br>`tests/unit/test_detect_context.py::test_two_common_word_name_under_created_by_is_corroborated`<br>`tests/unit/test_detect_context.py::test_honorific_led_by_and_label_names_are_caught` | PASS |
| TR-DT-15 | L5 registry, variants, propagation (exact, fuzzy OCR, unique surname), batch-wide person keys | 5 | `tests/unit/test_detect_context.py::test_canonical_key_and_variants`<br>`tests/unit/test_detect_context.py::test_fuzzy_ocr_match_and_native_exactness`<br>`tests/unit/test_detect_context.py::test_surname_only_rules`<br>`tests/unit/test_detect_context.py::test_initial_surname_header_is_linked_to_registered_person` | PASS |
| TR-DT-16 | Region findings (faces, unreadable) | 5 | `tests/unit/test_detect_context.py::test_region_findings`<br>`tests/integration/test_detect_fixtures.py::test_expected_regions_become_findings` | PASS |
| TR-DT-30 | Calibration (k-fold) | 10 | - | TODO |
| TR-EX-01 | PDF native chars and image coverage | 3 | `tests/integration/test_extract_fixtures.py::test_scanned_pdf_has_no_native_text_and_all_pages_ocr`<br>`tests/integration/test_extract_samples.py::test_pdf_is_fully_scanned_and_fig3_is_flagged` | PASS |
| TR-EX-02 | PDF OCR routing rule and native/OCR merge | 3 | `tests/integration/test_extract_fixtures.py::test_mixed_page_routes_to_ocr_and_drops_duplicate_ocr_lines`<br>`tests/integration/test_extract_fixtures.py::test_scanned_pdf_has_no_native_text_and_all_pages_ocr` | PASS |
| TR-EX-03 | OCR embedded images on native pages | 3 | `tests/integration/test_extract_fixtures.py::test_planted_item_extracted_at_expected_locator`<br>`tests/integration/test_extract_failclosed.py::test_ocr_disabled_native_pdf_with_image_ends_blocked` | PASS |
| TR-EX-04 | OCR 300 DPI, line segments, word confidences | 3 | `tests/integration/test_extract_fixtures.py::test_ocr_segments_carry_word_confidences`<br>`tests/unit/test_extract_units.py::test_parse_data_groups_lines_and_drops_empty_or_negative` | PASS |
| TR-EX-05 | Unreadable regions: low-confidence blocks and connected non-text regions (ADR-27) | 3 | `tests/unit/test_extract_units.py::test_unreadable_block_rules`<br>`tests/unit/test_extract_units.py::test_nontext_region_found_when_no_words_inside`<br>`tests/integration/test_extract_fixtures.py::test_illegible_region_is_not_read_as_text`<br>`tests/integration/test_extract_samples.py::test_pdf_is_fully_scanned_and_fig3_is_flagged` | PASS |
| TR-EX-06 | Face detection: Haar plus YuNet (ADR-27) | 3 | `tests/unit/test_extract_units.py::test_faces_found_on_public_domain_photo_not_on_text`<br>`tests/integration/test_extract_fixtures.py::test_expected_regions_are_found`<br>`tests/integration/test_extract_samples.py::test_pdf_is_fully_scanned_and_fig3_is_flagged` | PASS |
| TR-EX-07 | PDF Info and XMP metadata segments | 3 | `tests/integration/test_extract_fixtures.py::test_planted_item_extracted_at_expected_locator`<br>`tests/integration/test_extract_samples.py::test_pdf_is_fully_scanned_and_fig3_is_flagged` | PASS |
| TR-EX-08 | OCR cache key (raster sha + dpi + engine + parser version), encrypted at rest (ADR-26) | 3 | `tests/unit/test_extract_units.py::test_raster_key_depends_on_pixels_dpi_and_engine`<br>`tests/unit/test_extract_units.py::test_cache_key_includes_parser_version`<br>`tests/unit/test_extract_units.py::test_ocr_cache_is_encrypted_and_reused` | PASS |
| TR-EX-10 | DOCX ordered body walk, merged cells once, Fallback de-duplicated | 3 | `tests/integration/test_extract_fixtures.py::test_segments_are_in_reading_order`<br>`tests/integration/test_extract_fixtures.py::test_merged_cells_and_textbox_extracted_once`<br>`tests/integration/test_extract_fixtures.py::test_vmerge_continuation_cell_is_not_a_segment`<br>`tests/unit/test_extract_units.py::test_paragraph_text_includes_deleted_text_and_field_codes_but_not_fallback` | PASS |
| TR-EX-11 | DOCX headers, comments, alt text, docProps done; footnotes, endnotes and custom.xml parsed but not in fixtures | 3 | `tests/integration/test_extract_fixtures.py::test_planted_item_extracted_at_expected_locator`<br>`tests/integration/test_extract_samples.py::test_docx_structure_matches_profile`<br>`tests/unit/test_extract_units.py::test_author_attributes_are_collected_once` | PARTIAL |
| TR-EX-12 | DOCX image OCR with 2x upscale done, EMF rasterised on Windows; SVG text path untested | 3 | `tests/integration/test_extract_fixtures.py::test_planted_item_extracted_at_expected_locator`<br>`tests/integration/test_extract_failclosed.py::test_corrupt_image_part_in_docx_ends_blocked`<br>`tests/unit/test_extract_units.py::test_ink_ratio_and_prepare` | PARTIAL |
| TR-EX-13 | DOCX heading level and lists (incl. list styles) | 3 | `tests/integration/test_extract_fixtures.py::test_heading_level_and_list_membership` | PASS |
| TR-EX-20 | PPTX shapes, groups, tables, notes done; chart text untested | 3 | `tests/integration/test_extract_fixtures.py::test_planted_item_extracted_at_expected_locator`<br>`tests/integration/test_extract_samples.py::test_pptx_structure_matches_profile` | PARTIAL |
| TR-EX-21 | PPTX picture OCR, logo analysed once | 3 | `tests/integration/test_extract_fixtures.py::test_repeated_logo_is_analysed_once`<br>`tests/integration/test_extract_fixtures.py::test_expected_regions_are_found` | PASS |
| TR-EX-22 | PPTX docProps | 3 | `tests/integration/test_extract_fixtures.py::test_planted_item_extracted_at_expected_locator` | PASS |
| TR-EX-30 | Image EXIF metadata and OCR path (EXIF stripping is Phase 6) | 3, 6 | `tests/integration/test_extract_fixtures.py::test_planted_item_extracted_at_expected_locator` | PARTIAL |
| TR-EX-40 | Coverage accounting with a code per uninspected part (ADR-23) | 3 | `tests/integration/test_extract_fixtures.py::test_coverage_is_complete`<br>`tests/integration/test_extract_fixtures.py::test_pptx_printer_settings_binary_is_uninspected`<br>`tests/integration/test_extract_failclosed.py::test_ocr_disabled_scanned_pdf_ends_blocked_g3`<br>`tests/integration/test_extract_failclosed.py::test_xxe_in_document_part_is_uninspected` | PASS |
| TR-GT-01 | Transition whitelist | 1 | `tests/unit/test_gate_machine.py::test_allowed_transition_succeeds`<br>`tests/unit/test_gate_machine.py::test_illegal_transition_raises_and_changes_nothing`<br>`tests/unit/test_gate_machine.py::test_whitelist_is_exactly_trd_gt_01`<br>`tests/unit/test_gate_properties.py::test_safe_iff_no_rule_fires` | PASS |
| TR-GT-02 | DB CHECK constraint and trigger (ticket per transaction, ADR-20) | 1 | `tests/unit/test_db.py::test_direct_update_from_received_is_rejected`<br>`tests/unit/test_db.py::test_direct_update_to_safe_from_processing_is_rejected`<br>`tests/unit/test_db.py::test_forged_history_row_without_ticket_is_rejected`<br>`tests/unit/test_db.py::test_ticket_must_point_at_newest_history_row`<br>`tests/unit/test_db.py::test_check_constraint_rejects_unknown_state`<br>`tests/unit/test_db.py::test_history_is_append_only` | PASS |
| TR-GT-03 | SafeHandle mint/verify, only via decide() (ADR-22) | 1 | `tests/unit/test_gate_handle.py::test_tampering_any_field_is_refused`<br>`tests/unit/test_gate_handle.py::test_sanitized_file_changed_on_disk_is_refused`<br>`tests/unit/test_gate_machine.py::test_decide_clean_input_mints_handle_and_is_safe`<br>`tests/unit/test_gate_machine.py::test_public_transition_can_never_enter_safe` | PASS |
| TR-GT-04 | Handoff verifies handle and hash (store checks done; AI call in Phase 8) | 1, 8 | `tests/unit/test_gate_handle.py::test_validly_signed_handle_for_non_safe_job_is_refused`<br>`tests/unit/test_gate_handle.py::test_handle_under_a_different_policy_is_refused`<br>`tests/unit/test_gate_handle.py::test_handle_not_issued_by_the_gate_is_refused` | PARTIAL |
| TR-GT-05 | MockAgent default, LLM needs approval (config rule only; MockAgent in Phase 8) | 0, 8 | `tests/unit/test_config.py::test_invalid_policies_are_rejected`<br>`tests/unit/test_config.py::test_llm_enabled_with_full_approval_is_accepted` | PARTIAL |
| TR-IN-01 | PDF detection | 2 | `tests/unit/test_validator.py::test_valid_files_are_accepted`<br>`tests/unit/test_validator.py::test_extension_must_match_content`<br>`tests/unit/test_validator.py::test_corrupt_pdf` | PASS |
| TR-IN-02 | DOCX detection | 2 | `tests/unit/test_validator.py::test_valid_files_are_accepted`<br>`tests/unit/test_validator.py::test_extension_must_match_content` | PASS |
| TR-IN-03 | PPTX detection | 2 | `tests/unit/test_validator.py::test_valid_files_are_accepted`<br>`tests/unit/test_validator.py::test_extension_must_match_content` | PASS |
| TR-IN-04 | PNG/JPEG/TIFF detection | 2 | `tests/unit/test_validator.py::test_valid_files_are_accepted`<br>`tests/unit/test_validator.py::test_truncated_png`<br>`tests/unit/test_validator.py::test_image_too_large` | PASS |
| TR-IN-05 | XLSX (MAY): detected and rejected as unsupported; extraction is stretch | stretch | `tests/unit/test_validator.py::test_xlsx_is_not_supported_yet` | PARTIAL |
| TR-IN-06 | Reject legacy, macro, encrypted | 2 | `tests/unit/test_validator.py::test_unsupported_extensions`<br>`tests/unit/test_validator.py::test_legacy_ole_file_disguised_as_docx`<br>`tests/unit/test_validator.py::test_encrypted_pdf`<br>`tests/unit/test_validator.py::test_encrypted_ooxml_package`<br>`tests/unit/test_validator.py::test_macro_content_type_behind_docx_extension`<br>`tests/unit/test_validator.py::test_vba_project_part` | PASS |
| TR-PF-01 | DOCX/PPTX without images <= 15 s | 11 | - | TODO |
| TR-PF-02 | DOCX with screenshots <= 3 min | 11 | - | TODO |
| TR-PF-03 | Scanned PDF <= 20 s/page | 11 | - | TODO |
| TR-PF-04 | Progress at least every 5 s | 9 | - | TODO |
| TR-PF-05 | spaCy loaded once per process, shared by NER and the word list | 5 | `tests/unit/test_detect_context.py::test_spacy_model_loaded_once_per_process` | PASS |
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
| TR-SEC-04 | Restricted job dirs (0700 / Windows ACL, ADR-25), O_EXCL, safe filenames | 2 | `tests/unit/test_storage.py::test_job_dir_is_created_once_and_restricted`<br>`tests/unit/test_storage.py::test_upload_is_stored_as_original_with_o_excl`<br>`tests/unit/test_storage.py::test_display_names_are_sanitised`<br>`tests/integration/test_pipeline.py::test_upload_is_stored_under_job_dir_as_original` | PASS |
| TR-SEC-05 | Server-side state enforcement on artifacts | 8 | - | TODO |
| TR-SEC-06 | TTL sweeper and batch delete (store-level delete done; sweeper and endpoint in Phase 8) | 1, 8 | `tests/unit/test_db.py::test_delete_batch_removes_jobs_history_and_findings` | PARTIAL |
| TR-SEC-07 | Parser hardening (DTD/XXE, zip bomb, page and image limits done; OCR timeout and XML parts done; RLIMIT_AS Phase 11) | 2, 3, 11 | `tests/unit/test_validator.py::test_xxe_in_content_types_is_rejected`<br>`tests/unit/test_validator.py::test_billion_laughs_is_rejected`<br>`tests/unit/test_validator.py::test_zip_bomb_by_ratio`<br>`tests/unit/test_validator.py::test_too_many_pages`<br>`tests/integration/test_extract_failclosed.py::test_ocr_timeout_marks_page_uninspected`<br>`tests/integration/test_extract_failclosed.py::test_xxe_in_document_part_is_uninspected` | PARTIAL |
| TR-SEC-08 | No original XObjects or thumbnails in output | 6 | - | TODO |
| TR-SEC-09 | Documented prototype limits | 11 | - | TODO |
| V1 | Output reopens via two parsers | 7 | - | TODO |
| V2 | Known-value leak check | 7 | - | TODO |
| V3 | Residual scan | 7 | - | TODO |
| V4 | Coverage | 7 | - | TODO |
| V5 | Overlap and consistency | 7 | - | TODO |
| V6 | Structure SRS/CRS | 7 | - | TODO |
