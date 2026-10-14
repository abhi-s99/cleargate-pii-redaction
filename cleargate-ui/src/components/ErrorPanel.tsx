import React from 'react';
import { AlertCircle } from 'lucide-react';

interface ErrorPanelProps {
  code: string;
  message: string;
  endpoint?: string;
  onRetry?: () => void;
}

export const ErrorPanel: React.FC<ErrorPanelProps> = ({
  code,
  message,
  endpoint,
  onRetry,
}) => {
  return (
    <div
      className="bg-status-failed-bg border border-status-failed/30 rounded-lg p-5 text-status-failed space-y-3"
      role="alert"
    >
      <div className="flex items-start gap-3">
        <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
        <div className="space-y-1 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs px-2 py-0.5 rounded bg-status-failed/20 border border-status-failed/40">
              {code}
            </span>
            {endpoint && (
              <span className="text-xs text-text-muted font-mono">{endpoint}</span>
            )}
          </div>
          <p className="text-sm text-text font-medium">{message}</p>
        </div>
      </div>

      {onRetry && (
        <div className="pt-2">
          <button
            type="button"
            onClick={onRetry}
            className="text-xs bg-surface-raised text-text hover:bg-surface border border-border px-3 py-1.5 rounded transition-colors"
          >
            Retry request
          </button>
        </div>
      )}
    </div>
  );
};
