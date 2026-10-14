import React from 'react';
import { getStateUiConfig } from '../domain/stateUi';
import {
  Clock,
  Loader2,
  AlertTriangle,
  ShieldAlert,
  ShieldX,
  ShieldCheck,
  HelpCircle,
} from 'lucide-react';

interface StateBadgeProps {
  state?: string;
  size?: 'sm' | 'md' | 'lg';
}

export const StateBadge: React.FC<StateBadgeProps> = ({ state, size = 'md' }) => {
  const config = getStateUiConfig(state);

  const renderIcon = () => {
    const iconClass = size === 'sm' ? 'w-3 h-3' : size === 'lg' ? 'w-4 h-4' : 'w-3.5 h-3.5';
    switch (config.iconType) {
      case 'clock':
        return <Clock className={iconClass} aria-hidden="true" />;
      case 'spinner':
        return <Loader2 className={`${iconClass} animate-spin`} aria-hidden="true" />;
      case 'alert-triangle':
        return <AlertTriangle className={iconClass} aria-hidden="true" />;
      case 'shield-alert':
        return <ShieldAlert className={iconClass} aria-hidden="true" />;
      case 'shield-x':
        return <ShieldX className={iconClass} aria-hidden="true" />;
      case 'shield-check':
        return <ShieldCheck className={iconClass} aria-hidden="true" />;
      default:
        return <HelpCircle className={iconClass} aria-hidden="true" />;
    }
  };

  const sizeClass =
    size === 'sm'
      ? 'px-2 py-0.5 text-xs'
      : size === 'lg'
      ? 'px-3 py-1.5 text-sm font-semibold'
      : 'px-2.5 py-1 text-xs font-medium';

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border ${config.badgeClass} ${sizeClass}`}
      role="status"
      aria-label={`Status: ${config.badgeLabel}`}
    >
      {renderIcon()}
      <span>{config.badgeLabel}</span>
    </span>
  );
};
