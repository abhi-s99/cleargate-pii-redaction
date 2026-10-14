import React, { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  useJobQuery,
  useFindingsQuery,
  useReportMdQuery,
} from '../api/queries';
import { api, ApiError } from '../api/client';
import { useAuth } from '../app/AuthContext';
import { StateBanner } from '../components/StateBanner';
import { DataTable } from '../components/DataTable';
import { MarkdownView } from '../components/MarkdownView';
import { ErrorPanel } from '../components/ErrorPanel';
import { getStateUiConfig } from '../domain/stateUi';
import {
  FileText,
  Search,
  Download,
  Bot,
  ShieldAlert,
  ArrowLeft,
  Clock,
  AlertTriangle,
  ChevronRight,
  ExternalLink,
  Code,
  Sparkles,
} from 'lucide-react';

export const JobDetailPage: React.FC = () => {
  const { jobId } = useParams<{ jobId: string }>();
  const { role } = useAuth();

  const [activeTab, setActiveTab] = useState<
    'overview' | 'findings' | 'report' | 'downloads' | 'handoff'
  >('overview');
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [handoffResult, setHandoffResult] = useState<string | null>(null);
  const [handoffPending, setHandoffPending] = useState(false);
  const [handoffError, setHandoffError] = useState<string | null>(null);
  const [showRawJson, setShowRawJson] = useState(false);

  const { data: job, isLoading: jobLoading, error: jobError } = useJobQuery(jobId);
  const { data: findings = [], isLoading: findingsLoading } = useFindingsQuery(
    jobId,
    false // Never request include_text=true in findings tab per Section 5.4 #2
  );
  const { data: reportMd = '' } = useReportMdQuery(jobId);

  if (jobLoading) {
    return (
      <div className="max-w-container mx-auto px-4 sm:px-6 py-12 flex-1">
        <div className="animate-pulse space-y-6">
          <div className="h-6 bg-surface-raised rounded w-1/4"></div>
          <div className="h-32 bg-surface rounded"></div>
        </div>
      </div>
    );
  }

  if (jobError || !job) {
    return (
      <div className="max-w-container mx-auto px-4 sm:px-6 py-12 flex-1">
        <ErrorPanel
          code="JOB_NOT_FOUND"
          message={jobError ? jobError.message : 'Job could not be retrieved.'}
        />
        <div className="mt-4">
          <Link to="/jobs" className="text-link text-sm hover:underline">
            &larr; Return to jobs list
          </Link>
        </div>
      </div>
    );
  }

  const stateConfig = getStateUiConfig(job.state);
  const isSafe = job.state === 'VALIDATED_SAFE';
  const isReviewRequired = job.state === 'REVIEW_REQUIRED';

  // Handle blob downloads per Section 7 & Section 8
  const handleDownloadSanitizedText = async () => {
    if (!jobId) return;
    setDownloadError(null);
    try {
      const blob = await api.downloadSanitizedText(jobId);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `sanitized-${job.filename || jobId}.txt`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      a.remove();
    } catch (e: unknown) {
      const err = e as ApiError;
      setDownloadError(err.message || 'Download forbidden: document not validated safe.');
    }
  };

  const handleDownloadRedactedFile = async () => {
    if (!jobId) return;
    setDownloadError(null);
    try {
      // The redacted file keeps the uploaded format (redacted.<ext> on the server).
      const ext = (job.filename || '').split('.').pop()?.toLowerCase() || 'bin';
      const blob = await api.downloadRedactedFile(jobId, ext);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `redacted-${job.filename || jobId}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      a.remove();
    } catch (e: unknown) {
      const err = e as ApiError;
      setDownloadError(err.message || 'Download forbidden: document not validated safe.');
    }
  };

  const handleHandoff = async () => {
    if (!jobId) return;
    setHandoffPending(true);
    setHandoffError(null);
    setHandoffResult(null);
    try {
      const res = await api.handoffSafe(jobId);
      setHandoffResult(res.result || 'SafeHandle passed to AI model successfully.');
    } catch (e: unknown) {
      const err = e as ApiError;
      setHandoffError(err.message || 'Operation conflict: handoff permitted only in VALIDATED_SAFE state.');
    } finally {
      setHandoffPending(false);
    }
  };

  const handleDownloadReportJson = async () => {
    if (!jobId) return;
    try {
      const json = await api.getReportJson(jobId);
      const blob = new Blob([JSON.stringify(json, null, 2)], {
        type: 'application/json',
      });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `report-${jobId}.json`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      a.remove();
    } catch {
      // Ignore download errors
    }
  };

  return (
    <div className="max-w-container mx-auto px-4 sm:px-6 py-8 flex-1 space-y-6">
      {/* Breadcrumb navigation */}
      <div className="flex items-center gap-2 text-xs text-text-muted">
        <Link to="/jobs" className="hover:text-text flex items-center gap-1">
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>All Batches & Jobs</span>
        </Link>
        <span>/</span>
        <span className="text-text font-medium">{job.filename || jobId}</span>
      </div>

      {/* Main State Banner (Section 7) */}
      <StateBanner
        state={job.state}
        decidingRule={job.deciding_rule}
        policyHash={job.policy_hash}
        reason={job.reason}
        unresolvedCount={job.unresolved_items_count}
      />

      {/* If REVIEW_REQUIRED, prominent Callout to Review Workspace */}
      {isReviewRequired && (
        <div className="p-4 bg-status-review-bg border border-status-review/40 rounded-lg flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <ShieldAlert className="w-5 h-5 text-status-review shrink-0" />
            <div>
              <h3 className="text-sm font-semibold text-text">
                Uncertain findings require privacy officer resolution
              </h3>
              <p className="text-xs text-text-muted">
                Document safety cannot be determined until candidate items are resolved in the review queue.
              </p>
            </div>
          </div>

          <Link
            to={`/jobs/${jobId}/review`}
            className="bg-accent hover:bg-accent-hover text-text-on-accent text-xs font-semibold px-4 py-2 rounded-md flex items-center gap-1.5 shrink-0 shadow"
          >
            <span>Open Review Workspace</span>
            <ChevronRight className="w-4 h-4" />
          </Link>
        </div>
      )}

      {/* Tab navigation */}
      <div className="border-b border-border flex items-center space-x-1 sm:space-x-4 overflow-x-auto">
        <button
          type="button"
          onClick={() => setActiveTab('overview')}
          className={`py-3 px-3 border-b-2 text-xs sm:text-sm font-medium transition-colors flex items-center gap-1.5 whitespace-nowrap ${
            activeTab === 'overview'
              ? 'border-accent text-accent font-semibold'
              : 'border-transparent text-text-muted hover:text-text'
          }`}
        >
          <FileText className="w-4 h-4" />
          <span>Overview</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('findings')}
          className={`py-3 px-3 border-b-2 text-xs sm:text-sm font-medium transition-colors flex items-center gap-1.5 whitespace-nowrap ${
            activeTab === 'findings'
              ? 'border-accent text-accent font-semibold'
              : 'border-transparent text-text-muted hover:text-text'
          }`}
        >
          <Search className="w-4 h-4" />
          <span>Findings ({findings.length})</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('report')}
          className={`py-3 px-3 border-b-2 text-xs sm:text-sm font-medium transition-colors flex items-center gap-1.5 whitespace-nowrap ${
            activeTab === 'report'
              ? 'border-accent text-accent font-semibold'
              : 'border-transparent text-text-muted hover:text-text'
          }`}
        >
          <FileText className="w-4 h-4" />
          <span>Report</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('downloads')}
          className={`py-3 px-3 border-b-2 text-xs sm:text-sm font-medium transition-colors flex items-center gap-1.5 whitespace-nowrap ${
            activeTab === 'downloads'
              ? 'border-accent text-accent font-semibold'
              : 'border-transparent text-text-muted hover:text-text'
          }`}
        >
          <Download className="w-4 h-4" />
          <span>Downloads</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('handoff')}
          className={`py-3 px-3 border-b-2 text-xs sm:text-sm font-medium transition-colors flex items-center gap-1.5 whitespace-nowrap ${
            activeTab === 'handoff'
              ? 'border-accent text-accent font-semibold'
              : 'border-transparent text-text-muted hover:text-text'
          }`}
        >
          <Bot className="w-4 h-4" />
          <span>AI Handoff</span>
        </button>

        {isReviewRequired && (
          <Link
            to={`/jobs/${jobId}/review`}
            className="py-3 px-3 text-xs sm:text-sm font-medium text-status-review hover:underline flex items-center gap-1 ml-auto whitespace-nowrap"
          >
            <span>Review Workspace</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </Link>
        )}
      </div>

      {/* Tab 1: Overview */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Entity Detections by Type */}
            <div className="bg-surface border border-border rounded-lg p-5 space-y-4 shadow-card">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-text">
                Entity Counts by Type
              </h3>

              {job.counts_by_type && Object.keys(job.counts_by_type).length > 0 ? (
                <div className="space-y-2">
                  {Object.entries(job.counts_by_type).map(([entType, count]) => (
                    <div
                      key={entType}
                      className="flex items-center justify-between text-xs py-1.5 border-b border-border/50 last:border-0"
                    >
                      <span className="font-mono text-text">{entType}</span>
                      <span className="font-semibold text-text bg-surface-raised px-2 py-0.5 rounded border border-border">
                        {count}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-text-muted">
                  No entity detections recorded for this job.
                </p>
              )}
            </div>

            {/* Execution Timings */}
            <div className="bg-surface border border-border rounded-lg p-5 space-y-4 shadow-card">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-text flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-accent" />
                <span>Pipeline Stage Timings</span>
              </h3>

              {job.timings && Object.keys(job.timings).length > 0 ? (
                <div className="space-y-2">
                  {Object.entries(job.timings).map(([stageName, timeMs]) => (
                    <div
                      key={stageName}
                      className="flex items-center justify-between text-xs py-1.5 border-b border-border/50 last:border-0"
                    >
                      <span className="text-text-muted capitalize">
                        {stageName.replace(/_/g, ' ')}
                      </span>
                      <span className="font-mono text-text">{timeMs} ms</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-text-muted">
                  Timing metrics not emitted for current stage.
                </p>
              )}
            </div>
          </div>

          {/* Warnings List */}
          {job.warnings && job.warnings.length > 0 && (
            <div className="bg-surface border border-border rounded-lg p-5 space-y-3 shadow-card">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-status-review flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5" />
                <span>Job Warnings & Telemetry Flags ({job.warnings.length})</span>
              </h3>
              <ul className="space-y-2 text-xs">
                {job.warnings.map((warn, i) => (
                  <li
                    key={i}
                    className="p-2.5 rounded bg-status-review-bg text-text border border-status-review/20 flex items-start gap-2"
                  >
                    <span className="text-status-review">•</span>
                    <span>{warn}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Collapsible non-sensitive JSON viewer fallback (ASSUMPTION[A-3]) */}
          <div className="border border-border rounded-lg bg-surface p-4">
            <button
              type="button"
              onClick={() => setShowRawJson(!showRawJson)}
              className="flex items-center gap-2 text-xs font-mono text-text-muted hover:text-text"
            >
              <Code className="w-4 h-4 text-accent" />
              <span>{showRawJson ? 'Hide non-sensitive raw response' : 'View raw job metadata (JSON)'}</span>
            </button>
            {showRawJson && (
              <pre className="mt-3 p-4 bg-bg-alt rounded text-xs font-mono text-text-muted overflow-x-auto border border-border">
                {JSON.stringify(job, null, 2)}
              </pre>
            )}
          </div>
        </div>
      )}

      {/* Tab 2: Findings */}
      {activeTab === 'findings' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between text-xs text-text-muted px-1">
            <span>
              All previews are server-masked. Raw unmasked document text is isolated from this table.
            </span>
            {role !== 'reviewer' && (
              <span className="text-status-review">Viewing with Submitter token</span>
            )}
          </div>
          <DataTable findings={findings} isLoading={findingsLoading} />
        </div>
      )}

      {/* Tab 3: Report */}
      {activeTab === 'report' && (
        <div className="space-y-4">
          <MarkdownView
            content={reportMd || '# Report Pending\nReport not generated yet.'}
            onDownloadJson={handleDownloadReportJson}
            title={`Privacy Engine Report: ${job.filename || jobId}`}
          />
        </div>
      )}

      {/* Tab 4: Downloads */}
      {activeTab === 'downloads' && (
        <div className="bg-surface border border-border rounded-lg p-6 space-y-6 shadow-card">
          <div>
            <h3 className="font-heading font-semibold text-lg text-text">
              Document Artifact Downloads
            </h3>
            <p className="text-xs text-text-muted mt-1">
              Outputs are cryptographically released only when the state is Validated safe.
            </p>
          </div>

          {downloadError && (
            <div className="p-3 bg-status-failed-bg text-status-failed border border-status-failed/30 rounded text-xs">
              {downloadError}
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Sanitized Text Download */}
            <div className="border border-border rounded-lg p-5 bg-surface-raised space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-sm text-text">Sanitized Text File</span>
                <span className="text-xs font-mono text-text-muted">.txt</span>
              </div>
              <p className="text-xs text-text-muted">
                Plain text extracted from the document with all detected personal identifiers replaced by privacy tokens.
              </p>
              <div title={!isSafe ? 'Available only when the state is Validated safe.' : undefined}>
                <button
                  type="button"
                  onClick={handleDownloadSanitizedText}
                  disabled={!isSafe}
                  className="w-full bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-text-on-accent text-xs font-semibold py-2 px-4 rounded transition-colors flex items-center justify-center gap-2"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>Download Sanitized Text</span>
                </button>
              </div>
            </div>

            {/* Redacted File Download */}
            <div className="border border-border rounded-lg p-5 bg-surface-raised space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-sm text-text">Redacted Original Document</span>
                <span className="text-xs font-mono text-text-muted">Original format</span>
              </div>
              <p className="text-xs text-text-muted">
                Re-rendered document format with raster masks baked directly into visual layers.
              </p>
              <div title={!isSafe ? 'Available only when the state is Validated safe.' : undefined}>
                <button
                  type="button"
                  onClick={handleDownloadRedactedFile}
                  disabled={!isSafe}
                  className="w-full bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-text-on-accent text-xs font-semibold py-2 px-4 rounded transition-colors flex items-center justify-center gap-2"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>Download Redacted Document</span>
                </button>
              </div>
            </div>
          </div>

          {!stateConfig.downloadsEnabled && (
            <p className="text-xs text-text-muted italic border-t border-border pt-4">
              * Available only when the state is Validated safe.
            </p>
          )}
        </div>
      )}

      {/* Tab 5: AI Handoff */}
      {activeTab === 'handoff' && (
        <div className="bg-surface border border-border rounded-lg p-6 space-y-6 shadow-card">
          <div>
            <h3 className="font-heading font-semibold text-lg text-text">
              Direct AI Model Handoff
            </h3>
            <p className="text-xs text-text-muted mt-1">
              Transfer safe verified handles directly into downstream inference context without human file handling.
            </p>
          </div>

          <div className="p-4 bg-bg-alt border border-border rounded-md text-xs text-text-muted flex items-start gap-2.5">
            <Sparkles className="w-4 h-4 text-accent shrink-0 mt-0.5" />
            <p className="font-medium text-text">
              The AI receives sanitized text only.
            </p>
          </div>

          {handoffError && (
            <div className="p-3 bg-status-failed-bg text-status-failed border border-status-failed/30 rounded text-xs">
              {handoffError}
            </div>
          )}

          {handoffResult && (
            <div className="p-4 bg-status-safe-bg text-status-safe border border-status-safe/30 rounded text-xs space-y-1">
              <p className="font-semibold">Handoff Success:</p>
              <p>{handoffResult}</p>
            </div>
          )}

          <div title={!isSafe ? 'Available only when the state is Validated safe.' : undefined}>
            <button
              type="button"
              onClick={handleHandoff}
              disabled={!isSafe || handoffPending}
              className="bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-text-on-accent text-sm font-semibold py-2.5 px-6 rounded-md transition-colors flex items-center gap-2 shadow"
            >
              <Bot className="w-4 h-4" />
              <span>{handoffPending ? 'Transferring SafeHandle...' : 'Send sanitized text to the AI agent (mock)'}</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
