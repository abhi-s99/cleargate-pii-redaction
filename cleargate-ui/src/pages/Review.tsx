import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useReviewItemsQuery } from '../api/queries';
import { api, ApiError } from '../api/client';
import { useAuth } from '../app/AuthContext';
import { LocalDecision } from '../api/adapters';
import { ALL_KNOWN_ENTITY_TYPES } from '../domain/entityLabels';
import { EntityTypeChip } from '../components/EntityTypeChip';
import { RiskBadge } from '../components/RiskBadge';
import { TierBadge } from '../components/TierBadge';
import { LocatorLabel } from '../components/LocatorLabel';
import { HighlightedSegment } from '../components/HighlightedSegment';
import { ThumbnailWithMasks } from '../components/ThumbnailWithMasks';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { ErrorPanel } from '../components/ErrorPanel';
import {
  Check,
  X,
  Tag,
  Square,
  FileX,
  Keyboard,
  Send,
  HelpCircle,
  ArrowLeft,
  Loader2,
} from 'lucide-react';

export const ReviewPage: React.FC = () => {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const { role, isAuthenticated } = useAuth();

  const {
    data: reviewItems = [],
    isLoading,
    error: reviewError,
    refetch,
  } = useReviewItemsQuery(jobId);

  // Queue state
  const [selectedIndex, setSelectedIndex] = useState(0);
  // Decisions map: finding_id -> LocalDecision
  const [decisions, setDecisions] = useState<Record<string, LocalDecision>>({});

  // Action UI Modals & Inputs
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [rejectJustification, setRejectJustification] = useState('');
  const [showRetypeDropdown, setShowRetypeDropdown] = useState(false);

  const [showAddSpanModal, setShowAddSpanModal] = useState(false);
  const [selectedSpanRange, setSelectedSpanRange] = useState<{
    text: string;
    start: number;
    end: number;
  } | null>(null);
  const [addSpanType, setAddSpanType] = useState('PERSON');

  const [showAddRegionModal, setShowAddRegionModal] = useState(false);
  const [drawnBbox, setDrawnBbox] = useState<number[]>([50, 50, 200, 200]);

  const [showRejectDocDialog, setShowRejectDocDialog] = useState(false);
  const [rejectDocReason, setRejectDocReason] = useState('');

  const [showSubmitConfirmDialog, setShowSubmitConfirmDialog] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const currentItem = reviewItems[selectedIndex];

  // Rule: Reject is strictly FORBIDDEN on findings that are risk=HIGH and tier=DETERMINISTIC
  const isHighDeterministic =
    currentItem?.risk === 'HIGH' && currentItem?.tier === 'DETERMINISTIC';

  // Record a decision for the current finding
  const recordDecision = useCallback((decision: LocalDecision) => {
    if (!currentItem) return;
    setDecisions((prev) => ({
      ...prev,
      [currentItem.finding_id]: {
        ...decision,
        finding_id: currentItem.finding_id,
      },
    }));
  }, [currentItem]);

  const handleConfirm = useCallback(() => {
    recordDecision({ action: 'confirm' });
    if (selectedIndex < reviewItems.length - 1) {
      setSelectedIndex((prev) => prev + 1);
    }
  }, [recordDecision, selectedIndex, reviewItems.length]);

  const handleOpenReject = useCallback(() => {
    if (isHighDeterministic) return;
    setRejectJustification('');
    setShowRejectModal(true);
  }, [isHighDeterministic]);

  const handleApplyReject = () => {
    if (!rejectJustification.trim()) return;
    recordDecision({
      action: 'reject',
      justification: rejectJustification.trim(),
    });
    setShowRejectModal(false);
    if (selectedIndex < reviewItems.length - 1) {
      setSelectedIndex((prev) => prev + 1);
    }
  };

  const handleApplyRetype = (newType: string) => {
    recordDecision({
      action: 'retype',
      entity_type: newType,
    });
    setShowRetypeDropdown(false);
  };

  const handleApplyAddSpan = () => {
    if (!selectedSpanRange || !currentItem) return;
    recordDecision({
      action: 'add',
      segment_id: currentItem.segment_id,
      start: selectedSpanRange.start,
      end: selectedSpanRange.end,
      entity_type: addSpanType,
    });
    setShowAddSpanModal(false);
    setSelectedSpanRange(null);
  };

  const handleApplyAddRegion = () => {
    if (!currentItem) return;
    recordDecision({
      action: 'add_region',
      page: currentItem.locator?.page || 1,
      bbox: drawnBbox,
    });
    setShowAddRegionModal(false);
  };

  const handleApplyRejectDocument = () => {
    if (!rejectDocReason.trim()) return;
    recordDecision({
      action: 'reject_document',
      reason: rejectDocReason.trim(),
    });
    setShowRejectDocDialog(false);
  };

  // Keyboard navigation & quick actions: C, R, T, J, K (Section 5.5)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger shortcuts if user is typing in a textarea or input
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement)?.tagName)) {
        return;
      }

      switch (e.key.toUpperCase()) {
        case 'C':
          e.preventDefault();
          handleConfirm();
          break;
        case 'R':
          e.preventDefault();
          if (!isHighDeterministic) handleOpenReject();
          break;
        case 'T':
          e.preventDefault();
          setShowRetypeDropdown((prev) => !prev);
          break;
        case 'J':
          e.preventDefault();
          if (selectedIndex < reviewItems.length - 1) {
            setSelectedIndex((prev) => prev + 1);
          }
          break;
        case 'K':
          e.preventDefault();
          if (selectedIndex > 0) {
            setSelectedIndex((prev) => prev - 1);
          }
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleConfirm, handleOpenReject, isHighDeterministic, selectedIndex, reviewItems.length]);

  // Record "confirm" for every item the reviewer has not decided yet (keeps redactions).
  const handleConfirmAllRemaining = () => {
    setDecisions((prev) => {
      const next = { ...prev };
      for (const item of reviewItems) {
        if (!next[item.finding_id]) {
          next[item.finding_id] = { action: 'confirm', finding_id: item.finding_id };
        }
      }
      return next;
    });
  };

  // Submit all decisions in one POST /jobs/{id}/review
  const handleSubmitAllDecisions = async () => {
    if (!jobId) return;
    setIsSubmitting(true);
    setSubmitError(null);

    const decisionsList: LocalDecision[] = Object.values(decisions);

    try {
      await api.submitReviewDecisions(jobId, decisionsList);
      setShowSubmitConfirmDialog(false);
      // Navigate to Job Detail and resume automatic polling
      navigate(`/jobs/${jobId}`);
    } catch (e: unknown) {
      const err = e as ApiError;
      if (err.status === 409) {
        setSubmitError('This job is no longer awaiting review. Status was refreshed.');
        refetch();
      } else {
        setSubmitError(err.message || 'Failed to submit review decisions.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="max-w-container mx-auto px-4 sm:px-6 py-12 flex-1">
        <div className="p-8 text-center bg-surface border border-border rounded-lg animate-pulse text-text-muted">
          Loading review workspace queue...
        </div>
      </div>
    );
  }

  // Handle reviewer role restriction per Section 4 & Section 5
  if (role !== 'reviewer' || reviewError) {
    const errorMsg = !isAuthenticated
      ? 'Not connected. The token is forgotten on page reload unless "Keep token for this browser tab" was ticked; connect again with the reviewer token.'
      : reviewError
        ? reviewError.message
        : 'This token is not a reviewer token.';

    return (
      <div className="max-w-container mx-auto px-4 sm:px-6 py-12 flex-1">
        <ErrorPanel
          code="FORBIDDEN_REVIEWER_REQUIRED"
          message={errorMsg}
          endpoint="/jobs/{id}/review"
        />
        <div className="mt-4">
          <Link to="/connect" className="text-link text-sm hover:underline">
            &larr; Connect with a Reviewer Token
          </Link>
        </div>
      </div>
    );
  }

  if (reviewItems.length === 0) {
    return (
      <div className="max-w-container mx-auto px-4 sm:px-6 py-12 flex-1 text-center space-y-4">
        <div className="bg-surface border border-border rounded-lg p-10 max-w-lg mx-auto">
          <Check className="w-10 h-10 text-status-safe mx-auto mb-3" />
          <h2 className="text-xl font-heading font-bold text-text">No Open Review Items</h2>
          <p className="text-xs text-text-muted mt-2">
            All candidate findings for this document have either been resolved or this job is no longer in REVIEW_REQUIRED state.
          </p>
          <div className="mt-6">
            <Link
              to={`/jobs/${jobId}`}
              className="bg-accent text-text-on-accent text-xs font-semibold px-4 py-2 rounded-md"
            >
              Return to Job Detail
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const decidedCount = Object.keys(decisions).length;
  const currentDecision = currentItem ? decisions[currentItem.finding_id] : undefined;

  return (
    <div className="max-w-container mx-auto px-4 sm:px-6 py-6 flex-1 flex flex-col space-y-4">
      {/* Workspace Top Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border pb-4">
        <div>
          <div className="flex items-center gap-2 text-xs text-text-muted">
            <Link to={`/jobs/${jobId}`} className="hover:text-text flex items-center gap-1">
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to Job Detail</span>
            </Link>
            <span>/</span>
            <span className="font-mono text-accent">Review Workspace</span>
          </div>
          <h1 className="text-2xl font-heading font-bold text-text mt-1">
            Privacy Review Queue · {jobId}
          </h1>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs font-mono text-text-muted bg-surface border border-border px-3 py-1.5 rounded">
            Decided: {decidedCount} of {reviewItems.length}
          </span>

          {/* Convenience only: records "confirm" (keep the redaction) for every item not yet
              decided. The server still re-redacts and re-verifies before the gate decides. */}
          <button
            type="button"
            onClick={handleConfirmAllRemaining}
            disabled={isSubmitting || decidedCount === reviewItems.length}
            className="bg-surface border border-border hover:border-accent disabled:opacity-40 disabled:cursor-not-allowed text-text text-xs font-semibold px-3 py-2 rounded-md transition-colors"
          >
            Confirm all remaining
          </button>

          <button
            type="button"
            onClick={() => setShowSubmitConfirmDialog(true)}
            disabled={decidedCount === 0 || isSubmitting}
            className="bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-text-on-accent text-xs font-semibold px-4 py-2 rounded-md transition-colors flex items-center gap-1.5 shadow"
          >
            {isSubmitting ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Send className="w-3.5 h-3.5" />
            )}
            <span>Submit Decisions ({decidedCount})</span>
          </button>
        </div>
      </div>

      {submitError && (
        <div className="p-3 bg-status-failed-bg text-status-failed border border-status-failed/30 rounded text-xs">
          {submitError}
        </div>
      )}

      {/* Two-Pane Workspace Layout (Section 5.5) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 flex-1">
        {/* Left Pane: Queue of Open Items (col-span-4) */}
        <div className="lg:col-span-4 bg-surface border border-border rounded-lg shadow-card flex flex-col overflow-hidden max-h-[780px]">
          <div className="p-3.5 bg-surface-raised border-b border-border flex items-center justify-between">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-text">
              Candidate Queue ({reviewItems.length})
            </h2>
            <div className="flex items-center gap-1 text-[11px] text-text-muted font-mono">
              <Keyboard className="w-3.5 h-3.5 text-accent" />
              <span>J/K navigate</span>
            </div>
          </div>

          <div className="divide-y divide-border overflow-y-auto flex-1">
            {reviewItems.map((item, idx) => {
              const itemDecision = decisions[item.finding_id];
              const isSelected = idx === selectedIndex;

              return (
                <div
                  key={item.finding_id}
                  onClick={() => setSelectedIndex(idx)}
                  className={`p-3.5 cursor-pointer transition-colors text-xs space-y-2 ${
                    isSelected
                      ? 'bg-surface-raised border-l-4 border-l-accent'
                      : 'hover:bg-surface-raised/50 border-l-4 border-l-transparent'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <EntityTypeChip entityType={item.entity_type} />
                    <div className="flex items-center gap-1.5">
                      <RiskBadge risk={item.risk} />
                      <TierBadge tier={item.tier} />
                    </div>
                  </div>

                  <div className="font-mono text-text bg-bg-alt px-2 py-1 rounded border border-border/60 truncate">
                    {item.preview}
                  </div>

                  <div className="flex items-center justify-between text-[11px] text-text-muted pt-1">
                    <LocatorLabel locator={item.locator} />
                    {itemDecision ? (
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-status-safe-bg text-status-safe border border-status-safe/30 capitalize">
                        {itemDecision.action}
                      </span>
                    ) : (
                      <span className="text-[10px] text-text-muted font-mono">Undecided</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Pane: Item Detail & Resolution Tools (col-span-8) */}
        {currentItem && (
          <div className="lg:col-span-8 bg-surface border border-border rounded-lg shadow-card p-6 flex flex-col justify-between space-y-6">
            <div className="space-y-6">
              {/* Header with Type & Locators */}
              <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-border">
                <div className="flex items-center gap-3">
                  <EntityTypeChip entityType={currentItem.entity_type} />
                  <RiskBadge risk={currentItem.risk} />
                  <TierBadge tier={currentItem.tier} />
                  {currentItem.format_invalid && (
                    <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-status-review-bg text-status-review border border-status-review/30">
                      FORMAT_INVALID
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-xs text-text-muted font-mono">
                    Token: <strong className="text-accent">{currentItem.proposed_token || currentItem.token || '-'}</strong>
                  </span>
                </div>
              </div>

              {/* Full Segment Text with Highlighted Span (Section 5.5 #2) */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold uppercase tracking-wider text-text">
                    Document Text Segment (Span Highlighted)
                  </label>
                  <span className="text-[11px] text-text-muted">
                    Highlight extra text to add custom span
                  </span>
                </div>

                <HighlightedSegment
                  text={currentItem.segment_text}
                  start={currentItem.start}
                  end={currentItem.end}
                  token={currentItem.proposed_token || currentItem.token}
                  onTextSelection={(selectedText, s, e) => {
                    setSelectedSpanRange({ text: selectedText, start: s, end: e });
                    setShowAddSpanModal(true);
                  }}
                />
              </div>

              {/* Slide / Page Thumbnail with Proposed Masks (Section 5.5 #3) */}
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-text">
                  Visual Layout Inspection
                </label>
                <ThumbnailWithMasks
                  thumbnailUrl={currentItem.thumbnail_url}
                  thumbnailData={currentItem.thumbnail_data}
                  bbox={currentItem.locator?.bbox}
                  page={currentItem.locator?.page}
                  onRegionSelected={(box) => {
                    setDrawnBbox(box);
                    setShowAddRegionModal(true);
                  }}
                />
              </div>

              {/* Evidence List */}
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-text flex items-center gap-1.5">
                  <HelpCircle className="w-3.5 h-3.5 text-accent" />
                  <span>Detector Signals & Corroborating Evidence</span>
                </label>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {currentItem.evidence.map((ev, i) => (
                    <div
                      key={i}
                      className="p-3 rounded bg-surface-raised border border-border text-xs space-y-1"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-text">{ev.detector}</span>
                        {ev.layer && (
                          <span className="font-mono text-[10px] text-text-muted uppercase">
                            {ev.layer}
                          </span>
                        )}
                      </div>
                      {ev.rule_id && (
                        <p className="font-mono text-[11px] text-accent">Rule: {ev.rule_id}</p>
                      )}
                      {ev.context_terms && ev.context_terms.length > 0 && (
                        <p className="text-[11px] text-text-muted">
                          Terms: {ev.context_terms.join(', ')}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Active Decision on Item */}
              {currentDecision && (
                <div className="p-3 bg-accent/10 border border-accent/30 rounded text-xs flex items-center justify-between text-text">
                  <span className="font-mono">
                    Current decision: <strong>{currentDecision.action.toUpperCase()}</strong>
                    {currentDecision.justification && `: "${currentDecision.justification}"`}
                    {currentDecision.entity_type && `, type: ${currentDecision.entity_type}`}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setDecisions((prev) => {
                        const copy = { ...prev };
                        delete copy[currentItem.finding_id];
                        return copy;
                      });
                    }}
                    className="text-text-muted hover:text-status-failed text-xs underline"
                  >
                    Clear decision
                  </button>
                </div>
              )}
            </div>

            {/* Action Bar & Keyboard Shortcuts Legend (Section 5.5) */}
            <div className="pt-6 border-t border-border space-y-4">
              <div className="flex flex-wrap items-center gap-2.5">
                {/* 1. Confirm Button */}
                <button
                  type="button"
                  onClick={handleConfirm}
                  className="bg-accent hover:bg-accent-hover text-text-on-accent text-xs font-semibold px-4 py-2 rounded transition-colors flex items-center gap-1.5 shadow"
                  title="Confirm entity redaction (Press C)"
                >
                  <Check className="w-3.5 h-3.5" />
                  <span>Confirm (C)</span>
                </button>

                {/* 2. Reject Button (Strictly forbidden on HIGH + DETERMINISTIC) */}
                <div
                  title={
                    isHighDeterministic
                      ? 'Reject is forbidden on High Risk Deterministic findings (Section 4)'
                      : 'Reject finding with justification (Press R)'
                  }
                >
                  <button
                    type="button"
                    onClick={handleOpenReject}
                    disabled={isHighDeterministic}
                    className="bg-surface hover:bg-surface-raised disabled:opacity-30 disabled:cursor-not-allowed text-status-failed border border-border text-xs font-semibold px-4 py-2 rounded transition-colors flex items-center gap-1.5"
                  >
                    <X className="w-3.5 h-3.5" />
                    <span>Reject (R)</span>
                  </button>
                </div>

                {/* 3. Retype Button */}
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setShowRetypeDropdown(!showRetypeDropdown)}
                    className="bg-surface hover:bg-surface-raised text-text border border-border text-xs font-semibold px-4 py-2 rounded transition-colors flex items-center gap-1.5"
                    title="Change entity classification (Press T)"
                  >
                    <Tag className="w-3.5 h-3.5 text-accent" />
                    <span>Change Type (T)</span>
                  </button>

                  {showRetypeDropdown && (
                    <div className="absolute bottom-full mb-1 left-0 w-64 bg-surface border border-border rounded-lg shadow-2xl p-2 z-20 max-h-60 overflow-y-auto divide-y divide-border/40">
                      <span className="text-[10px] uppercase font-mono text-text-muted px-2 py-1 block">
                        Select New Entity Type
                      </span>
                      {ALL_KNOWN_ENTITY_TYPES.map((type) => (
                        <button
                          key={type}
                          type="button"
                          onClick={() => handleApplyRetype(type)}
                          className="w-full text-left px-2 py-1.5 text-xs text-text hover:bg-surface-raised rounded transition-colors"
                        >
                          {type}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* 4. Add missed region */}
                <button
                  type="button"
                  onClick={() => setShowAddRegionModal(true)}
                  className="bg-surface hover:bg-surface-raised text-text border border-border text-xs font-semibold px-3 py-2 rounded transition-colors flex items-center gap-1.5"
                  title="Add visual region mask"
                >
                  <Square className="w-3.5 h-3.5 text-accent" />
                  <span>Add Region</span>
                </button>

                {/* 5. Reject document */}
                <button
                  type="button"
                  onClick={() => setShowRejectDocDialog(true)}
                  className="bg-status-failed-bg hover:bg-status-failed/20 text-status-failed border border-status-failed/30 text-xs font-semibold px-3 py-2 rounded transition-colors flex items-center gap-1.5 ml-auto"
                  title="Reject entire document"
                >
                  <FileX className="w-3.5 h-3.5" />
                  <span>Reject Document</span>
                </button>
              </div>

              {/* Keyboard Shortcut Legend */}
              <div className="flex flex-wrap items-center gap-4 text-[11px] text-text-muted font-mono pt-2 border-t border-border/40">
                <span>Shortcuts:</span>
                <span><kbd className="px-1.5 py-0.5 rounded bg-bg-alt border border-border">C</kbd> Confirm</span>
                <span><kbd className="px-1.5 py-0.5 rounded bg-bg-alt border border-border">R</kbd> Reject</span>
                <span><kbd className="px-1.5 py-0.5 rounded bg-bg-alt border border-border">T</kbd> Retype</span>
                <span><kbd className="px-1.5 py-0.5 rounded bg-bg-alt border border-border">J</kbd>/<kbd className="px-1.5 py-0.5 rounded bg-bg-alt border border-border">K</kbd> Next/Prev</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Reject Justification Modal Dialog */}
      <ConfirmDialog
        isOpen={showRejectModal}
        title="Reject Finding Decision"
        message="A documented justification is mandatory when discarding candidate privacy detections."
        confirmLabel="Apply Rejection"
        isDestructive={true}
        onConfirm={handleApplyReject}
        onCancel={() => setShowRejectModal(false)}
      >
        <div className="space-y-2 mt-2">
          <label className="text-xs font-semibold text-text block">
            Reviewer Justification (Required)
          </label>
          <textarea
            rows={3}
            value={rejectJustification}
            onChange={(e) => setRejectJustification(e.target.value)}
            placeholder="Document rationale (e.g. false positive corporate address, non-PII test fixture)..."
            className="w-full p-2.5 bg-bg-alt border border-border rounded text-xs text-text focus:ring-1 focus:ring-focus-ring"
          />
        </div>
      </ConfirmDialog>

      {/* Add Missed Span Modal */}
      <ConfirmDialog
        isOpen={showAddSpanModal}
        title="Add Custom PII Span"
        message={`Mark missed text span "${selectedSpanRange?.text}" for redaction.`}
        confirmLabel="Add Span Mask"
        onConfirm={handleApplyAddSpan}
        onCancel={() => setShowAddSpanModal(false)}
      >
        <div className="space-y-2 mt-2">
          <label className="text-xs font-semibold text-text block">Entity Type</label>
          <select
            value={addSpanType}
            onChange={(e) => setAddSpanType(e.target.value)}
            className="w-full p-2 bg-bg-alt border border-border rounded text-xs text-text"
          >
            {ALL_KNOWN_ENTITY_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
      </ConfirmDialog>

      {/* Add Region Modal */}
      <ConfirmDialog
        isOpen={showAddRegionModal}
        title="Add Raster Region Mask"
        message={`Apply bounding box mask on page ${currentItem?.locator?.page || 1}.`}
        confirmLabel="Apply Region Mask"
        onConfirm={handleApplyAddRegion}
        onCancel={() => setShowAddRegionModal(false)}
      >
        <p className="text-xs font-mono text-accent">
          Bounding Box: [{drawnBbox.join(', ')}]
        </p>
      </ConfirmDialog>

      {/* Reject Entire Document Dialog */}
      <ConfirmDialog
        isOpen={showRejectDocDialog}
        title="Reject Entire Document"
        message="This action immediately blocks the document from AI handoff and sets state to BLOCKED."
        confirmLabel="Confirm Document Rejection"
        isDestructive={true}
        onConfirm={handleApplyRejectDocument}
        onCancel={() => setShowRejectDocDialog(false)}
      >
        <div className="space-y-2 mt-2">
          <label className="text-xs font-semibold text-text block">
            Reason for Document Rejection (Required)
          </label>
          <textarea
            rows={3}
            value={rejectDocReason}
            onChange={(e) => setRejectDocReason(e.target.value)}
            placeholder="e.g. Corrupted unredactable raster scans or non-remediable PII..."
            className="w-full p-2.5 bg-bg-alt border border-border rounded text-xs text-text focus:ring-1 focus:ring-focus-ring"
          />
        </div>
      </ConfirmDialog>

      {/* Submit Decisions Confirmation Dialog (Section 5.5) */}
      <ConfirmDialog
        isOpen={showSubmitConfirmDialog}
        title="Submit Review Decisions"
        message="The system will re-redact and re-verify. Your decisions cannot mark this document safe by themselves."
        confirmLabel="Submit & Re-verify"
        onConfirm={handleSubmitAllDecisions}
        onCancel={() => setShowSubmitConfirmDialog(false)}
      >
        <div className="p-3 bg-surface-raised border border-border rounded text-xs text-text-muted mt-2">
          Submitting <strong>{decidedCount}</strong> decisions for job{' '}
          <strong className="text-text">{jobId}</strong>.
        </div>
      </ConfirmDialog>
    </div>
  );
};
