import React from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { useJobQuery } from '../api/queries';
import { batchStorageAdapter, StoredBatch } from '../api/adapters';
import { StateBadge } from '../components/StateBadge';
import { ProgressBar } from '../components/ProgressBar';
import { StatCounter } from '../components/StatCounter';
import { EmptyState } from '../components/EmptyState';
import {
  Layers,
  ArrowRight,
  AlertTriangle,
  Clock,
  PlusCircle,
  FileText,
} from 'lucide-react';

interface JobRowProps {
  jobId: string;
  initialFilename?: string;
  onJobStateUpdate?: (jobId: string, state: string) => void;
}

const JobRow: React.FC<JobRowProps> = ({
  jobId,
  initialFilename,
  onJobStateUpdate,
}) => {
  const navigate = useNavigate();
  const { data: job, isLoading } = useJobQuery(jobId);

  React.useEffect(() => {
    if (job?.state && onJobStateUpdate) {
      onJobStateUpdate(jobId, job.state);
    }
  }, [job?.state, jobId, onJobStateUpdate]);

  const filename = job?.filename || initialFilename || jobId;
  const warningsCount = job?.warnings?.length ?? 0;

  return (
    <div
      onClick={() => navigate(`/jobs/${jobId}`)}
      className="p-4 sm:p-5 hover:bg-surface-raised cursor-pointer transition-colors flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border last:border-0"
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter') navigate(`/jobs/${jobId}`);
      }}
      aria-label={`View details for job ${filename}`}
    >
      <div className="flex items-start sm:items-center gap-3.5 min-w-0 md:w-1/3">
        <FileText className="w-5 h-5 text-accent shrink-0 mt-0.5 sm:mt-0" />
        <div className="truncate">
          <p className="font-heading font-medium text-sm text-text truncate">
            {filename}
          </p>
          <span className="font-mono text-[11px] text-text-muted">{jobId}</span>
        </div>
      </div>

      <div className="flex-1 max-w-xs w-full">
        {job?.progress ? (
          <ProgressBar
            stage={job.progress.stage}
            done={job.progress.done}
            total={job.progress.total}
          />
        ) : isLoading ? (
          <div className="h-2 bg-surface-raised rounded animate-pulse" />
        ) : (
          <span className="text-xs text-text-muted font-mono">-</span>
        )}
      </div>

      <div className="flex items-center justify-between md:justify-end gap-4 shrink-0">
        {warningsCount > 0 && (
          <span
            className="flex items-center gap-1 text-xs text-status-review font-medium"
            title={`${warningsCount} warnings`}
          >
            <AlertTriangle className="w-3.5 h-3.5" />
            <span>{warningsCount}</span>
          </span>
        )}

        <StateBadge state={job?.state} />

        <ArrowRight className="w-4 h-4 text-text-muted hidden md:block" />
      </div>
    </div>
  );
};

