import { http, HttpResponse } from 'msw';
import { SCENARIOS } from './fixtures';

// In-memory scenario state tracking for dynamic transitions
const scenarioState = { ...SCENARIOS };
let slowProgress = 3;

function getAuthRole(request: Request): 'submitter' | 'reviewer' | null {
  const auth = request.headers.get('Authorization');
  if (!auth || !auth.startsWith('Bearer ')) return null;
  const token = auth.replace('Bearer ', '').trim().toLowerCase();
  if (token.includes('reviewer')) return 'reviewer';
  return 'submitter';
}

function checkAuth(request: Request): { authorized: boolean; role: 'submitter' | 'reviewer' | null } {
  const role = getAuthRole(request);
  if (!role) return { authorized: false, role: null };
  return { authorized: true, role };
}

export const handlers = [
  // GET /api/v1/health
  http.get('*/api/v1/health', () => {
    return HttpResponse.json({
      status: 'ok',
      service: 'cleargate-backend-mock',
      model_loaded: true,
      tesseract_version: '5.3.4-local',
      vault_key_present: true,
    });
  }),

  // GET /api/v1/whoami
  http.get('*/api/v1/whoami', ({ request }) => {
    const { authorized, role } = checkAuth(request);
    if (!authorized) {
      return HttpResponse.json(
        { error: { code: 'UNAUTHORIZED', message: 'Bearer token is missing or invalid.' } },
        { status: 401 }
      );
    }
    return HttpResponse.json({ role });
  }),

  // POST /api/v1/batches
  http.post('*/api/v1/batches', async ({ request }) => {
    const { authorized } = checkAuth(request);
    if (!authorized) {
      return HttpResponse.json(
        { error: { code: 'UNAUTHORIZED', message: 'Bearer token is missing or invalid.' } },
        { status: 401 }
      );
    }

    const formData = await request.formData();
    const files = formData.getAll('files[]') as File[];
    const batchId = `batch-${Date.now().toString(36)}`;

    // Match files to scenario jobs or create default synthetic jobs
    const jobs = files.map((file, idx) => {
      const name = file.name.toLowerCase();
      let matchedScenarioId = 'job-safe';

      if (name.includes('needs-review')) matchedScenarioId = 'job-needs-review';
      else if (name.includes('scan-ocr-off') || name.includes('blocked')) matchedScenarioId = 'job-blocked';
      else if (name.includes('encrypted') || name.includes('failed')) matchedScenarioId = 'job-failed';
      else if (name.includes('slow')) matchedScenarioId = 'job-slow';
      else if (name.includes('queued')) matchedScenarioId = 'job-queued';

      const scenario = scenarioState[matchedScenarioId];
      const jobId = `${matchedScenarioId}-${idx}`;
      // Clone scenario into memory
      scenarioState[jobId] = {
        ...scenario,
        job: {
          ...scenario.job,
          job_id: jobId,
          filename: file.name,
        },
      };

      return {
        job_id: jobId,
        filename: file.name,
        state: scenario.job.state,
      };
    });

    return HttpResponse.json({
      batch_id: batchId,
      jobs,
    });
  }),

  // GET /api/v1/jobs/:id
  http.get('*/api/v1/jobs/:id', ({ request, params }) => {
    const { authorized } = checkAuth(request);
    if (!authorized) {
      return HttpResponse.json(
        { error: { code: 'UNAUTHORIZED', message: 'Bearer token is missing or invalid.' } },
        { status: 401 }
      );
    }

    const id = params.id as string;
    const scenario = scenarioState[id] || scenarioState['job-safe'];

    // Dynamic progress advance for slow scenario
    if (id.includes('slow')) {
      slowProgress = (slowProgress % 10) + 1;
      return HttpResponse.json({
        ...scenario.job,
        progress: {
          stage: slowProgress < 5 ? 'ocr_extraction' : 'deep_pii_analysis',
          done: slowProgress,
          total: 10,
        },
      });
    }

    return HttpResponse.json(scenario.job);
  }),

  // GET /api/v1/jobs/:id/findings
  http.get('*/api/v1/jobs/:id/findings', ({ request, params }) => {
    const { authorized, role } = checkAuth(request);
    if (!authorized) {
      return HttpResponse.json(
        { error: { code: 'UNAUTHORIZED', message: 'Bearer token is missing or invalid.' } },
        { status: 401 }
      );
    }

    const url = new URL(request.url);
    const includeText = url.searchParams.get('include_text') === 'true';

    if (includeText && role !== 'reviewer') {
      return HttpResponse.json(
        {
          error: {
            code: 'FORBIDDEN_REVIEWER_REQUIRED',
            message: 'Viewing raw unmasked findings requires reviewer privileges.',
          },
        },
        { status: 403 }
      );
    }

    const id = params.id as string;
    const scenario = scenarioState[id] || scenarioState['job-safe'];
    return HttpResponse.json(scenario.findings);
  }),

  // GET /api/v1/jobs/:id/review
  http.get('*/api/v1/jobs/:id/review', ({ request, params }) => {
    const { authorized, role } = checkAuth(request);
    if (!authorized) {
      return HttpResponse.json(
        { error: { code: 'UNAUTHORIZED', message: 'Bearer token is missing or invalid.' } },
        { status: 401 }
      );
    }

    if (role !== 'reviewer') {
      return HttpResponse.json(
        {
          error: {
            code: 'FORBIDDEN_REVIEWER_REQUIRED',
            message: 'Access denied: review workspace requires a reviewer token.',
          },
        },
        { status: 403 }
      );
    }

    const id = params.id as string;
    const scenario = scenarioState[id] || scenarioState['job-needs-review'];
    return HttpResponse.json(scenario.reviewItems);
  }),

  // POST /api/v1/jobs/:id/review
  http.post('*/api/v1/jobs/:id/review', async ({ request, params }) => {
    const { authorized, role } = checkAuth(request);
    if (!authorized) {
      return HttpResponse.json(
        { error: { code: 'UNAUTHORIZED', message: 'Bearer token is missing or invalid.' } },
        { status: 401 }
      );
    }

    if (role !== 'reviewer') {
      return HttpResponse.json(
        {
          error: {
            code: 'FORBIDDEN_REVIEWER_REQUIRED',
            message: 'Submitting review decisions requires reviewer credentials.',
          },
        },
        { status: 403 }
      );
    }

    const id = params.id as string;
    const scenario = scenarioState[id] || scenarioState['job-needs-review'];

    // 409 Conflict if not in REVIEW_REQUIRED
    if (scenario.job.state !== 'REVIEW_REQUIRED') {
      return HttpResponse.json(
        {
          error: {
            code: 'INVALID_JOB_STATE',
            message: 'Review decisions can only be submitted for jobs in REVIEW_REQUIRED state.',
            job_id: id,
          },
        },
        { status: 409 }
      );
    }

    // Loop demonstration: Transition REVIEW_REQUIRED -> PROCESSING -> VALIDATED_SAFE
    scenario.job.state = 'PROCESSING';
    scenario.job.progress = { stage: 're_verification', done: 9, total: 10 };
    scenario.job.warnings = [];

    // Trigger eventual transition to VALIDATED_SAFE
    setTimeout(() => {
      if (scenarioState[id]) {
        scenarioState[id].job.state = 'VALIDATED_SAFE';
        scenarioState[id].job.progress = { stage: 'completed', done: 10, total: 10 };
        scenarioState[id].job.deciding_rule = 'RULE_POST_REVIEW_VERIFY_SAFE';
        scenarioState[id].reviewItems = [];
      }
    }, 4000);

    return HttpResponse.json({ status: 'decisions_accepted' });
  }),

  // GET /api/v1/jobs/:id/report?format=json|md
  http.get('*/api/v1/jobs/:id/report', ({ request, params }) => {
    const { authorized } = checkAuth(request);
    if (!authorized) {
      return HttpResponse.json(
        { error: { code: 'UNAUTHORIZED', message: 'Bearer token is missing or invalid.' } },
        { status: 401 }
      );
    }

    const url = new URL(request.url);
    const format = url.searchParams.get('format') || 'md';
    const id = params.id as string;
    const scenario = scenarioState[id] || scenarioState['job-safe'];

    if (format === 'json') {
      return HttpResponse.json(scenario.reportJson);
    }

    return new HttpResponse(scenario.reportMd, {
      headers: { 'Content-Type': 'text/markdown; charset=utf-8' },
    });
  }),

  // GET /api/v1/jobs/:id/artifacts/sanitized.txt (403 unless VALIDATED_SAFE)
  http.get('*/api/v1/jobs/:id/artifacts/sanitized.txt', ({ request, params }) => {
    const { authorized } = checkAuth(request);
    if (!authorized) {
      return HttpResponse.json(
        { error: { code: 'UNAUTHORIZED', message: 'Bearer token is missing or invalid.' } },
        { status: 401 }
      );
    }

    const id = params.id as string;
    const scenario = scenarioState[id] || scenarioState['job-safe'];

    if (scenario.job.state !== 'VALIDATED_SAFE') {
      return HttpResponse.json(
        {
          error: {
            code: 'FORBIDDEN_OUTPUT_UNVERIFIED',
            message: 'Sanitized text is only available when state is VALIDATED_SAFE.',
            job_id: id,
          },
        },
        { status: 403 }
      );
    }

    const text = scenario.sanitizedText || 'CONFIDENTIAL SANITIZED TEXT DUMP';
    return new HttpResponse(text, {
      headers: {
        'Content-Type': 'text/plain; charset=utf-8',
        'Content-Disposition': 'attachment; filename="sanitized.txt"',
      },
    });
  }),

  // GET /api/v1/jobs/:id/artifacts/redacted.:ext (403 unless VALIDATED_SAFE)
  http.get('*/api/v1/jobs/:id/artifacts/:filename', ({ request, params }) => {
    const { authorized } = checkAuth(request);
    if (!authorized) {
      return HttpResponse.json(
        { error: { code: 'UNAUTHORIZED', message: 'Bearer token is missing or invalid.' } },
        { status: 401 }
      );
    }

    const id = params.id as string;
    const scenario = scenarioState[id] || scenarioState['job-safe'];

    if (scenario.job.state !== 'VALIDATED_SAFE') {
      return HttpResponse.json(
        {
          error: {
            code: 'FORBIDDEN_OUTPUT_UNVERIFIED',
            message: 'Redacted files are only available when state is VALIDATED_SAFE.',
            job_id: id,
          },
        },
        { status: 403 }
      );
    }

    const blob = new Blob(['Mock synthetic redacted binary content'], {
      type: 'application/octet-stream',
    });
    return new HttpResponse(blob, {
      headers: {
        'Content-Type': 'application/octet-stream',
        'Content-Disposition': 'attachment; filename="redacted-artifact.docx"',
      },
    });
  }),

  // POST /api/v1/jobs/:id/handoff (409 unless VALIDATED_SAFE)
  http.post('*/api/v1/jobs/:id/handoff', ({ request, params }) => {
    const { authorized } = checkAuth(request);
    if (!authorized) {
      return HttpResponse.json(
        { error: { code: 'UNAUTHORIZED', message: 'Bearer token is missing or invalid.' } },
        { status: 401 }
      );
    }

    const id = params.id as string;
    const scenario = scenarioState[id] || scenarioState['job-safe'];

    if (scenario.job.state !== 'VALIDATED_SAFE') {
      return HttpResponse.json(
        {
          error: {
            code: 'CONFLICT_NOT_SAFE',
            message: 'Handoff to AI model permitted only after state is VALIDATED_SAFE.',
            job_id: id,
          },
        },
        { status: 409 }
      );
    }

    return HttpResponse.json({
      status: 'HANDOFF_SUCCESS',
      handoff_id: `ho-${Date.now().toString(36)}`,
      result: 'SafeHandle transferred to AI model. Model completed reasoning without privacy exposure.',
      message: 'The AI receives sanitized text only.',
    });
  }),

  // DELETE /api/v1/batches/:id (Behind VITE_ENABLE_DELETE=false)
  http.delete('*/api/v1/batches/:id', ({ request, params }) => {
    const { authorized } = checkAuth(request);
    if (!authorized) {
      return HttpResponse.json(
        { error: { code: 'UNAUTHORIZED', message: 'Bearer token is missing or invalid.' } },
        { status: 401 }
      );
    }

    return HttpResponse.json({
      deleted: true,
      batch_id: params.id,
    });
  }),
];
