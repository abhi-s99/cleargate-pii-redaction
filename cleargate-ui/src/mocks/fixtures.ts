// Synthetic fixtures for MSW mock API (Section 10)
import { JobDetail, Finding, ReviewItem, ReportJson } from '../api/schemas';

export interface ScenarioFixture {
  job: JobDetail;
  findings: Finding[];
  reviewItems: ReviewItem[];
  reportMd: string;
  reportJson: ReportJson;
  sanitizedText?: string;
}

export const SCENARIOS: Record<string, ScenarioFixture> = {
  // Scenario 1: safe.docx -> VALIDATED_SAFE
  'job-safe': {
    job: {
      job_id: 'job-safe',
      filename: 'safe.docx',
      state: 'VALIDATED_SAFE',
      progress: { stage: 'completed', done: 10, total: 10 },
      counts_by_type: {
        PERSON: 2,
        EMAIL_ADDRESS: 1,
        DATE_OF_BIRTH: 1,
      },
      timings: {
        extraction_ms: 120,
        detection_ms: 340,
        redaction_ms: 85,
        verification_ms: 150,
      },
      warnings: [],
      deciding_rule: 'RULE_VERIFY_PASSED_ALL_CLEARED',
      policy_hash: 'sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
      created_at: new Date(Date.now() - 300000).toISOString(),
      updated_at: new Date(Date.now() - 60000).toISOString(),
    },
    findings: [
      {
        finding_id: 'f-safe-1',
        segment_id: 'seg-1',
        start: 12,
        end: 25,
        entity_type: 'PERSON',
        risk: 'LOW',
        tier: 'CORROBORATED',
        preview: 'Test P***** A',
        decision: 'auto_redact',
        token: '[PERSON_1]',
        evidence: [
          { detector: 'RegexDetector', layer: 'deterministic', rule_id: 'NAME_TITLE_01', raw_score: 0.95 },
          { detector: 'ContextCorroborator', layer: 'heuristic', context_terms: ['Author:', 'Signer'] },
        ],
        locator: { page: 1, paragraph_index: 2 },
      },
      {
        finding_id: 'f-safe-2',
        segment_id: 'seg-2',
        start: 40,
        end: 63,
        entity_type: 'EMAIL_ADDRESS',
        risk: 'LOW',
        tier: 'DETERMINISTIC',
        preview: 'p*****@example.test',
        decision: 'auto_redact',
        token: '[EMAIL_1]',
        evidence: [
          { detector: 'EmailFormatValidator', layer: 'deterministic', rule_id: 'RFC_5322_SYNTAX', raw_score: 1.0 },
        ],
        locator: { page: 1, paragraph_index: 3 },
      },
    ],
    reviewItems: [],
    sanitizedText: `CONFIDENTIAL REPORT\nPrepared by [PERSON_1] ([EMAIL_1])\nAll verified data was sanitized by ClearGate.\nNo sensitive personal data survives into AI context.`,
    reportMd: `# ClearGate Verification Report
**Job ID:** job-safe  
**Status:** VALIDATED_SAFE  
**Deciding Rule:** RULE_VERIFY_PASSED_ALL_CLEARED  

## Summary
- Total Detections: 3
- Auto Redactions Applied: 3
- Independent Verification: Passed (0 leaks, 0 surviving values)
- Safe Gate Decision: Cleared for AI consumption.
`,
    reportJson: {
      job_id: 'job-safe',
      state: 'VALIDATED_SAFE',
      summary: 'All entities successfully sanitized and independently verified.',
      gate_decision: 'CLEARED',
      gate_reason: 'All detections sanitized with zero residual risks.',
      findings_count: 3,
      entity_counts: { PERSON: 2, EMAIL_ADDRESS: 1, DATE_OF_BIRTH: 1 },
      generated_at: new Date().toISOString(),
    },
  },

  // Scenario 2: needs-review.pptx -> REVIEW_REQUIRED (5 review items)
  'job-needs-review': {
    job: {
      job_id: 'job-needs-review',
      filename: 'needs-review.pptx',
      state: 'REVIEW_REQUIRED',
      progress: { stage: 'awaiting_human_review', done: 7, total: 10 },
      counts_by_type: {
        US_SSN: 1,
        EMPLOYEE_ID: 1,
        PHOTO: 1,
        UNREADABLE_IMAGE_REGION: 1,
        PERSON: 1,
      },
      timings: {
        extraction_ms: 210,
        detection_ms: 450,
      },
      warnings: [
        'Image region on slide 3 could not be OCR-read; flagged for visual review.',
        'High risk deterministic SSN pattern flagged.',
      ],
      deciding_rule: 'RULE_UNCERTAIN_FINDINGS_TRIGGER_REVIEW',
      policy_hash: 'sha256:7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069',
      unresolved_items_count: 5,
      created_at: new Date(Date.now() - 180000).toISOString(),
      updated_at: new Date(Date.now() - 30000).toISOString(),
    },
    findings: [
      {
        finding_id: 'f-nr-1',
        segment_id: 'seg-10',
        start: 15,
        end: 26,
        entity_type: 'US_SSN',
        risk: 'HIGH',
        tier: 'DETERMINISTIC',
        preview: '000-**-0000',
        decision: 'review',
        token: '[SSN]',
        evidence: [
          { detector: 'PatternRegex', layer: 'deterministic', rule_id: 'US_SSN_STRICT', raw_score: 1.0 },
        ],
        locator: { slide: 1, shape_id: 4 },
      },
      {
        finding_id: 'f-nr-2',
        segment_id: 'seg-11',
        start: 35,
        end: 45,
        entity_type: 'EMPLOYEE_ID',
        risk: 'MEDIUM',
        tier: 'CORROBORATED',
        preview: 'EMP-****',
        decision: 'review',
        token: '[EMPLOYEE_ID]',
        evidence: [
          { detector: 'CorporatePrefix', layer: 'heuristic', rule_id: 'EMP_PRE_02', raw_score: 0.8 },
          { detector: 'ContextWindow', context_terms: ['Staff ID', 'Personnel'] },
        ],
        locator: { slide: 2, shape_id: 2 },
      },
      {
        finding_id: 'f-nr-3',
        segment_id: 'seg-12',
        entity_type: 'PHOTO',
        risk: 'MEDIUM',
        tier: 'SINGLE_SIGNAL',
        preview: '[Facial Photograph]',
        decision: 'review',
        token: '[PHOTO_1]',
        evidence: [
          { detector: 'FaceDetectionFilter', layer: 'vision', rule_id: 'CASCADED_FACE_01', raw_score: 0.82 },
        ],
        locator: { slide: 2, shape_id: 7, image_ref: 'ppt/media/image1.png' },
      },
      {
        finding_id: 'f-nr-4',
        segment_id: 'seg-13',
        entity_type: 'UNREADABLE_IMAGE_REGION',
        risk: 'MEDIUM',
        tier: 'LOW',
        preview: '[Unreadable Image Text]',
        decision: 'review',
        token: '[REGION_MASK]',
        evidence: [
          { detector: 'OcrContrastThreshold', layer: 'vision', rule_id: 'LOW_CONFIDENCE_OCR', raw_score: 0.35 },
        ],
        locator: { slide: 3, shape_id: 1, image_ref: 'ppt/media/diagram2.png', bbox: [100, 150, 400, 350] },
      },
      {
        finding_id: 'f-nr-5',
        segment_id: 'seg-14',
        start: 5,
        end: 18,
        entity_type: 'PERSON',
        risk: 'LOW',
        tier: 'SINGLE_SIGNAL',
        preview: 'J*** D**',
        decision: 'review',
        token: '[PERSON_2]',
        evidence: [
          { detector: 'NamedEntityRecognizer', layer: 'statistical', rule_id: 'NER_SPACY_EN', raw_score: 0.65 },
        ],
        locator: { slide: 4, shape_id: 3 },
      },
    ],
    reviewItems: [
      {
        finding_id: 'f-nr-1',
        segment_id: 'seg-10',
        start: 15,
        end: 26,
        entity_type: 'US_SSN',
        risk: 'HIGH',
        tier: 'DETERMINISTIC',
        preview: '000-**-0000',
        proposed_token: '[SSN]',
        evidence: [
          { detector: 'PatternRegex', layer: 'deterministic', rule_id: 'US_SSN_STRICT', raw_score: 1.0 },
        ],
        locator: { slide: 1, shape_id: 4 },
        segment_text: 'Employee record: 000-00-0000 is stored securely in payroll.',
      },
      {
        finding_id: 'f-nr-2',
        segment_id: 'seg-11',
        start: 17,
        end: 25,
        entity_type: 'EMPLOYEE_ID',
        risk: 'MEDIUM',
        tier: 'CORROBORATED',
        preview: 'EMP-****',
        proposed_token: '[EMPLOYEE_ID]',
        evidence: [
          { detector: 'CorporatePrefix', layer: 'heuristic', rule_id: 'EMP_PRE_02', raw_score: 0.8 },
          { detector: 'ContextWindow', context_terms: ['Staff ID', 'Personnel'] },
        ],
        locator: { slide: 2, shape_id: 2 },
        segment_text: 'Staff identifier EMP-9821 submitted quarterly performance objectives.',
      },
      {
        finding_id: 'f-nr-3',
        segment_id: 'seg-12',
        entity_type: 'PHOTO',
        risk: 'MEDIUM',
        tier: 'SINGLE_SIGNAL',
        preview: '[Facial Photograph]',
        proposed_token: '[PHOTO_1]',
        evidence: [
          { detector: 'FaceDetectionFilter', layer: 'vision', rule_id: 'CASCADED_FACE_01', raw_score: 0.82 },
        ],
        locator: { slide: 2, shape_id: 7, image_ref: 'ppt/media/image1.png' },
        thumbnail_data: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200" viewBox="0 0 300 200"><rect width="300" height="200" fill="%231e293b"/><text x="150" y="90" fill="%2394a3b8" font-family="sans-serif" font-size="14" text-anchor="middle">Slide 2 · Badge Photo</text><rect x="90" y="110" width="120" height="60" fill="%23f59e0b" fill-opacity="0.3" stroke="%23f59e0b" stroke-width="2"/><text x="150" y="145" fill="%23fbbf24" font-family="sans-serif" font-size="12" text-anchor="middle">[PHOTO_1]</text></svg>',
        segment_text: 'Slide 2 header: Badge photo asset embedded at shape 7.',
      },
      {
        finding_id: 'f-nr-4',
        segment_id: 'seg-13',
        entity_type: 'UNREADABLE_IMAGE_REGION',
        risk: 'MEDIUM',
        tier: 'LOW',
        preview: '[Unreadable Image Text]',
        proposed_token: '[REGION_MASK]',
        evidence: [
          { detector: 'OcrContrastThreshold', layer: 'vision', rule_id: 'LOW_CONFIDENCE_OCR', raw_score: 0.35 },
        ],
        locator: { slide: 3, shape_id: 1, image_ref: 'ppt/media/diagram2.png', bbox: [100, 150, 400, 350] },
        thumbnail_data: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200" viewBox="0 0 300 200"><rect width="300" height="200" fill="%231e293b"/><text x="150" y="80" fill="%2394a3b8" font-family="sans-serif" font-size="14" text-anchor="middle">Slide 3 Diagram</text><rect x="60" y="100" width="180" height="70" fill="%23ef4444" fill-opacity="0.3" stroke="%23ef4444" stroke-width="2" stroke-dasharray="4"/><text x="150" y="140" fill="%23f87171" font-family="sans-serif" font-size="11" text-anchor="middle">Unreadable Low Contrast Region</text></svg>',
        segment_text: 'Architectural topology diagram contains faded scanned annotations.',
      },
      {
        finding_id: 'f-nr-5',
        segment_id: 'seg-14',
        start: 11,
        end: 19,
        entity_type: 'PERSON',
        risk: 'LOW',
        tier: 'SINGLE_SIGNAL',
        preview: 'J*** D**',
        proposed_token: '[PERSON_2]',
        evidence: [
          { detector: 'NamedEntityRecognizer', layer: 'statistical', rule_id: 'NER_SPACY_EN', raw_score: 0.65 },
        ],
        locator: { slide: 4, shape_id: 3 },
        segment_text: 'Reviewed by John Doe during executive briefing.',
      },
    ],
    reportMd: `# ClearGate Status Report
**Job ID:** job-needs-review  
**Status:** REVIEW_REQUIRED  

## Summary
5 items flagged for privacy officer review before gate decision can be reached.
- US_SSN (Deterministic High Risk)
- EMPLOYEE_ID (Corroborated)
- PHOTO (Single signal vision detector)
- UNREADABLE_IMAGE_REGION (OCR contrast fail)
- PERSON (Statistical NER)
`,
    reportJson: {
      job_id: 'job-needs-review',
      state: 'REVIEW_REQUIRED',
      summary: '5 candidate findings require human reviewer adjudication.',
      gate_decision: 'PENDING_REVIEW',
      gate_reason: 'Uncertain and high-risk findings pending review confirmation.',
      findings_count: 5,
      entity_counts: {
        US_SSN: 1,
        EMPLOYEE_ID: 1,
        PHOTO: 1,
        UNREADABLE_IMAGE_REGION: 1,
        PERSON: 1,
      },
      generated_at: new Date().toISOString(),
    },
  },

  // Scenario 3: scan-ocr-off.pdf -> BLOCKED
  'job-blocked': {
    job: {
      job_id: 'job-blocked',
      filename: 'scan-ocr-off.pdf',
      state: 'BLOCKED',
      progress: { stage: 'verification_failed', done: 8, total: 10 },
      counts_by_type: {
        UNREADABLE_IMAGE_REGION: 3,
        PERSON: 1,
      },
      timings: {
        extraction_ms: 320,
        detection_ms: 480,
        verification_ms: 220,
      },
      warnings: [
        'Multiple corrupted and unreadable scanned raster pages encountered.',
        'Fail-closed policy triggered: unverified regions cannot be proven safe.',
      ],
      deciding_rule: 'RULE_FAIL_CLOSED_CORRUPTED_OR_UNREADABLE_SURVIVING',
      policy_hash: 'sha256:1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b',
      reason: 'Fail-closed verification: document has 3 unreadable raster pages that could not be verified safe.',
      created_at: new Date(Date.now() - 400000).toISOString(),
      updated_at: new Date(Date.now() - 120000).toISOString(),
    },
    findings: [],
    reviewItems: [],
    reportMd: `# ClearGate Gate Decision Report
**Job ID:** job-blocked  
**Status:** BLOCKED  
**Deciding Rule:** RULE_FAIL_CLOSED_CORRUPTED_OR_UNREADABLE_SURVIVING  

## Reason
Fail-closed policy enforced: Scanner was unable to reliably extract 3 pages. Output cannot be validated safe for AI handoff.
`,
    reportJson: {
      job_id: 'job-blocked',
      state: 'BLOCKED',
      summary: 'Document blocked under fail-closed privacy policy.',
      gate_decision: 'BLOCKED',
      gate_reason: 'Unreadable scanned pages prevent verification.',
      findings_count: 4,
      generated_at: new Date().toISOString(),
    },
  },

  // Scenario 4: encrypted.pdf -> FAILED
  'job-failed': {
    job: {
      job_id: 'job-failed',
      filename: 'encrypted.pdf',
      state: 'FAILED',
      progress: { stage: 'validation_error', done: 0, total: 10 },
      warnings: ['File is password encrypted or malformed. Extraction aborted.'],
      deciding_rule: 'RULE_EXTRACTION_FATAL_ERROR',
      reason: 'Encrypted document: PDF parsing failed due to password encryption.',
      created_at: new Date(Date.now() - 500000).toISOString(),
      updated_at: new Date(Date.now() - 490000).toISOString(),
    },
    findings: [],
    reviewItems: [],
    reportMd: `# ClearGate Pipeline Error Report
**Job ID:** job-failed  
**Status:** FAILED  
**Code:** ENCRYPTED_FILE_NOT_SUPPORTED  

Extraction failed. Password-protected documents must be decrypted prior to submission.
`,
    reportJson: {
      job_id: 'job-failed',
      state: 'FAILED',
      summary: 'Fatal extraction failure: encrypted file format.',
      gate_decision: 'FAILED',
      gate_reason: 'Encrypted file cannot be processed.',
      findings_count: 0,
      generated_at: new Date().toISOString(),
    },
  },

  // Scenario 5: slow.pdf -> PROCESSING
  'job-slow': {
    job: {
      job_id: 'job-slow',
      filename: 'slow.pdf',
      state: 'PROCESSING',
      progress: { stage: 'ocr_extraction', done: 3, total: 10 },
      counts_by_type: {},
      timings: { extraction_ms: 1800 },
      warnings: ['Large raster scan: OCR running in multi-pass mode.'],
      created_at: new Date(Date.now() - 60000).toISOString(),
      updated_at: new Date().toISOString(),
    },
    findings: [],
    reviewItems: [],
    reportMd: `# ClearGate Job Status Report
**Job ID:** job-slow  
**Status:** PROCESSING  

Processing in progress. Currently executing stage: ocr_extraction (3/10).
`,
    reportJson: {
      job_id: 'job-slow',
      state: 'PROCESSING',
      summary: 'Job is actively executing in background pipeline.',
      gate_decision: 'PENDING',
      findings_count: 0,
      generated_at: new Date().toISOString(),
    },
  },

  // Scenario 6: queued.docx -> RECEIVED
  'job-queued': {
    job: {
      job_id: 'job-queued',
      filename: 'queued.docx',
      state: 'RECEIVED',
      progress: { stage: 'queued', done: 0, total: 10 },
      counts_by_type: {},
      warnings: [],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    findings: [],
    reviewItems: [],
    reportMd: `# ClearGate Job Status Report
**Job ID:** job-queued  
**Status:** RECEIVED  

Job received and registered in batch dispatch queue.
`,
    reportJson: {
      job_id: 'job-queued',
      state: 'RECEIVED',
      summary: 'Job is queued for processing.',
      gate_decision: 'QUEUED',
      findings_count: 0,
      generated_at: new Date().toISOString(),
    },
  },
};
