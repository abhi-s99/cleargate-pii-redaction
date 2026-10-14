import React from 'react';
import { RiskLevel } from '../domain/states';
import { AlertCircle, AlertTriangle, ShieldCheck } from 'lucide-react';

interface RiskBadgeProps {
  risk: RiskLevel | string;
}

export const RiskBadge: React.FC<RiskBadgeProps> = ({ risk }) => {
  const normalized = risk.toUpperCase();

  let colorClasses = 'bg-surface text-text-muted border-border';
  let Icon = ShieldCheck;

  if (normalized === 'HIGH') {
    colorClasses = 'bg-status-failed-bg text-status-failed border-status-failed/30';
    Icon = AlertCircle;
  } else if (normalized === 'MEDIUM') {
    colorClasses = 'bg-status-review-bg text-status-review border-status-review/30';
    Icon = AlertTriangle;
  } else if (normalized === 'LOW') {
    colorClasses = 'bg-status-safe-bg text-status-safe border-status-safe/30';
    Icon = ShieldCheck;
  }

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold border ${colorClasses}`}
      aria-label={`Risk level: ${risk}`}
    >
      <Icon className="w-3 h-3" aria-hidden="true" />
      <span>{normalized}</span>
    </span>
  );
};
