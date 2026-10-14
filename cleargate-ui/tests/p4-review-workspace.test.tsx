import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '../src/app/AuthContext';
import { ReviewPage } from '../src/pages/Review';
import { setApiAuthToken, api } from '../src/api/client';

describe('Phase P4: Review Workspace and Safety Constraints', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
    // Set reviewer role token in sessionStorage and client
    sessionStorage.setItem('cleargate_auth_token', 'reviewer-token');
    sessionStorage.setItem('cleargate_auth_role', 'reviewer');
    setApiAuthToken('Bearer reviewer-token');
  });

  it('prohibits rejection on findings with risk=HIGH and tier=DETERMINISTIC', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <MemoryRouter initialEntries={['/jobs/job-needs-review/review']}>
            <Routes>
              <Route path="/jobs/:jobId/review" element={<ReviewPage />} />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>
    );

    // Wait for the queue items to render
    await screen.findByText('Privacy Review Queue · job-needs-review');

    // The first item in job-needs-review is US_SSN (rendered with friendly label) which is HIGH + DETERMINISTIC
    expect(screen.getAllByText('US Social Security Number').length).toBeGreaterThan(0);
    expect(screen.getAllByText('HIGH').length).toBeGreaterThan(0);
    expect(screen.getAllByText('DETERMINISTIC').length).toBeGreaterThan(0);

    // Verify Reject button is disabled
    const rejectBtn = screen.getByRole('button', { name: /Reject \(R\)/i });
    expect(rejectBtn).toBeDisabled();
  });

  it('allows Confirm on findings and advances decided counter', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <MemoryRouter initialEntries={['/jobs/job-needs-review/review']}>
            <Routes>
              <Route path="/jobs/:jobId/review" element={<ReviewPage />} />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>
    );

    await screen.findByText('Privacy Review Queue · job-needs-review');

    // Initially 0 decided
    expect(screen.getByText(/Decided: 0 of 5/i)).toBeInTheDocument();

    // Click Confirm button
    const confirmBtn = screen.getByRole('button', { name: /Confirm \(C\)/i });
    fireEvent.click(confirmBtn);

    // Now 1 decided
    expect(screen.getByText(/Decided: 1 of 5/i)).toBeInTheDocument();
  });

  it('demonstrates mock loop: submitting review decisions transitions state to PROCESSING', async () => {
    // Directly submit review decisions through API client to verify transition
    const result = await api.submitReviewDecisions('job-needs-review', [
      { finding_id: 'f-nr-1', action: 'confirm' },
      { finding_id: 'f-nr-2', action: 'confirm' },
    ]);
    expect(result.status).toBe('decisions_accepted');

    const job = await api.getJob('job-needs-review');
    expect(job.state).toBe('PROCESSING');
  });

  it('enforces 409 when job is not in REVIEW_REQUIRED state', async () => {
    // job-safe is in VALIDATED_SAFE
    await expect(
      api.submitReviewDecisions('job-safe', [{ finding_id: 'f-1', action: 'confirm' }])
    ).rejects.toThrow();
  });
});
