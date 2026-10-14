import React from 'react';
import { TierLevel } from '../domain/states';

interface TierBadgeProps {
  tier: TierLevel | string;
}

export const TierBadge: React.FC<TierBadgeProps> = ({ tier }) => {
  const normalized = tier.toUpperCase();

  let styles = 'bg-surface text-text-muted border-border';

  switch (normalized) {
    case 'DETERMINISTIC':
      styles = 'bg-purple-950/40 text-purple-300 border-purple-800/40';
      break;
    case 'CORROBORATED':
      styles = 'bg-blue-950/40 text-blue-300 border-blue-800/40';
      break;
    case 'SINGLE_SIGNAL':
      styles = 'bg-amber-950/40 text-amber-300 border-amber-800/40';
      break;
    case 'LOW':
      styles = 'bg-slate-900 text-slate-400 border-slate-700';
      break;
  }

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-mono font-medium border ${styles}`}
      aria-label={`Detection tier: ${tier}`}
    >
      {normalized}
    </span>
  );
};
