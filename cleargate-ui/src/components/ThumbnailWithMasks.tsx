import React, { useState } from 'react';
import { EyeOff, BoxSelect } from 'lucide-react';

interface ThumbnailWithMasksProps {
  thumbnailUrl?: string;
  thumbnailData?: string;
  bbox?: number[];
  page?: number;
  onRegionSelected?: (bbox: [number, number, number, number]) => void;
}

export const ThumbnailWithMasks: React.FC<ThumbnailWithMasksProps> = ({
  thumbnailUrl,
  thumbnailData,
  onRegionSelected,
}) => {
  const [drawingBox, setDrawingBox] = useState<boolean>(false);
  const [boxCoord, setBoxCoord] = useState<[number, number, number, number] | null>(null);

  const imageSrc = thumbnailData || thumbnailUrl;

  if (!imageSrc) {
    return (
      <div className="h-48 rounded bg-surface border border-border flex flex-col items-center justify-center text-text-muted space-y-2 p-4 text-center">
        <EyeOff className="w-8 h-8 opacity-40" />
        <span className="text-xs">Preview not provided by server</span>
        <span className="text-[10px] text-text-muted">
          Raster imagery is available only when visual detectors or OCR generate candidate masks.
        </span>
      </div>
    );
  }

  const handleSimulateBoxDraw = () => {
    // Generate sample user-drawn bounding box [x1, y1, x2, y2]
    const sampleBox: [number, number, number, number] = [80, 120, 220, 180];
    setBoxCoord(sampleBox);
    setDrawingBox(true);
    if (onRegionSelected) {
      onRegionSelected(sampleBox);
    }
  };

  return (
    <div className="space-y-2">
      <div className="relative border border-border rounded-lg overflow-hidden bg-bg-alt flex items-center justify-center p-2">
        <img
          src={imageSrc}
          alt="Slide or document page raster thumbnail preview"
          className="max-h-64 object-contain rounded"
        />

        {drawingBox && boxCoord && (
          <div
            className="absolute border-2 border-dashed border-status-review bg-status-review/20 pointer-events-none rounded"
            style={{
              left: `${boxCoord[0]}px`,
              top: `${boxCoord[1]}px`,
              width: `${boxCoord[2] - boxCoord[0]}px`,
              height: `${boxCoord[3] - boxCoord[1]}px`,
            }}
          >
            <span className="text-[9px] font-mono text-status-review bg-bg-alt/90 px-1 py-0.5 rounded absolute -top-4 left-0">
              User Mask [{boxCoord.join(',')}]
            </span>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between text-xs text-text-muted px-1">
        <span>Page Thumbnail (Proposed masks overlaid)</span>
        <button
          type="button"
          onClick={handleSimulateBoxDraw}
          className="text-link hover:underline flex items-center gap-1 text-[11px]"
        >
          <BoxSelect className="w-3.5 h-3.5" />
          <span>Draw mask region</span>
        </button>
      </div>
    </div>
  );
};
