import { describe, it, expect, beforeEach } from 'vitest';
import { api, setApiAuthToken, ApiError } from '../src/api/client';
import { SCENARIOS } from '../src/mocks/fixtures';
import { JobDetailSchema } from '../src/api/schemas';

describe('Phase P1: API Contract & Mock Verification', () => {
  beforeEach(() => {
    setApiAuthToken('Bearer submitter-valid-token');
  });

  it('verifies GET /health returns valid health schema without auth', async () => {
    setApiAuthToken(null);
    const health = await api.getHealth();
    expect(health.status).toBe('ok');
    expect(health.model_loaded).toBe(true);
    expect(health.vault_key_present).toBe(true);
  });

  it('rejects unauthenticated requests with 401 UNAUTHORIZED', async () => {
    setApiAuthToken(null);
    await expect(api.getJob('job-safe')).rejects.toThrowError(ApiError);
    try {
      await api.getJob('job-safe');
    } catch (e: unknown) {
      const err = e as ApiError;
      expect(err.status).toBe(401);
      expect(err.code).toBe('UNAUTHORIZED');
    }
  });

  it('verifies all 6 scenario jobs return valid schemas', async () => {
    const scenarioKeys = Object.keys(SCENARIOS);
    expect(scenarioKeys).toHaveLength(6);

    for (const key of scenarioKeys) {
      const job = await api.getJob(key);
      const parsed = JobDetailSchema.safeParse(job);
      expect(parsed.success).toBe(true);
      expect(job.job_id).toBe(key);
      expect(job.state).toBe(SCENARIOS[key].job.state);
    }
  });

  it('returns 403 on reviewer-only review items endpoint when using submitter token', async () => {
    setApiAuthToken('Bearer submitter-token');
    await expect(api.getReviewItems('job-needs-review')).rejects.toThrowError();
    try {
      await api.getReviewItems('job-needs-review');
    } catch (e: unknown) {
      const err = e as ApiError;
      expect(err.status).toBe(403);
      expect(err.code).toBe('FORBIDDEN_REVIEWER_REQUIRED');
    }
  });

  it('allows reviewer token to fetch review items with valid schema', async () => {
    setApiAuthToken('Bearer reviewer-token');
    const items = await api.getReviewItems('job-needs-review');
    expect(items).toHaveLength(5);
    expect(items[0].finding_id).toBe('f-nr-1');
    expect(items[0].risk).toBe('HIGH');
    expect(items[0].tier).toBe('DETERMINISTIC');
  });

  it('enforces 403 on artifacts unless job is in VALIDATED_SAFE state', async () => {
    // job-blocked is BLOCKED -> must return 403
    await expect(api.downloadSanitizedText('job-blocked')).rejects.toThrowError();
    try {
      await api.downloadSanitizedText('job-blocked');
    } catch (e: unknown) {
      const err = e as ApiError;
      expect(err.status).toBe(403);
    }

    // job-safe is VALIDATED_SAFE -> succeeds
    const blob = await api.downloadSanitizedText('job-safe');
    expect(blob).toBeDefined();
    expect(blob.size).toBeGreaterThan(0);
  });

  it('enforces 409 on handoff unless job is in VALIDATED_SAFE state', async () => {
    // job-needs-review is in REVIEW_REQUIRED -> 409
    await expect(api.handoffSafe('job-needs-review')).rejects.toThrowError();
    try {
      await api.handoffSafe('job-needs-review');
    } catch (e: unknown) {
      const err = e as ApiError;
      expect(err.status).toBe(409);
    }

    // job-safe is VALIDATED_SAFE -> 200
    const handoff = await api.handoffSafe('job-safe');
    expect(handoff.status).toBe('HANDOFF_SUCCESS');
  });

  it('enforces 409 on review decision POST if state is not REVIEW_REQUIRED', async () => {
    setApiAuthToken('Bearer reviewer-token');
    // job-safe is already VALIDATED_SAFE -> 409
    await expect(
      api.submitReviewDecisions('job-safe', [{ finding_id: 'f-1', action: 'confirm' }])
    ).rejects.toThrowError();
    try {
      await api.submitReviewDecisions('job-safe', [{ finding_id: 'f-1', action: 'confirm' }]);
    } catch (e: unknown) {
      const err = e as ApiError;
      expect(err.status).toBe(409);
    }
  });

  it('demonstrates review loop: submitting decisions on REVIEW_REQUIRED transitions state', async () => {
    setApiAuthToken('Bearer reviewer-token');
    const res = await api.submitReviewDecisions('job-needs-review', [
      { finding_id: 'f-nr-1', action: 'confirm' },
    ]);
    expect(res.status).toBe('decisions_accepted');

    // Job transitions to PROCESSING immediately
    const updatedJob = await api.getJob('job-needs-review');
    expect(updatedJob.state).toBe('PROCESSING');
  });
});
