import React from 'react';
import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';

interface InsightCardProps {
  category: string;
  title: string;
  blurb: string;
  ctaText?: string;
  ctaHref?: string;
  onClick?: () => void;
  icon?: React.ReactNode;
}

export const InsightCard: React.FC<InsightCardProps> = ({
  category,
  title,
  blurb,
  ctaText = 'Learn more',
  ctaHref,
  onClick,
  icon,
}) => {
  const content = (
    <div className="bg-surface hover:bg-surface-raised border border-border hover:border-accent hover:shadow-lg transition-all duration-200 rounded-lg p-6 flex flex-col justify-between h-full group shadow-card">
      <div>
        <div className="flex items-center justify-between mb-3">
          <span className="text-[11px] font-mono uppercase tracking-wider text-accent font-semibold">
            {category}
          </span>
          {icon && <div className="text-text-muted group-hover:text-accent transition-colors">{icon}</div>}
        </div>
        <h3 className="font-heading font-bold text-lg text-text group-hover:text-accent transition-colors mb-2">
          {title}
        </h3>
        <p className="text-sm text-text-muted leading-relaxed">
          {blurb}
        </p>
      </div>

      <div className="pt-6 mt-4 border-t border-border/40 flex items-center text-sm font-semibold text-accent group-hover:text-accent-hover">
        <span>{ctaText}</span>
        <ArrowRight className="w-4 h-4 ml-1.5 transition-transform group-hover:translate-x-1" />
      </div>
    </div>
  );

  if (ctaHref) {
    if (ctaHref.startsWith('http')) {
      return (
        <a href={ctaHref} target="_blank" rel="noreferrer" className="block h-full">
          {content}
        </a>
      );
    }
    return (
      <Link to={ctaHref} className="block h-full">
        {content}
      </Link>
    );
  }

  if (onClick) {
    return (
      <button type="button" onClick={onClick} className="block w-full text-left h-full">
        {content}
      </button>
    );
  }

  return <div>{content}</div>;
};
