import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '../src/app/AuthContext';
import { JobDetailPage } from '../src/pages/JobDetail';
import { setApiAuthToken } from '../src/api/client';
import { STATE_UI_MAP } from '../src/domain/stateUi';
import { JobState } from '../src/domain/states';

describe('Phase P3: Job Detail and State->UI Table Mapping', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
    sessionStorage.setItem('cleargate_auth_token', 'submitter-token');
    setApiAuthToken('Bearer submitter-token');
  });

  const allStates: JobState[] = [
    'RECEIVED',
    'PROCESSING',
    'REVIEW_REQUIRED',
    'BLOCKED',
    'FAILED',
    'VALIDATED_SAFE',
  ];

  it('verifies stateUi table rules: downloads and handoff enabled ONLY for VALIDATED_SAFE', () => {
    for (const state of allStates) {
      const config = STATE_UI_MAP[state];
      if (state === 'VALIDATED_SAFE') {
        expect(config.downloadsEnabled).toBe(true);
        expect(config.handoffEnabled).toBe(true);
      } else {
        expect(config.downloadsEnabled).toBe(false);
        expect(config.handoffEnabled).toBe(false);
      }
    }
  });

  it('renders JobDetail for job-safe and verifies downloads and handoff buttons are enabled', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <MemoryRouter initialEntries={['/jobs/job-safe']}>
            <Routes>
              <Route path="/jobs/:jobId" element={<JobDetailPage />} />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>
    );

    // Wait for job-safe data to load
    await screen.findByText('RULE_VERIFY_PASSED_ALL_CLEARED');
    expect(screen.getByText('safe.docx')).toBeInTheDocument();
    expect(screen.getByText('Validated safe')).toBeInTheDocument();

    // Switch to Downloads tab
    fireEvent.click(screen.getByRole('button', { name: /Downloads/i }));
    const downloadTextBtn = screen.getByRole('button', { name: /Download Sanitized Text/i });
    expect(downloadTextBtn).toBeEnabled();

    // Switch to AI Handoff tab
    fireEvent.click(screen.getByRole('button', { name: /AI Handoff/i }));
    const handoffBtn = screen.getByRole('button', { name: /Send sanitized text to the AI agent/i });
    expect(handoffBtn).toBeEnabled();
    expect(screen.getByText(/The AI receives sanitized text only/i)).toBeInTheDocument();
  });

  it('renders JobDetail for job-blocked and verifies downloads/handoff buttons are disabled', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <MemoryRouter initialEntries={['/jobs/job-blocked']}>
            <Routes>
              <Route path="/jobs/:jobId" element={<JobDetailPage />} />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>
    );

    // Wait for job-blocked to load
    await screen.findByText(/Fail-closed verification: document has 3 unreadable raster pages/i);
    expect(screen.getByText('scan-ocr-off.pdf')).toBeInTheDocument();
    expect(screen.getByText('Blocked')).toBeInTheDocument();

    // Switch to Downloads tab
    fireEvent.click(screen.getByRole('button', { name: /Downloads/i }));
    const downloadTextBtn = screen.getByRole('button', { name: /Download Sanitized Text/i });
    expect(downloadTextBtn).toBeDisabled();

    // Switch to AI Handoff tab
    fireEvent.click(screen.getByRole('button', { name: /AI Handoff/i }));
    const handoffBtn = screen.getByRole('button', { name: /Send sanitized text to the AI agent/i });
    expect(handoffBtn).toBeDisabled();
  });
});
