// API Client with strict runtime contract validation and error handling
import {
  HealthSchema,
  BatchCreateResponseSchema,
  JobDetailSchema,
  FindingSchema,
  ReviewItemSchema,
  HandoffResponseSchema,
  ReportJsonSchema,
  ErrorResponseSchema,
  HealthResponse,
  BatchCreateResponse,
  JobDetail,
  Finding,
  ReviewItem,
  HandoffResponse,
  ReportJson,
} from './schemas';
import { adaptDecisionPayload, LocalDecision } from './adapters';
import { z } from 'zod';

export class ApiError extends Error {
  public code: string;
  public status: number;
  public jobId?: string;

  constructor(status: number, code: string, message: string, jobId?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.jobId = jobId;
  }
}

let currentAuthToken: string | null = null;
let onUnauthorizedCallback: (() => void) | null = null;

export function setApiAuthToken(token: string | null): void {
  currentAuthToken = token;
}

export function setOnUnauthorized(cb: () => void): void {
  onUnauthorizedCallback = cb;
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

async function request<T>(
  endpoint: string,
  options: RequestInit = {},
  schema?: z.ZodType<T, z.ZodTypeDef, unknown>
): Promise<T> {
  const url = `${BASE_URL}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;
  const headers = new Headers(options.headers);

  if (currentAuthToken && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${currentAuthToken}`);
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    if (onUnauthorizedCallback) onUnauthorizedCallback();
    throw new ApiError(401, 'UNAUTHORIZED', 'Session token is missing, invalid, or expired.');
  }

  if (!response.ok) {
    let errorCode = `HTTP_${response.status}`;
    let errorMessage = `Server error (${response.status})`;
    let jobId: string | undefined;

    try {
      const errJson = await response.json();
      const parsed = ErrorResponseSchema.safeParse(errJson);
      if (parsed.success) {
        errorCode = parsed.data.error.code;
        errorMessage = parsed.data.error.message;
        jobId = parsed.data.error.job_id;
      }
    } catch {
      // Non-JSON error response
    }

    if (response.status === 403) {
      if (endpoint.includes('/review') || endpoint.includes('/findings')) {
        errorMessage = 'This token does not have the reviewer role required for this endpoint.';
      } else {
        errorMessage = errorMessage || 'Access forbidden: document output not permitted in this state.';
      }
    }

    if (response.status === 409) {
      errorMessage = errorMessage || 'Operation conflict: the job is not in the required state.';
    }

    throw new ApiError(response.status, errorCode, errorMessage, jobId);
  }

  // Handle empty or blob responses
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('text/plain') || contentType.includes('text/markdown')) {
    const textData = await response.text();
    return textData as unknown as T;
  }

  const json = await response.json();
  if (schema) {
    const parseResult = schema.safeParse(json);
    if (!parseResult.success) {
      // Rule R5: Validate contract at runtime. On mismatch show visible message with endpoint name
      throw new Error(`Unexpected response from server: ${endpoint}`);
    }
    return parseResult.data;
  }

  return json as T;
}

export const api = {
  // GET /health
  async getHealth(): Promise<HealthResponse> {
    return request<HealthResponse>('/health', { method: 'GET' }, HealthSchema);
  },

  // POST /batches
  async createBatch(files: File[], policy?: string): Promise<BatchCreateResponse> {
    const formData = new FormData();
    files.forEach((file) => formData.append('files[]', file));
    if (policy && policy.trim()) {
      formData.append('policy', policy.trim());
    }

    return request<BatchCreateResponse>(
      '/batches',
      {
        method: 'POST',
        body: formData,
      },
      BatchCreateResponseSchema
    );
  },

  // GET /jobs/{id}
  async getJob(id: string): Promise<JobDetail> {
    return request<JobDetail>(`/jobs/${id}`, { method: 'GET' }, JobDetailSchema);
  },

  // GET /jobs/{id}/findings
  async getFindings(id: string, includeText = false): Promise<Finding[]> {
    const query = includeText ? '?include_text=true' : '';
    return request<Finding[]>(
      `/jobs/${id}/findings${query}`,
      { method: 'GET' },
      z.array(FindingSchema)
    );
  },

  // GET /jobs/{id}/review
  async getReviewItems(id: string): Promise<ReviewItem[]> {
    return request<ReviewItem[]>(
      `/jobs/${id}/review`,
      { method: 'GET' },
      z.array(ReviewItemSchema)
    );
  },

  // POST /jobs/{id}/review
  async submitReviewDecisions(id: string, decisions: LocalDecision[]): Promise<{ status: string }> {
    const payload = adaptDecisionPayload(decisions);
    return request<{ status: string }>(
      `/jobs/${id}/review`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }
    );
  },

  // GET /jobs/{id}/report?format=json|md
  async getReportMd(id: string): Promise<string> {
    return request<string>(`/jobs/${id}/report?format=md`, { method: 'GET' });
  },

  async getReportJson(id: string): Promise<ReportJson> {
    return request<ReportJson>(`/jobs/${id}/report?format=json`, { method: 'GET' }, ReportJsonSchema);
  },

  // GET /jobs/{id}/artifacts/sanitized.txt (Blob download with Bearer auth)
  async downloadSanitizedText(id: string): Promise<Blob> {
    const url = `${BASE_URL}/jobs/${id}/artifacts/sanitized.txt`;
    const headers = new Headers();
    if (currentAuthToken) headers.set('Authorization', `Bearer ${currentAuthToken}`);

    const res = await fetch(url, { headers });
    if (!res.ok) {
      if (res.status === 403) {
        throw new ApiError(403, 'FORBIDDEN', 'Sanitized text is available only when state is Validated safe.');
      }
      throw new ApiError(res.status, 'DOWNLOAD_FAILED', 'Failed to download sanitized text.');
    }
    return res.blob();
  },

  // GET /jobs/{id}/artifacts/redacted.{ext}
  async downloadRedactedFile(id: string, ext = 'docx'): Promise<Blob> {
    const url = `${BASE_URL}/jobs/${id}/artifacts/redacted.${ext}`;
    const headers = new Headers();
    if (currentAuthToken) headers.set('Authorization', `Bearer ${currentAuthToken}`);

    const res = await fetch(url, { headers });
    if (!res.ok) {
      if (res.status === 403) {
        throw new ApiError(403, 'FORBIDDEN', 'Redacted artifact is available only when state is Validated safe.');
      }
      throw new ApiError(res.status, 'DOWNLOAD_FAILED', 'Failed to download redacted file.');
    }
    return res.blob();
  },

  // POST /jobs/{id}/handoff
  async handoffSafe(id: string): Promise<HandoffResponse> {
    return request<HandoffResponse>(
      `/jobs/${id}/handoff`,
      { method: 'POST' },
      HandoffResponseSchema
    );
  },

  // DELETE /batches/{id} (behind VITE_ENABLE_DELETE=false)
  async deleteBatch(id: string): Promise<{ deleted: boolean }> {
    return request<{ deleted: boolean }>(`/batches/${id}`, { method: 'DELETE' });
  },
};
