import React from 'react';
import { formatStageTitle } from '../domain/stateUi';

interface ProgressBarProps {
  stage?: string;
  done?: number;
  total?: number;
  showDetails?: boolean;
}

export const ProgressBar: React.FC<ProgressBarProps> = ({
  stage,
  done,
  total,
  showDetails = true,
}) => {
  const percentage =
    total !== undefined && total > 0 && done !== undefined
      ? Math.min(100, Math.round((done / total) * 100))
      : 0;

  const stageLabel = formatStageTitle(stage);

  return (
    <div className="w-full space-y-1.5" aria-live="polite">
      {showDetails && (
        <div className="flex items-center justify-between text-xs text-text-muted">
          <span className="font-medium text-text">{stageLabel}</span>
          <span className="font-mono">
            {done !== undefined && total !== undefined
              ? `${done} / ${total} (${percentage}%)`
              : '-'}
          </span>
        </div>
      )}

      <div
        className="w-full bg-surface-raised rounded-full h-2 overflow-hidden border border-border"
        role="progressbar"
        aria-valuenow={done ?? 0}
        aria-valuemin={0}
        aria-valuemax={total ?? 100}
        aria-label={`Progress: ${stageLabel}`}
      >
        <div
          className="bg-accent h-full rounded-full transition-all duration-300"
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
};
