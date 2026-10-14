import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../src/app/AuthContext';
import { Layout } from '../src/components/Layout';

describe('Phase P0: Global Layout and Chrome', () => {
  it('renders utility bar, navbar, and footer with brand wordmark', () => {
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={['/']}>
          <Layout />
        </MemoryRouter>
      </AuthProvider>
    );

    // Verify wordmark ClearGate exists per Rule R8
    expect(screen.getAllByText('ClearGate').length).toBeGreaterThan(0);

    // Verify navigation links
    expect(screen.getByText('Upload')).toBeInTheDocument();
    expect(screen.getByText('Jobs')).toBeInTheDocument();
    expect(screen.getByText('How it works')).toBeInTheDocument();

    // Verify utility bar
    expect(
      screen.getByText(/Prototype · design baseline v0.1/i)
    ).toBeInTheDocument();

    // Verify footer disclaimer
    expect(
      screen.getByText(/Prototype built for the Optiv Consulting case study PS-2/i)
    ).toBeInTheDocument();
  });
});
