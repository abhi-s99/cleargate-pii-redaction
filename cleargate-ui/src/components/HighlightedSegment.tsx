import React from 'react';

interface HighlightedSegmentProps {
  text?: string;
  start?: number;
  end?: number;
  entityType?: string;
  token?: string;
  onTextSelection?: (selectedText: string, startOffset: number, endOffset: number) => void;
}

export const HighlightedSegment: React.FC<HighlightedSegmentProps> = ({
  text,
  start,
  end,
  token,
  onTextSelection,
}) => {
  if (!text) {
    return (
      <div className="p-4 rounded bg-surface border border-border text-xs text-text-muted italic">
        Full segment text not provided or restricted by privacy policy.
      </div>
    );
  }

  const handleMouseUp = () => {
    if (!onTextSelection) return;
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) return;

    const selectedString = selection.toString().trim();
    if (selectedString) {
      // Find offset in full text
      const idx = text.indexOf(selectedString);
      if (idx !== -1) {
        onTextSelection(selectedString, idx, idx + selectedString.length);
      }
    }
  };

  const hasValidSpan =
    start !== undefined &&
    end !== undefined &&
    start >= 0 &&
    end <= text.length &&
    start < end;

  if (!hasValidSpan) {
    return (
      <div
        onMouseUp={handleMouseUp}
        className="p-4 rounded bg-bg-alt border border-border font-mono text-xs leading-relaxed text-text select-text"
      >
        {text}
      </div>
    );
  }

  const beforeSpan = text.slice(0, start);
  const targetSpan = text.slice(start, end);
  const afterSpan = text.slice(end);

  return (
    <div
      onMouseUp={handleMouseUp}
      className="p-4 rounded bg-bg-alt border border-border font-mono text-xs leading-relaxed text-text select-text whitespace-pre-wrap"
    >
      <span>{beforeSpan}</span>
      <mark
        className="bg-accent/30 text-text border border-accent/60 px-1 py-0.5 rounded font-semibold relative inline-block mx-0.5"
        title={token ? `Target token: ${token}` : 'Target PII finding'}
      >
        {targetSpan}
        {token && (
          <span className="ml-1 text-[10px] text-accent font-normal underline">
            {token}
          </span>
        )}
      </mark>
      <span>{afterSpan}</span>
    </div>
  );
};
