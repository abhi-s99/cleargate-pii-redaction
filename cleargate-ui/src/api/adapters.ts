// Isolated adapter file per Rule R3 & Section 4.1
import {
  JobDetail,
  JobDetailSchema,
  ReviewSubmitPayload,
  ReviewSubmitPayloadSchema,
  DecisionItemSchema,
  BatchCreateResponse,
  BatchCreateResponseSchema,
  ReportJson,
  ReportJsonSchema,
  ErrorResponse,
  ErrorResponseSchema,
} from './schemas';
import { z } from 'zod';

// ASSUMPTION[A-1]: Batch ID and Job IDs stored in sessionStorage without document content.
const BATCH_STORAGE_KEY = 'cleargate_batches_v1';

export interface StoredBatch {
  batch_id: string;
  created_at: string;
  jobs: Array<{
    job_id: string;
    filename: string;
    state: string;
  }>;
}

export const batchStorageAdapter = {
  getStoredBatches(): StoredBatch[] {
    try {
      const raw = sessionStorage.getItem(BATCH_STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  },

  saveBatch(batch: StoredBatch): void {
    try {
      const existing = this.getStoredBatches();
      const updated = [batch, ...existing.filter((b) => b.batch_id !== batch.batch_id)].slice(0, 10);
      sessionStorage.setItem(BATCH_STORAGE_KEY, JSON.stringify(updated));
    } catch {
      // Ignore storage errors
    }
  },

  updateJobStateInBatch(batchId: string, jobId: string, newState: string): void {
    try {
      const batches = this.getStoredBatches();
      const batch = batches.find((b) => b.batch_id === batchId);
      if (batch) {
        const job = batch.jobs.find((j) => j.job_id === jobId);
        if (job) {
          job.state = newState;
          sessionStorage.setItem(BATCH_STORAGE_KEY, JSON.stringify(batches));
        }
      }
    } catch {
      // Ignore storage errors
    }
  },
};

// ASSUMPTION[A-3]: Tolerant runtime parser for Job Detail
export function adaptJobDetail(raw: unknown): { data?: JobDetail; error?: string } {
  const result = JobDetailSchema.safeParse(raw);
  if (!result.success) {
    return {
      error: `Unexpected response from server: /jobs/{id} (${result.error.issues[0]?.message ?? 'invalid schema'})`,
    };
  }
  return { data: result.data };
}

// ASSUMPTION[A-3]: Tolerant runtime parser for Batch Creation
export function adaptBatchCreateResponse(raw: unknown): { data?: BatchCreateResponse; error?: string } {
  const result = BatchCreateResponseSchema.safeParse(raw);
  if (!result.success) {
    return {
      error: `Unexpected response from server: /batches (${result.error.issues[0]?.message ?? 'invalid schema'})`,
    };
  }
  return { data: result.data };
}

// ASSUMPTION[A-4]: Decision POST body adapter transforms reviewer decisions into { decisions: [...] }
export interface LocalDecision {
  finding_id?: string;
  action: 'confirm' | 'reject' | 'retype' | 'add' | 'add_region' | 'reject_document';
  justification?: string;
  entity_type?: string;
  segment_id?: string;
  start?: number;
  end?: number;
  page?: number;
  bbox?: number[];
  reason?: string;
}

export function adaptDecisionPayload(decisions: LocalDecision[]): ReviewSubmitPayload {
  const parsed = decisions.map((d) => DecisionItemSchema.parse(d));
  return ReviewSubmitPayloadSchema.parse({ decisions: parsed });
}

// ASSUMPTION[A-3]: Tolerant parser for safe Report JSON
export function adaptReportJson(raw: unknown): { data?: ReportJson; error?: string } {
  const result = ReportJsonSchema.safeParse(raw);
  if (!result.success) {
    return {
      error: `Unexpected response from server: /jobs/{id}/report (${result.error.issues[0]?.message ?? 'invalid schema'})`,
    };
  }
  return { data: result.data };
}

// Standard Error Response Parser per Section 4
export function adaptErrorResponse(raw: unknown): ErrorResponse | null {
  const result = ErrorResponseSchema.safeParse(raw);
  return result.success ? result.data : null;
}

// Generic tolerant validator per Rule R5
export function validateResponse<T>(schema: z.ZodType<T>, endpoint: string, data: unknown): T {
  const result = schema.safeParse(data);
  if (!result.success) {
    // Rule R5: Show visible "Unexpected response from server" with endpoint name, log nothing sensitive
    throw new Error(`Unexpected response from server: ${endpoint}`);
  }
  return result.data;
}
