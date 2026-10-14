import React from 'react';
import { Locator, formatLocator } from '../domain/locator';
import { MapPin } from 'lucide-react';

interface LocatorLabelProps {
  locator?: Locator;
}

export const LocatorLabel: React.FC<LocatorLabelProps> = ({ locator }) => {
  const formatted = formatLocator(locator);

  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs text-text-muted font-mono"
      title={locator ? JSON.stringify(locator) : undefined}
    >
      <MapPin className="w-3.5 h-3.5 text-accent shrink-0" aria-hidden="true" />
      <span>{formatted}</span>
    </span>
  );
};
