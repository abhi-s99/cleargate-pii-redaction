import React, { useState, useRef } from 'react';
import { UploadCloud, File, X, AlertTriangle, AlertCircle } from 'lucide-react';

const SUPPORTED_EXTENSIONS = [
  '.pdf',
  '.docx',
  '.pptx',
  '.png',
  '.jpg',
  '.jpeg',
  '.tif',
  '.tiff',
];

const BLOCKED_LEGACY_EXTENSIONS = ['.doc', '.ppt', '.docm', '.pptm'];

const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024; // 50 MB
const MAX_BATCH_FILES = 20;

interface FileDropzoneProps {
  files: File[];
  onFilesChange: (files: File[]) => void;
  disabled?: boolean;
}

export const FileDropzone: React.FC<FileDropzoneProps> = ({
  files,
  onFilesChange,
  disabled = false,
}) => {
  const [isDragOver, setIsDragOver] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const getFileExtension = (name: string): string => {
    const idx = name.lastIndexOf('.');
    return idx !== -1 ? name.substring(idx).toLowerCase() : '';
  };

  const handleIncomingFiles = (incomingList: FileList | File[]) => {
    setErrorMessage(null);
    const incoming = Array.from(incomingList);
    const validToAdd: File[] = [];

    for (const file of incoming) {
      const ext = getFileExtension(file.name);

      // Check blocked legacy extensions per Section 3 & 5.2
      if (BLOCKED_LEGACY_EXTENSIONS.includes(ext)) {
        setErrorMessage(
          `File "${file.name}" is not supported: please save legacy formats as .docx or .pptx before uploading.`
        );
        continue;
      }

      // Check allowlist
      if (!SUPPORTED_EXTENSIONS.includes(ext)) {
        setErrorMessage(
          `File "${file.name}" has an unsupported format. Supported formats: .pdf, .docx, .pptx, .png, .jpg, .tif.`
        );
        continue;
      }

      // Check 50 MB limit
      if (file.size > MAX_FILE_SIZE_BYTES) {
        setErrorMessage(
          `File "${file.name}" exceeds the 50 MB size limit (${formatFileSize(file.size)}).`
        );
        continue;
      }

      validToAdd.push(file);
    }

    // Check batch file count limit
    const totalCount = files.length + validToAdd.length;
    if (totalCount > MAX_BATCH_FILES) {
      setErrorMessage(
        `Batch limit exceeded: maximum ${MAX_BATCH_FILES} files allowed per batch. Currently ${totalCount}.`
      );
      const remainingSlots = Math.max(0, MAX_BATCH_FILES - files.length);
      onFilesChange([...files, ...validToAdd.slice(0, remainingSlots)]);
      return;
    }

    // Only invoke onChange when new valid files are added
    if (validToAdd.length > 0) {
      onFilesChange([...files, ...validToAdd]);
    }
  };

  const removeFile = (index: number) => {
    onFilesChange(files.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-4">
      {/* Drop zone container */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setIsDragOver(true);
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragOver(false);
          if (!disabled && e.dataTransfer.files) {
            handleIncomingFiles(e.dataTransfer.files);
          }
        }}
        onClick={() => {
          if (!disabled && fileInputRef.current) {
            fileInputRef.current.click();
          }
        }}
        className={`border-2 border-dashed rounded-lg p-8 sm:p-12 text-center cursor-pointer transition-all duration-200 ${
          isDragOver
            ? 'border-accent bg-accent/10 scale-[0.99]'
            : 'border-border hover:border-accent/60 bg-surface/50 hover:bg-surface'
        } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-label="Upload files dropzone"
        onKeyDown={(e) => {
          if (!disabled && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            fileInputRef.current?.click();
          }
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.pptx,.png,.jpg,.jpeg,.tif,.tiff"
          className="hidden"
          disabled={disabled}
          onChange={(e) => {
            if (e.target.files) {
              handleIncomingFiles(e.target.files);
              e.target.value = ''; // Reset for re-selection
            }
          }}
        />

        <div className="flex flex-col items-center justify-center space-y-3">
          <div className="w-14 h-14 rounded-full bg-surface-raised flex items-center justify-center text-accent shadow-inner">
            <UploadCloud className="w-7 h-7" />
          </div>

          <div>
            <p className="text-base font-semibold text-text">
              Drag & drop document files here, or <span className="text-link underline">browse</span>
            </p>
            <p className="text-xs text-text-muted mt-1.5">
              Supported: .pdf, .docx, .pptx, images (PNG/JPG/TIFF) · Max 50 MB each · Up to 20 files per batch
            </p>
          </div>
        </div>
      </div>

      {/* Validation warning/error */}
      {errorMessage && (
        <div
          className="p-3 rounded-md bg-status-failed-bg text-status-failed border border-status-failed/30 text-xs flex items-start gap-2"
          role="alert"
        >
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* File queue list */}
      {files.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-text-muted px-1">
            <span>Selected Files ({files.length} / {MAX_BATCH_FILES})</span>
            <button
              type="button"
              onClick={() => onFilesChange([])}
              className="hover:text-text underline text-xs"
            >
              Clear all
            </button>
          </div>

          <div className="divide-y divide-border border border-border rounded-md bg-surface overflow-hidden">
            {files.map((file, idx) => (
              <div
                key={`${file.name}-${idx}`}
                className="p-3 flex items-center justify-between gap-4 text-sm hover:bg-surface-raised transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <File className="w-4 h-4 text-accent shrink-0" />
                  <div className="truncate">
                    <p className="font-medium text-text truncate">{file.name}</p>
                    <p className="text-xs text-text-muted">{formatFileSize(file.size)}</p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => removeFile(idx)}
                  className="p-1 text-text-muted hover:text-status-failed rounded transition-colors"
                  aria-label={`Remove file ${file.name}`}
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Note about rejected legacy formats */}
      <div className="text-[11px] text-text-muted flex items-center gap-1.5 px-1">
        <AlertTriangle className="w-3.5 h-3.5 text-text-muted shrink-0" />
        <span>
          Legacy formats (.doc, .ppt, .docm, .pptm) and password-protected files are rejected by the privacy engine.
        </span>
      </div>
    </div>
  );
};
