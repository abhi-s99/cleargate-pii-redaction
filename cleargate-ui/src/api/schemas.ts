import { z } from 'zod';

export const ErrorResponseSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    job_id: z.string().optional(),
  }),
}).passthrough();

export type ErrorResponse = z.infer<typeof ErrorResponseSchema>;

export const HealthSchema = z.object({
  status: z.string().default('ok'),
  service: z.string().optional(),
  model_loaded: z.boolean(),
  tesseract_version: z.string().optional(),
  vault_key_present: z.boolean(),
}).passthrough();

export type HealthResponse = z.infer<typeof HealthSchema>;

// GET /whoami: the role the server assigns to the presented token (ADR-35).
export const WhoAmISchema = z.object({
  role: z.enum(['submitter', 'reviewer']),
});

export type WhoAmIResponse = z.infer<typeof WhoAmISchema>;

export const JobStateSchema = z.enum([
  'RECEIVED',
  'PROCESSING',
  'REVIEW_REQUIRED',
  'BLOCKED',
  'VALIDATED_SAFE',
  'FAILED',
]);

export const BatchJobItemSchema = z.object({
  job_id: z.string(),
  filename: z.string(),
  state: JobStateSchema,
}).passthrough();

export const BatchCreateResponseSchema = z.object({
  batch_id: z.string(),
  jobs: z.array(BatchJobItemSchema),
}).passthrough();

export type BatchCreateResponse = z.infer<typeof BatchCreateResponseSchema>;

export const ProgressSchema = z.object({
  stage: z.string().optional(),
  done: z.number().optional(),
  total: z.number().optional(),
}).passthrough();

export const LocatorSchema = z.object({
  part: z.string().optional(),
  page: z.number().optional(),
  slide: z.number().optional(),
  shape_id: z.union([z.number(), z.string()]).optional(),
  paragraph_index: z.number().optional(),
  table: z.number().optional(),
  row: z.number().optional(),
  col: z.number().optional(),
  bbox: z.array(z.number()).optional(),
  image_ref: z.string().optional(),
}).passthrough();

export const JobDetailSchema = z.object({
  job_id: z.string(),
  filename: z.string().optional(),
  state: JobStateSchema,
  progress: ProgressSchema.optional(),
  counts_by_type: z.record(z.string(), z.number()).optional(),
  timings: z.record(z.string(), z.number()).optional(),
  warnings: z.array(z.string()).optional(),
  deciding_rule: z.string().optional(),
  policy_hash: z.string().optional(),
  reason: z.string().optional(),
  created_at: z.string().optional(),
  updated_at: z.string().optional(),
  unresolved_items_count: z.number().optional(),
}).passthrough();

export type JobDetail = z.infer<typeof JobDetailSchema>;

export const EvidenceItemSchema = z.object({
  detector: z.string(),
  layer: z.string().optional(),
  rule_id: z.string().optional(),
  raw_score: z.number().optional(),
  context_terms: z.array(z.string()).optional(),
}).passthrough();

export const FindingSchema = z.object({
  finding_id: z.string(),
  segment_id: z.string().optional(),
  start: z.number().optional(),
  end: z.number().optional(),
  entity_type: z.string(),
  risk: z.enum(['HIGH', 'MEDIUM', 'LOW']),
  tier: z.enum(['DETERMINISTIC', 'CORROBORATED', 'SINGLE_SIGNAL', 'LOW']),
  evidence: z.array(EvidenceItemSchema).default([]),
  format_invalid: z.boolean().optional(),
  preview: z.string(),
  decision: z.string().optional(),
  token: z.string().optional(),
  locator: LocatorSchema.optional(),
}).passthrough();

export type Finding = z.infer<typeof FindingSchema>;

export const ReviewItemSchema = z.object({
  finding_id: z.string(),
  segment_id: z.string().optional(),
  start: z.number().optional(),
  end: z.number().optional(),
  entity_type: z.string(),
  risk: z.enum(['HIGH', 'MEDIUM', 'LOW']),
  tier: z.enum(['DETERMINISTIC', 'CORROBORATED', 'SINGLE_SIGNAL', 'LOW']),
  preview: z.string(),
  evidence: z.array(EvidenceItemSchema).default([]),
  format_invalid: z.boolean().optional(),
  proposed_token: z.string().optional(),
  token: z.string().optional(),
  locator: LocatorSchema.optional(),
  thumbnail_url: z.string().optional(),
  thumbnail_data: z.string().optional(),
  segment_text: z.string().optional(),
}).passthrough();

export type ReviewItem = z.infer<typeof ReviewItemSchema>;

export const ReviewDecisionActionSchema = z.enum([
  'confirm',
  'reject',
  'retype',
  'add',
  'add_region',
  'reject_document',
]);

export const DecisionItemSchema = z.object({
  finding_id: z.string().optional(),
  action: ReviewDecisionActionSchema,
  justification: z.string().optional(),
  entity_type: z.string().optional(),
  segment_id: z.string().optional(),
  start: z.number().optional(),
  end: z.number().optional(),
  page: z.number().optional(),
  bbox: z.array(z.number()).optional(),
  reason: z.string().optional(),
}).passthrough();

export const ReviewSubmitPayloadSchema = z.object({
  decisions: z.array(DecisionItemSchema),
}).passthrough();

export type ReviewSubmitPayload = z.infer<typeof ReviewSubmitPayloadSchema>;

export const HandoffResponseSchema = z.object({
  status: z.string(),
  result: z.string().optional(),
  message: z.string().optional(),
  handoff_id: z.string().optional(),
}).passthrough();

export type HandoffResponse = z.infer<typeof HandoffResponseSchema>;

export const ReportJsonSchema = z.object({
  job_id: z.string(),
  state: z.string(),
  summary: z.string().optional(),
  policy: z.string().optional(),
  entity_counts: z.record(z.string(), z.number()).optional(),
  findings_count: z.number().optional(),
  gate_decision: z.string().optional(),
  gate_reason: z.string().optional(),
  generated_at: z.string().optional(),
}).passthrough();

export type ReportJson = z.infer<typeof ReportJsonSchema>;
