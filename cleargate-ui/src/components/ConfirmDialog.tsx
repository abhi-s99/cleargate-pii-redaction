import React, { useEffect, useRef } from 'react';
import { AlertTriangle, X } from 'lucide-react';

interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  isDestructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: React.ReactNode;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  isOpen,
  title,
  message,
  confirmLabel = 'Confirm Action',
  cancelLabel = 'Cancel',
  isDestructive = false,
  onConfirm,
  onCancel,
  children,
}) => {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onCancel]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="dialog-title"
    >
      <div
        ref={dialogRef}
        className="bg-surface border border-border rounded-lg max-w-md w-full p-6 space-y-4 shadow-2xl animate-in fade-in zoom-in-95 duration-150"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
                isDestructive
                  ? 'bg-status-failed-bg text-status-failed'
                  : 'bg-status-review-bg text-status-review'
              }`}
            >
              <AlertTriangle className="w-4 h-4" />
            </div>
            <h3 id="dialog-title" className="font-heading font-bold text-base text-text">
              {title}
            </h3>
          </div>

          <button
            type="button"
            onClick={onCancel}
            className="text-text-muted hover:text-text p-1 rounded transition-colors"
            aria-label="Close dialog"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <p className="text-xs text-text-muted leading-relaxed">{message}</p>

        {children && <div className="pt-1">{children}</div>}

        <div className="flex items-center justify-end gap-3 pt-4 border-t border-border">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 rounded text-xs font-medium text-text-muted hover:text-text hover:bg-surface-raised transition-colors border border-border"
          >
            {cancelLabel}
          </button>

          <button
            type="button"
            onClick={onConfirm}
            className={`px-4 py-2 rounded text-xs font-semibold text-text-on-accent transition-colors shadow ${
              isDestructive
                ? 'bg-status-failed hover:bg-status-failed/90'
                : 'bg-accent hover:bg-accent-hover'
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
};
