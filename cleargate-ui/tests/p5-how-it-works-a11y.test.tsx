import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { HowItWorksPage } from '../src/pages/HowItWorks';

describe('Phase P5: How It Works & Accessibility Pass', () => {
  it('renders 8-stage pipeline, state machine SVG, fail-closed principles, and limitations', () => {
    render(
      <MemoryRouter initialEntries={['/how-it-works']}>
        <HowItWorksPage />
      </MemoryRouter>
    );

    // 8-stage pipeline
    expect(screen.getByText(/The 8-Stage Document Lifecycle/i)).toBeInTheDocument();
    expect(screen.getByText('1. Validate')).toBeInTheDocument();
    expect(screen.getByText('8. Handoff')).toBeInTheDocument();

    // State machine SVG diagram
    expect(screen.getByLabelText(/ClearGate Job State Machine Diagram/i)).toBeInTheDocument();
    expect(screen.getByText('Server-Enforced Job State Transitions')).toBeInTheDocument();

    // Fail-closed explainer
    expect(
      screen.getByText(/An unread page, an unapplied redaction, or a surviving value blocks the document/i)
    ).toBeInTheDocument();

    // Limitations box with honest disclaimers (Section 5.6)
    expect(screen.getByText(/No scanner proves zero PII:/i)).toBeInTheDocument();
    expect(screen.getByText(/OCR cannot read every region:/i)).toBeInTheDocument();
    expect(screen.getByText(/Prototype security posture:/i)).toBeInTheDocument();
  });
});
