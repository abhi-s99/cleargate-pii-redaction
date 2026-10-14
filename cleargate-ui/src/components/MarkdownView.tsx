import React, { useState } from 'react';
import { Copy, Check, Download } from 'lucide-react';

interface MarkdownViewProps {
  content: string;
  onDownloadJson?: () => void;
  title?: string;
}

export const MarkdownView: React.FC<MarkdownViewProps> = ({
  content,
  onDownloadJson,
  title = 'Sanitized Report',
}) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Ignore clipboard write failure
    }
  };

  // Safe line-by-line renderer without dangerouslySetInnerHTML (Section 8: zero raw HTML, no external images)
  const renderSafeMarkdown = (text: string) => {
    const lines = text.split('\n');
    const elements: React.ReactNode[] = [];

    lines.forEach((line, index) => {
      const trimmed = line.trim();

      // Heading 1
      if (trimmed.startsWith('# ')) {
        elements.push(
          <h1 key={index} className="text-xl font-bold font-heading text-text mt-4 mb-2 pb-1 border-b border-border">
            {trimmed.substring(2)}
          </h1>
        );
      }
      // Heading 2
      else if (trimmed.startsWith('## ')) {
        elements.push(
          <h2 key={index} className="text-lg font-semibold font-heading text-text mt-3 mb-1">
            {trimmed.substring(3)}
          </h2>
        );
      }
      // Heading 3
      else if (trimmed.startsWith('### ')) {
        elements.push(
          <h3 key={index} className="text-base font-semibold text-text mt-2 mb-1">
            {trimmed.substring(4)}
          </h3>
        );
      }
      // Bullet list item
      else if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
        elements.push(
          <li key={index} className="ml-5 list-disc text-sm text-text-muted my-0.5">
            {trimmed.substring(2)}
          </li>
        );
      }
      // Horizontal rule
      else if (trimmed === '---') {
        elements.push(<hr key={index} className="my-4 border-border" />);
      }
      // Empty line
      else if (!trimmed) {
        elements.push(<div key={index} className="h-2" />);
      }
      // Paragraph
      else {
        elements.push(
          <p key={index} className="text-sm text-text-muted leading-relaxed font-sans">
            {trimmed}
          </p>
        );
      }
    });

    return elements;
  };

  return (
    <div className="bg-surface border border-border rounded-lg shadow-card overflow-hidden">
      <div className="p-4 bg-surface-raised border-b border-border flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text">{title}</h3>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleCopy}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-surface hover:bg-surface-raised border border-border text-text transition-colors"
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5 text-status-safe" />
                <span>Copied summary</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                <span>Copy summary</span>
              </>
            )}
          </button>

          {onDownloadJson && (
            <button
              type="button"
              onClick={onDownloadJson}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-accent hover:bg-accent-hover text-text-on-accent font-medium transition-colors"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Download JSON</span>
            </button>
          )}
        </div>
      </div>

      <div className="p-6 space-y-1 font-sans">{renderSafeMarkdown(content)}</div>
    </div>
  );
};
