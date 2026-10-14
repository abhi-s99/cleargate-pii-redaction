import React, { useEffect, useState } from 'react';

interface StatCounterProps {
  value: number;
  label: string;
  helper?: string;
  icon?: React.ReactNode;
}

export const StatCounter: React.FC<StatCounterProps> = ({
  value,
  label,
  helper,
  icon,
}) => {
  const [displayCount, setDisplayCount] = useState(value);

  useEffect(() => {
    // Respect prefers-reduced-motion
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setDisplayCount(value);
      return;
    }

    let start = 0;
    const duration = 600;
    const steps = 20;
    const increment = value / steps;
    const stepTime = duration / steps;

    const timer = setInterval(() => {
      start += increment;
      if (start >= value) {
        setDisplayCount(value);
        clearInterval(timer);
      } else {
        setDisplayCount(Math.floor(start));
      }
    }, stepTime);

    return () => clearInterval(timer);
  }, [value]);

  return (
    <div className="bg-surface border border-border rounded-lg p-5 flex flex-col justify-between shadow-card">
      <div className="flex items-center justify-between text-text-muted mb-2">
        <span className="text-xs font-semibold uppercase tracking-wider">{label}</span>
        {icon && <div className="text-accent">{icon}</div>}
      </div>

      <div className="text-3xl font-heading font-bold text-text">
        {displayCount}
      </div>

      {helper && (
        <p className="text-xs text-text-muted mt-2 border-t border-border/50 pt-2">
          {helper}
        </p>
      )}
    </div>
  );
};
