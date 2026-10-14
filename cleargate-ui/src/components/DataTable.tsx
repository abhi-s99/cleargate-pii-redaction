import React, { useState, useMemo, useRef, useEffect } from 'react';
import { Finding } from '../api/schemas';
import { EntityTypeChip } from './EntityTypeChip';
import { RiskBadge } from './RiskBadge';
import { TierBadge } from './TierBadge';
import { LocatorLabel } from './LocatorLabel';
import { Search, Filter } from 'lucide-react';

interface DataTableProps {
  findings: Finding[];
  isLoading?: boolean;
}

export const DataTable: React.FC<DataTableProps> = ({ findings, isLoading }) => {
  const [filterType, setFilterType] = useState<string>('ALL');
  const [filterRisk, setFilterRisk] = useState<string>('ALL');
  const [filterTier, setFilterTier] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState('');

  // Extract unique filter options
  const uniqueTypes = useMemo(() => {
    return Array.from(new Set(findings.map((f) => f.entity_type))).sort();
  }, [findings]);

  const filteredFindings = useMemo(() => {
    return findings.filter((f) => {
      if (filterType !== 'ALL' && f.entity_type !== filterType) return false;
      if (filterRisk !== 'ALL' && f.risk !== filterRisk) return false;
      if (filterTier !== 'ALL' && f.tier !== filterTier) return false;
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase();
        const matchesPreview = f.preview.toLowerCase().includes(query);
        const matchesToken = f.token?.toLowerCase().includes(query) ?? false;
        const matchesType = f.entity_type.toLowerCase().includes(query);
        if (!matchesPreview && !matchesToken && !matchesType) return false;
      }
      return true;
    });
  }, [findings, filterType, filterRisk, filterTier, searchQuery]);

  // Virtualized row rendering logic (ASSUMPTION[A-6]: handles large datasets smoothly)
  const containerRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const rowHeight = 64; // Row height in px
  const containerHeight = 480;

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop);
  };

  useEffect(() => {
    // Reset scroll on filter change
    if (containerRef.current) {
      containerRef.current.scrollTop = 0;
      setScrollTop(0);
    }
  }, [filterType, filterRisk, filterTier, searchQuery]);

  const totalRows = filteredFindings.length;
  const startIndex = Math.max(0, Math.floor(scrollTop / rowHeight) - 2);
  const visibleCount = Math.ceil(containerHeight / rowHeight) + 4;
  const endIndex = Math.min(totalRows, startIndex + visibleCount);
  const visibleRows = filteredFindings.slice(startIndex, endIndex);
  const offsetY = startIndex * rowHeight;
  const totalHeight = totalRows * rowHeight;

  if (isLoading) {
    return (
      <div className="p-8 text-center bg-surface border border-border rounded-lg animate-pulse text-text-muted">
        Loading findings data...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Table filter controls */}
      <div className="bg-surface border border-border rounded-lg p-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-2 flex-1 min-w-[200px] max-w-sm">
          <div className="relative w-full">
            <Search className="w-4 h-4 text-text-muted absolute left-3 top-2.5" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search masked preview or token..."
              className="w-full pl-9 pr-3 py-1.5 bg-bg-alt border border-border rounded text-xs text-text focus:ring-1 focus:ring-focus-ring"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 text-xs">
          <div className="flex items-center gap-1 text-text-muted">
            <Filter className="w-3.5 h-3.5 text-accent" />
            <span>Filters:</span>
          </div>

          {/* Type filter */}
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="bg-bg-alt border border-border rounded px-2.5 py-1 text-text text-xs"
          >
            <option value="ALL">All Entity Types ({uniqueTypes.length})</option>
            {uniqueTypes.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>

          {/* Risk filter */}
          <select
            value={filterRisk}
            onChange={(e) => setFilterRisk(e.target.value)}
            className="bg-bg-alt border border-border rounded px-2.5 py-1 text-text text-xs"
          >
            <option value="ALL">All Risks</option>
            <option value="HIGH">HIGH</option>
            <option value="MEDIUM">MEDIUM</option>
            <option value="LOW">LOW</option>
          </select>

          {/* Tier filter */}
          <select
            value={filterTier}
            onChange={(e) => setFilterTier(e.target.value)}
            className="bg-bg-alt border border-border rounded px-2.5 py-1 text-text text-xs"
          >
            <option value="ALL">All Tiers</option>
            <option value="DETERMINISTIC">DETERMINISTIC</option>
            <option value="CORROBORATED">CORROBORATED</option>
            <option value="SINGLE_SIGNAL">SINGLE_SIGNAL</option>
            <option value="LOW">LOW</option>
          </select>
        </div>
      </div>

      {/* Virtualized data table container */}
      <div className="bg-surface border border-border rounded-lg shadow-card overflow-hidden">
        {/* Table header */}
        <div className="grid grid-cols-12 gap-3 px-4 py-3 bg-surface-raised border-b border-border text-xs font-semibold text-text uppercase tracking-wider">
          <div className="col-span-3">Entity Type</div>
          <div className="col-span-2">Risk & Tier</div>
          <div className="col-span-3">Masked Preview</div>
          <div className="col-span-2">Location</div>
          <div className="col-span-2">Token & Detector</div>
        </div>

        {totalRows === 0 ? (
          <div className="p-8 text-center text-xs text-text-muted">
            No findings match the current filter criteria.
          </div>
        ) : (
          <div
            ref={containerRef}
            onScroll={handleScroll}
            style={{ height: `${containerHeight}px`, overflowY: 'auto' }}
            className="relative divide-y divide-border"
          >
            <div style={{ height: `${totalHeight}px`, width: '100%', position: 'relative' }}>
              <div
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${offsetY}px)`,
                }}
              >
                {visibleRows.map((finding) => (
                  <div
                    key={finding.finding_id}
                    style={{ height: `${rowHeight}px` }}
                    className="grid grid-cols-12 gap-3 px-4 py-2.5 items-center hover:bg-surface-raised transition-colors border-b border-border text-xs"
                  >
                    <div className="col-span-3 truncate">
                      <EntityTypeChip entityType={finding.entity_type} />
                      <span className="font-mono text-[10px] text-text-muted block mt-0.5">
                        {finding.finding_id}
                      </span>
                    </div>

                    <div className="col-span-2 flex flex-col gap-1">
                      <div>
                        <RiskBadge risk={finding.risk} />
                      </div>
                      <div>
                        <TierBadge tier={finding.tier} />
                      </div>
                    </div>

                    <div className="col-span-3 truncate">
                      {/* Section 8: Masked preview only, never raw values */}
                      <span className="font-mono text-text bg-bg-alt px-2 py-1 rounded border border-border/80 inline-block truncate max-w-full">
                        {finding.preview}
                      </span>
                    </div>

                    <div className="col-span-2">
                      <LocatorLabel locator={finding.locator} />
                    </div>

                    <div className="col-span-2 truncate space-y-0.5">
                      <span className="font-mono text-[11px] text-accent block font-medium">
                        {finding.token || '-'}
                      </span>
                      <span className="text-[10px] text-text-muted truncate block">
                        {finding.evidence?.[0]?.detector || '-'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        <div className="px-4 py-2.5 bg-surface-raised border-t border-border flex items-center justify-between text-xs text-text-muted">
          <span>
            Showing {filteredFindings.length} of {findings.length} findings
          </span>
          <span className="font-mono text-[11px]">Preview data masked by server</span>
        </div>
      </div>
    </div>
  );
};
