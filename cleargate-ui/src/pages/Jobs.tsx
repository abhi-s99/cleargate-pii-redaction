import React from 'react';
import { useSearchParams } from 'react-router-dom';
import { BatchPage } from './Batch';
import { SCENARIOS } from '../mocks/fixtures';
import { Link } from 'react-router-dom';
import { StateBadge } from '../components/StateBadge';
import { ShieldAlert, ArrowRight } from 'lucide-react';
import { useAuth } from '../app/AuthContext';

export const JobsPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const isReviewQueueView = searchParams.get('view') === 'review';
  const { role } = useAuth();

  if (isReviewQueueView) {
    const reviewJobs = Object.values(SCENARIOS).filter(
      (s) => s.job.state === 'REVIEW_REQUIRED'
    );

    return (
      <div className="max-w-container mx-auto px-4 sm:px-6 py-10 flex-1 space-y-6">
        <div className="border-b border-border pb-4">
          <span className="text-xs font-mono uppercase text-accent font-semibold">
            Privacy Review
          </span>
          <h1 className="text-3xl font-heading font-bold text-text mt-1">
            Review Queue
          </h1>
          <p className="text-sm text-text-muted mt-1">
            Jobs requiring human reviewer verification before safety gating can proceed.
          </p>
        </div>

        {role !== 'reviewer' ? (
          <div className="bg-surface border border-border rounded-lg p-8 text-center space-y-3">
            <ShieldAlert className="w-8 h-8 text-status-review mx-auto" />
            <h2 className="text-lg font-bold text-text">Reviewer Credentials Required</h2>
            <p className="text-sm text-text-muted max-w-md mx-auto">
              Your current token has the Submitter role. To resolve findings in the review workspace, connect using a Reviewer token.
            </p>
            <Link
              to="/connect"
              className="inline-block mt-2 text-xs font-semibold bg-accent text-text-on-accent px-4 py-2 rounded-md"
            >
              Switch to Reviewer Role
            </Link>
          </div>
        ) : (
          <div className="bg-surface border border-border rounded-lg divide-y divide-border overflow-hidden">
            {reviewJobs.map((item) => (
              <div
                key={item.job.job_id}
                className="p-5 flex items-center justify-between hover:bg-surface-raised transition-colors"
              >
                <div>
                  <div className="flex items-center gap-3">
                    <h3 className="font-semibold text-text">{item.job.filename}</h3>
                    <StateBadge state={item.job.state} />
                  </div>
                  <p className="text-xs text-text-muted mt-1">
                    Job ID: {item.job.job_id} · {item.reviewItems.length} items flagged for review
                  </p>
                </div>

                <Link
                  to={`/jobs/${item.job.job_id}/review`}
                  className="bg-accent hover:bg-accent-hover text-text-on-accent text-xs font-semibold px-4 py-2 rounded flex items-center gap-1.5 transition-colors"
                >
                  <span>Open Review Workspace</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </Link>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  return <BatchPage />;
};
