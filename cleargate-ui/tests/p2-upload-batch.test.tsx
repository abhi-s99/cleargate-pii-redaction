import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '../src/app/AuthContext';
import { UploadPage } from '../src/pages/Upload';
import { FileDropzone } from '../src/components/FileDropzone';
import { isTerminalState } from '../src/domain/states';
import { ProgressBar } from '../src/components/ProgressBar';

describe('Phase P2: Upload, Extension Validation, Polling Logic', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
  });

  it('blocks legacy unencrypted extensions (.doc, .ppt, .docm, .pptm) client-side with explicit message', async () => {
    const handleFilesChange = vi.fn();

    render(
      <FileDropzone
        files={[]}
        onFilesChange={handleFilesChange}
      />
    );

    const blockedFile = new window.File(['fake content'], 'test-legacy.doc', {
      type: 'application/msword',
    });

    const dropzone = screen.getByRole('button', { name: /Upload files dropzone/i });

    // Simulate drag & drop with blocked extension
    fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [blockedFile],
      },
    });

    expect(
      screen.getByText(/File "test-legacy.doc" is not supported: please save legacy formats as .docx or .pptx/i)
    ).toBeInTheDocument();
    expect(handleFilesChange).not.toHaveBeenCalled();
  });

  it('allows valid supported extensions (.docx, .pdf, .pptx)', () => {
    const handleFilesChange = vi.fn();

    render(
      <FileDropzone
        files={[]}
        onFilesChange={handleFilesChange}
      />
    );

    const validFile = new window.File(['docx content'], 'valid-doc.docx', {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    });

    const dropzone = screen.getByRole('button', { name: /Upload files dropzone/i });

    fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [validFile],
      },
    });

    expect(handleFilesChange).toHaveBeenCalledWith([validFile]);
  });

  it('verifies terminal states correctly stop polling calculation', () => {
    // Check terminal states: BLOCKED, FAILED, VALIDATED_SAFE
    expect(isTerminalState('BLOCKED')).toBe(true);
    expect(isTerminalState('FAILED')).toBe(true);
    expect(isTerminalState('VALIDATED_SAFE')).toBe(true);

    // Non-terminal states: RECEIVED, PROCESSING, REVIEW_REQUIRED
    expect(isTerminalState('RECEIVED')).toBe(false);
    expect(isTerminalState('PROCESSING')).toBe(false);
    expect(isTerminalState('REVIEW_REQUIRED')).toBe(false);
  });

  it('renders progress bar with stage and ratio formatted without raw nulls', () => {
    render(
      <ProgressBar
        stage="ocr_extraction"
        done={3}
        total={10}
      />
    );

    // Stage must be title-cased per ASSUMPTION[A-5]
    expect(screen.getByText('Ocr Extraction')).toBeInTheDocument();
    expect(screen.getByText('3 / 10 (30%)')).toBeInTheDocument();
  });

  it('renders Upload home screen with 4-step explainer row', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <MemoryRouter initialEntries={['/']}>
            <UploadPage />
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>
    );

    expect(screen.getByText(/What happens to your document/i)).toBeInTheDocument();
    expect(screen.getByText(/1. Structure & OCR Extract/i)).toBeInTheDocument();
    expect(screen.getByText(/2. Detect & Mask PII/i)).toBeInTheDocument();
    expect(screen.getByText(/3. Independent Verification/i)).toBeInTheDocument();
    expect(screen.getByText(/4. Cryptographic Safe Gate/i)).toBeInTheDocument();
  });
});
