import React from 'react';
import { ArrowDown, Shield, FileCheck } from 'lucide-react';
import { Link } from 'react-router-dom';

interface PageHeroProps {
  headline?: string;
  supportingLine?: string;
  onPrimaryCtaClick?: () => void;
}

export const PageHero: React.FC<PageHeroProps> = ({
  headline = 'Nothing reaches the AI unless it is proven safe.',
  supportingLine = 'ClearGate extracts, redacts and independently verifies your documents, then lets them through only when it can show they are safe.',
  onPrimaryCtaClick,
}) => {
  return (
    <header className="bg-hero-bg text-hero-text border-b border-border py-16 lg:py-24 relative overflow-hidden">
      {/* Subtle tech background grid effect */}
      <div
        className="absolute inset-0 opacity-[0.03] pointer-events-none"
        style={{
          backgroundImage:
            'radial-gradient(var(--accent) 1px, transparent 1px), radial-gradient(var(--accent) 1px, var(--hero-bg) 1px)',
          backgroundSize: '40px 40px',
        }}
        aria-hidden="true"
      />

      <div className="max-w-container mx-auto px-4 sm:px-6 relative z-10">
        <div className="max-w-3xl space-y-6">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-neutral-900 border border-neutral-700 text-xs font-mono text-blue-400">
            <Shield className="w-3.5 h-3.5" />
            <span>Deterministic Privacy Isolation Engine</span>
          </div>

          <h1 className="font-heading font-extrabold text-3xl sm:text-4xl lg:text-5xl tracking-tight text-hero-text leading-[1.15]">
            {headline}
          </h1>

          <p className="text-base sm:text-lg text-gray-300 leading-relaxed font-normal max-w-2xl">
            {supportingLine}
          </p>

          <div className="pt-4 flex flex-wrap items-center gap-4">
            <button
              type="button"
              onClick={onPrimaryCtaClick}
              className="bg-accent hover:bg-accent-hover text-text-on-accent font-semibold px-6 py-3 rounded-md transition-all shadow-lg flex items-center gap-2 focus:ring-2 focus:ring-focus-ring"
            >
              <FileCheck className="w-4 h-4" />
              <span>Upload document batch</span>
              <ArrowDown className="w-4 h-4 ml-1" />
            </button>

            <Link
              to="/how-it-works"
              className="bg-neutral-900 hover:bg-neutral-800 text-white border border-neutral-700 font-medium px-5 py-3 rounded-md transition-colors text-sm"
            >
              See how the privacy gate works
            </Link>
          </div>
        </div>
      </div>
    </header>
  );
};