export const BatchPage: React.FC = () => {
  const { batchId } = useParams<{ batchId: string }>();
  const navigate = useNavigate();

  // Load batches from sessionStorage per ASSUMPTION[A-1]
  const storedBatches = batchStorageAdapter.getStoredBatches();
  const currentBatch: StoredBatch | undefined = batchId
    ? storedBatches.find((b) => b.batch_id === batchId)
    : storedBatches[0];

  const handleJobStateUpdate = (jId: string, newState: string) => {
    if (currentBatch?.batch_id) {
      batchStorageAdapter.updateJobStateInBatch(currentBatch.batch_id, jId, newState);
    }
  };

  if (!currentBatch && storedBatches.length === 0) {
    return (
      <div className="max-w-container mx-auto px-4 sm:px-6 py-12 flex-1">
        <EmptyState
          title="No batches active in this session"
          description="You have not submitted any document batches yet. Upload files to start processing through the privacy gate."
          actionText="Upload Documents"
          onAction={() => navigate('/')}
          icon={<Layers className="w-6 h-6 text-accent" />}
        />
      </div>
    );
  }

  // Calculate batch metrics
  const jobsList = currentBatch?.jobs || [];
  const safeCount = jobsList.filter((j) => j.state === 'VALIDATED_SAFE').length;
  const reviewCount = jobsList.filter((j) => j.state === 'REVIEW_REQUIRED').length;
  const processingCount = jobsList.filter(
    (j) => j.state === 'PROCESSING' || j.state === 'RECEIVED'
  ).length;
  const blockedOrFailedCount = jobsList.filter(
    (j) => j.state === 'BLOCKED' || j.state === 'FAILED'
  ).length;

  return (
    <div className="max-w-container mx-auto px-4 sm:px-6 py-10 flex-1 space-y-8">
      {/* Header & Batch Selector */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border pb-6">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono uppercase text-accent font-semibold">
              Batch Tracking
            </span>
            <span className="text-xs font-mono text-text-muted">· 3s polling</span>
          </div>
          <h1 className="text-3xl font-heading font-bold text-text mt-1">
            {currentBatch ? `Batch: ${currentBatch.batch_id}` : 'All Job Batches'}
          </h1>
          {currentBatch?.created_at && (
            <p className="text-xs text-text-muted mt-1 flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5" />
              <span>Created: {new Date(currentBatch.created_at).toLocaleTimeString()}</span>
            </p>
          )}
        </div>

        <div className="flex items-center gap-3">
          <Link
            to="/"
            className="bg-accent hover:bg-accent-hover text-text-on-accent text-sm font-semibold px-4 py-2 rounded-md transition-colors flex items-center gap-2 shadow"
          >
            <PlusCircle className="w-4 h-4" />
            <span>New Batch</span>
          </Link>
        </div>
      </div>

      {/* Optiv Stats Band Pattern (Section 5.3 & 9.1) */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCounter
          value={jobsList.length}
          label="Total Documents"
          helper="Enrolled in gate pipeline"
        />
        <StatCounter
          value={safeCount}
          label="Validated Safe"
          helper="Cleared for AI model handoff"
        />
        <StatCounter
          value={reviewCount}
          label="Needs Review"
          helper="Awaiting reviewer decision"
        />
        <StatCounter
          value={blockedOrFailedCount + processingCount}
          label="Active / Blocked"
          helper={`${processingCount} in-flight · ${blockedOrFailedCount} blocked`}
        />
      </div>

      {/* Jobs Table Container */}
      <div className="bg-surface border border-border rounded-lg shadow-card overflow-hidden">
        <div className="p-4 sm:px-6 bg-surface-raised border-b border-border flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-text">
            Documents in Batch ({jobsList.length})
          </h2>
          <span className="text-xs text-text-muted">
            Auto-polling updates active jobs
          </span>
        </div>

        <div className="divide-y divide-border">
          {jobsList.map((j) => (
            <JobRow
              key={j.job_id}
              jobId={j.job_id}
              initialFilename={j.filename}
              onJobStateUpdate={handleJobStateUpdate}
            />
          ))}
        </div>
      </div>

      {/* Recent Batches History (Session-local per ASSUMPTION[A-1]) */}
      {storedBatches.length > 1 && (
        <div className="pt-6 border-t border-border space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            Recent Session Batches (Tab Storage)
          </h3>
          <div className="flex flex-wrap gap-2">
            {storedBatches.map((b) => (
              <button
                key={b.batch_id}
                type="button"
                onClick={() => navigate(`/batches/${b.batch_id}`)}
                className={`text-xs px-3 py-1.5 rounded-md font-mono border transition-colors ${
                  b.batch_id === currentBatch?.batch_id
                    ? 'bg-accent/15 border-accent text-accent font-semibold'
                    : 'bg-surface border-border text-text-muted hover:border-text-muted'
                }`}
              >
                {b.batch_id} ({b.jobs.length} jobs)
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
