import React, { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { PageHero } from '../components/PageHero';
import { FileDropzone } from '../components/FileDropzone';
import { InsightCard } from '../components/InsightCard';
import { useCreateBatchMutation } from '../api/queries';
import { batchStorageAdapter } from '../api/adapters';
import { useAuth } from '../app/AuthContext';
import {
  FileText,
  Search,
  CheckCircle,
  ShieldCheck,
  ChevronDown,
  ChevronUp,
  Loader2,
  Sparkles,
} from 'lucide-react';

export const UploadPage: React.FC = () => {
  const [files, setFiles] = useState<File[]>([]);
  const [policy, setPolicy] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [clientError, setClientError] = useState<string | null>(null);

  const { isAuthenticated, token } = useAuth();
  const navigate = useNavigate();
  const dropzoneRef = useRef<HTMLDivElement>(null);

  const createBatchMutation = useCreateBatchMutation();

  const scrollToDropzone = () => {
    dropzoneRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setClientError(null);

    if (files.length === 0) {
      setClientError('Please select or drop at least one document file.');
      return;
    }

    if (!isAuthenticated && !token) {
      navigate('/connect');
      return;
    }

    try {
      const response = await createBatchMutation.mutateAsync({
        files,
        policy: policy.trim() || undefined,
      });

      // ASSUMPTION[A-1]: Persist batch_id and job_ids to sessionStorage
      batchStorageAdapter.saveBatch({
        batch_id: response.batch_id,
        created_at: new Date().toISOString(),
        jobs: response.jobs.map((j) => ({
          job_id: j.job_id,
          filename: j.filename,
          state: j.state,
        })),
      });

      navigate(`/batches/${response.batch_id}`);
    } catch (err: unknown) {
      const errorMsg =
        err instanceof Error ? err.message : 'Batch creation failed unexpectedly.';
      setClientError(errorMsg);
    }
  };

  // Helper to load synthetic scenario files for quick evaluation in mock mode
  const handleSelectScenario = (filename: string) => {
    const dummyBlob = new Blob(['Synthetic test payload for ClearGate engine'], {
      type: 'application/octet-stream',
    });
    const testFile = new window.File([dummyBlob], filename, {
      type: filename.endsWith('.docx')
        ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        : 'application/pdf',
    });
    setFiles([testFile]);
  };

  return (
    <div className="flex-1 flex flex-col">
      <PageHero onPrimaryCtaClick={scrollToDropzone} />

      {/* Main Upload Section */}
      <section ref={dropzoneRef} className="py-12 px-4 sm:px-6 max-w-container mx-auto w-full">
        <div className="max-w-3xl mx-auto space-y-8">
          <div className="border-b border-border pb-4 flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-heading font-bold text-text">
                Submit Document Batch
              </h2>
              <p className="text-sm text-text-muted mt-1">
                Upload business documents for deterministic PII redaction and mathematical verification.
              </p>
            </div>

            {/* Quick scenario selector for evaluating the 6 mock cases */}
            <div className="hidden sm:block text-right">
              <span className="text-[11px] font-mono text-text-muted block">
                Synthetic Scenarios
              </span>
              <div className="flex items-center gap-1.5 mt-1">
                <button
                  type="button"
                  onClick={() => handleSelectScenario('safe.docx')}
                  className="text-xs px-2 py-0.5 rounded bg-surface hover:bg-surface-raised border border-border text-status-safe"
                  title="Scenario 1: safe.docx -> VALIDATED_SAFE"
                >
                  Safe
                </button>
                <button
                  type="button"
                  onClick={() => handleSelectScenario('needs-review.pptx')}
                  className="text-xs px-2 py-0.5 rounded bg-surface hover:bg-surface-raised border border-border text-status-review"
                  title="Scenario 2: needs-review.pptx -> REVIEW_REQUIRED"
                >
                  Review
                </button>
                <button
                  type="button"
                  onClick={() => handleSelectScenario('scan-ocr-off.pdf')}
                  className="text-xs px-2 py-0.5 rounded bg-surface hover:bg-surface-raised border border-border text-status-blocked"
                  title="Scenario 3: scan-ocr-off.pdf -> BLOCKED"
                >
                  Blocked
                </button>
                <button
                  type="button"
                  onClick={() => handleSelectScenario('slow.pdf')}
                  className="text-xs px-2 py-0.5 rounded bg-surface hover:bg-surface-raised border border-border text-status-processing"
                  title="Scenario 5: slow.pdf -> PROCESSING"
                >
                  Slow
                </button>
              </div>
            </div>
          </div>

          <form onSubmit={handleUploadSubmit} className="space-y-6">
            {clientError && (
              <div className="p-4 rounded-md bg-status-failed-bg text-status-failed border border-status-failed/30 text-sm">
                {clientError}
              </div>
            )}

            <FileDropzone
              files={files}
              onFilesChange={setFiles}
              disabled={createBatchMutation.isPending}
            />

            {/* Collapsed Advanced Policy Configuration */}
            <div className="border border-border rounded-md bg-surface p-4">
              <button
                type="button"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="flex items-center justify-between w-full text-xs font-semibold text-text uppercase tracking-wider"
              >
                <span>Advanced Policy Configuration (Optional)</span>
                {showAdvanced ? (
                  <ChevronUp className="w-4 h-4 text-text-muted" />
                ) : (
                  <ChevronDown className="w-4 h-4 text-text-muted" />
                )}
              </button>

              {showAdvanced && (
                <div className="mt-3 pt-3 border-t border-border space-y-2">
                  <label htmlFor="policyName" className="block text-xs text-text-muted">
                    Custom Policy Profile Name
                  </label>
                  <input
                    id="policyName"
                    type="text"
                    value={policy}
                    onChange={(e) => setPolicy(e.target.value)}
                    placeholder="e.g. strict-gdpr-phi-v2"
                    className="w-full px-3 py-2 bg-bg-alt border border-border rounded text-text text-sm focus:ring-1 focus:ring-focus-ring"
                  />
                  <p className="text-[11px] text-text-muted">
                    Leave blank to use the active default enterprise privacy policy.
                  </p>
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-4 pt-2">
              <button
                type="submit"
                disabled={files.length === 0 || createBatchMutation.isPending}
                className="bg-accent hover:bg-accent-hover disabled:opacity-50 text-text-on-accent font-semibold px-6 py-2.5 rounded-md transition-colors shadow flex items-center gap-2 focus:ring-2 focus:ring-focus-ring"
              >
                {createBatchMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Synchronizing Batch...</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" />
                    <span>Process Batch ({files.length} {files.length === 1 ? 'file' : 'files'})</span>
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      </section>

      {/* "What happens to your file" 4-step row (Section 5.2 Optiv InsightCard pattern) */}
      <section className="bg-bg-alt py-16 border-t border-border mt-auto">
        <div className="max-w-container mx-auto px-4 sm:px-6 space-y-8">
          <div>
            <span className="text-xs font-mono uppercase text-accent font-semibold">
              Fail-Closed Pipeline
            </span>
            <h2 className="text-2xl font-heading font-bold text-text mt-1">
              What happens to your document
            </h2>
            <p className="text-sm text-text-muted mt-1 max-w-xl">
              Every submitted artifact traverses four isolated stages before any output is released to an AI model.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <InsightCard
              category="Stage 1 · Ingestion"
              title="1. Structure & OCR Extract"
              blurb="Local parsers extract paragraphs, tables, slides, and embedded images. Tesseract OCR processes raster imagery in offline isolation."
              ctaText="Explore extraction"
              ctaHref="/how-it-works"
              icon={<FileText className="w-5 h-5" />}
            />
            <InsightCard
              category="Stage 2 · Detection"
              title="2. Detect & Mask PII"
              blurb="Multi-layer deterministic regex patterns, corroborated contextual heuristics, and vision detectors mark candidate entities with structured tokens."
              ctaText="Explore detectors"
              ctaHref="/how-it-works"
              icon={<Search className="w-5 h-5" />}
            />
            <InsightCard
              category="Stage 3 · Verification"
              title="3. Independent Verification"
              blurb="A secondary verification scanner inspects the candidate output. Unreadable pages, unapplied masks, or surviving values immediately fail-closed."
              ctaText="Fail-closed rules"
              ctaHref="/how-it-works#fail-closed"
              icon={<ShieldCheck className="w-5 h-5" />}
            />
            <InsightCard
              category="Stage 4 · Gate"
              title="4. Cryptographic Safe Gate"
              blurb="Only documents reaching VALIDATED_SAFE state permit artifact downloads or AI handoff. The AI receives sanitized text only."
              ctaText="Review state machine"
              ctaHref="/how-it-works#states"
              icon={<CheckCircle className="w-5 h-5" />}
            />
          </div>
        </div>
      </section>
    </div>
  );
};
