import React from 'react';
import { AlertCircle, HelpCircle } from 'lucide-react';

interface EmptyStateProps {
  title: string;
  description: string;
  actionText?: string;
  onAction?: () => void;
  icon?: React.ReactNode;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  actionText,
  onAction,
  icon,
}) => {
  return (
    <div className="bg-surface border border-border rounded-lg p-12 text-center flex flex-col items-center justify-center space-y-4">
      <div className="w-12 h-12 rounded-full bg-surface-raised flex items-center justify-center text-text-muted">
        {icon || <HelpCircle className="w-6 h-6" />}
      </div>
      <div className="max-w-md space-y-1">
        <h3 className="font-heading font-semibold text-text text-base">{title}</h3>
        <p className="text-sm text-text-muted leading-relaxed">{description}</p>
      </div>
      {actionText && onAction && (
        <button
          type="button"
          onClick={onAction}
          className="bg-accent hover:bg-accent-hover text-text-on-accent text-sm font-medium px-4 py-2 rounded-md transition-colors"
        >
          {actionText}
        </button>
      )}
    </div>
  );
};

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
