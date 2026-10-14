import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '../src/app/AuthContext';
import { ConnectPage } from '../src/pages/Connect';
import { ReviewPage } from '../src/pages/Review';

function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/connect" element={<ConnectPage />} />
            <Route path="/" element={<div>home page</div>} />
            <Route path="/jobs/:jobId/review" element={<ReviewPage />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}

describe('Phase P6: the server decides the role of a token (ADR-35)', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('stores the role reported by the server, not the button that was selected', async () => {
    renderAt('/connect');
    // The "Submitter" button stays selected, but the token is a reviewer token.
    fireEvent.change(screen.getByPlaceholderText(/token/i), {
      target: { value: 'reviewer-demo-token' },
    });
    fireEvent.click(screen.getByLabelText(/Keep token for this browser tab/i));
    fireEvent.click(screen.getByRole('button', { name: /Connect & Authorize/i }));
    await screen.findByText('home page');
    expect(sessionStorage.getItem('cleargate_auth_role')).toBe('reviewer');
  });

  it('says "not connected" on the review page when no token is held', async () => {
    renderAt('/jobs/job-needs-review/review');
    await waitFor(() => expect(screen.getByText(/Not connected/i)).toBeInTheDocument());
  });
});
