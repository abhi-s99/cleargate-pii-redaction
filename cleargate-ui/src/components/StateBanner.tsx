import React from 'react';
import { getStateUiConfig } from '../domain/stateUi';
import { StateBadge } from './StateBadge';
import { ShieldCheck, AlertCircle, FileKey } from 'lucide-react';

interface StateBannerProps {
  state?: string;
  decidingRule?: string;
  policyHash?: string;
  reason?: string;
  unresolvedCount?: number;
}

export const StateBanner: React.FC<StateBannerProps> = ({
  state,
  decidingRule,
  policyHash,
  reason,
  unresolvedCount,
}) => {
  const config = getStateUiConfig(state);

  return (
    <div
      className="p-6 rounded-lg border bg-surface-raised border-border space-y-4 shadow-card"
      aria-live="polite"
    >
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <StateBadge state={state} size="lg" />
          <h2 className="text-lg font-semibold text-text">
            {config.bannerMessage}
          </h2>
        </div>

        {unresolvedCount !== undefined && unresolvedCount > 0 && (
          <span className="text-xs bg-status-review-bg text-status-review border border-status-review/30 px-3 py-1 rounded-full font-medium">
            {unresolvedCount} item{unresolvedCount === 1 ? '' : 's'} awaiting review
          </span>
        )}
      </div>

      {(reason || decidingRule || policyHash) && (
        <div className="pt-2 border-t border-border/60 text-xs text-text-muted space-y-2">
          {reason && (
            <div className="flex items-start gap-2 text-text">
              <AlertCircle className="w-4 h-4 text-status-review shrink-0 mt-0.5" />
              <span>{reason}</span>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-6 pt-1 font-mono text-[11px]">
            {decidingRule && (
              <div className="flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5 text-accent" />
                <span className="text-text-muted">Rule:</span>
                <span className="text-text">{decidingRule}</span>
              </div>
            )}
            {policyHash && (
              <div className="flex items-center gap-1.5">
                <FileKey className="w-3.5 h-3.5 text-accent" />
                <span className="text-text-muted">Policy Hash:</span>
                <span className="text-text truncate max-w-xs" title={policyHash}>
                  {policyHash.slice(0, 20)}...
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
