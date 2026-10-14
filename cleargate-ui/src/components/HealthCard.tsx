import React from 'react';
import { HealthResponse } from '../api/schemas';
import { CheckCircle2, XCircle, Cpu, FileText, KeyRound, Server } from 'lucide-react';

interface HealthCardProps {
  health?: HealthResponse | null;
  isLoading?: boolean;
  error?: string | null;
}

export const HealthCard: React.FC<HealthCardProps> = ({
  health,
  isLoading,
  error,
}) => {
  if (isLoading) {
    return (
      <div className="bg-surface border border-border rounded-lg p-6 animate-pulse space-y-3">
        <div className="h-4 bg-surface-raised rounded w-1/3"></div>
        <div className="h-8 bg-surface-raised rounded"></div>
      </div>
    );
  }

  if (error || !health) {
    return (
      <div className="bg-status-failed-bg border border-status-failed/30 rounded-lg p-6 space-y-3 text-status-failed">
        <div className="flex items-center gap-2 font-semibold">
          <XCircle className="w-5 h-5 shrink-0" />
          <span>Backend service unreachable</span>
        </div>
        <p className="text-xs text-text-muted">
          Could not communicate with the ClearGate health endpoint. Verify backend is running at configured origin.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-surface border border-border rounded-lg p-6 space-y-4 shadow-card">
      <div className="flex items-center justify-between pb-3 border-b border-border">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-5 h-5 text-status-safe" />
          <h3 className="font-heading font-semibold text-text">Service Health Status</h3>
        </div>
        <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-status-safe-bg text-status-safe border border-status-safe/30">
          HEALTHY
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
        <div className="space-y-1">
          <div className="flex items-center gap-1.5 text-text-muted">
            <Server className="w-3.5 h-3.5 text-accent" />
            <span>Service</span>
          </div>
          <p className="font-medium text-text">{health.service || 'ClearGate Core'}</p>
        </div>

        <div className="space-y-1">
          <div className="flex items-center gap-1.5 text-text-muted">
            <Cpu className="w-3.5 h-3.5 text-accent" />
            <span>PII Model</span>
          </div>
          <p className="font-medium text-text">
            {health.model_loaded ? 'Loaded & Active' : 'Not loaded'}
          </p>
        </div>

        <div className="space-y-1">
          <div className="flex items-center gap-1.5 text-text-muted">
            <FileText className="w-3.5 h-3.5 text-accent" />
            <span>Tesseract OCR</span>
          </div>
          <p className="font-medium text-text">
            {health.tesseract_version || 'Not available'}
          </p>
        </div>

        <div className="space-y-1">
          <div className="flex items-center gap-1.5 text-text-muted">
            <KeyRound className="w-3.5 h-3.5 text-accent" />
            <span>Vault Key</span>
          </div>
          <p className="font-medium text-text">
            {health.vault_key_present ? 'Configured' : 'Missing'}
          </p>
        </div>
      </div>
    </div>
  );
};
