import { JobState } from './states';

export interface StateUiConfig {
  badgeLabel: string;
  badgeClass: string;
  bannerMessage: string;
  downloadsEnabled: boolean;
  handoffEnabled: boolean;
  reviewAction: 'none' | 'open_workspace';
  iconType: 'clock' | 'spinner' | 'alert-triangle' | 'shield-alert' | 'shield-x' | 'shield-check' | 'help-circle';
}

export const STATE_UI_MAP: Record<JobState, StateUiConfig> = {
  RECEIVED: {
    badgeLabel: 'Received',
    badgeClass: 'bg-status-processing-bg text-status-processing border-status-processing/30',
    bannerMessage: 'Queued for processing.',
    downloadsEnabled: false,
    handoffEnabled: false,
    reviewAction: 'none',
    iconType: 'clock',
  },
  PROCESSING: {
    badgeLabel: 'Processing',
    badgeClass: 'bg-status-processing-bg text-status-processing border-status-processing/30',
    bannerMessage: 'Processing. This page updates automatically.',
    downloadsEnabled: false,
    handoffEnabled: false,
    reviewAction: 'none',
    iconType: 'spinner',
  },
  REVIEW_REQUIRED: {
    badgeLabel: 'Needs review',
    badgeClass: 'bg-status-review-bg text-status-review border-status-review/30',
    bannerMessage: 'A reviewer must resolve uncertain items before this document can be cleared.',
    downloadsEnabled: false,
    handoffEnabled: false,
    reviewAction: 'open_workspace',
    iconType: 'alert-triangle',
  },
  BLOCKED: {
    badgeLabel: 'Blocked',
    badgeClass: 'bg-status-blocked-bg text-status-blocked border-status-blocked/30',
    bannerMessage: 'Blocked: the system could not show this document is safe. Only the report is available.',
    downloadsEnabled: false,
    handoffEnabled: false,
    reviewAction: 'none',
    iconType: 'shield-alert',
  },
  FAILED: {
    badgeLabel: 'Failed',
    badgeClass: 'bg-status-failed-bg text-status-failed border-status-failed/30',
    bannerMessage: 'Processing failed. See the report for the error code.',
    downloadsEnabled: false,
    handoffEnabled: false,
    reviewAction: 'none',
    iconType: 'shield-x',
  },
  VALIDATED_SAFE: {
    badgeLabel: 'Validated safe',
    badgeClass: 'bg-status-safe-bg text-status-safe border-status-safe/30',
    bannerMessage: 'Verified by the privacy gate. Outputs are available.',
    downloadsEnabled: true,
    handoffEnabled: true,
    reviewAction: 'none',
    iconType: 'shield-check',
  },
};

export const UNKNOWN_STATE_CONFIG: StateUiConfig = {
  badgeLabel: 'Unknown state',
  badgeClass: 'bg-surface text-text-muted border-border',
  bannerMessage: 'Unknown state returned by server. Outputs are unavailable.',
  downloadsEnabled: false,
  handoffEnabled: false,
  reviewAction: 'none',
  iconType: 'help-circle',
};

export function getStateUiConfig(state: string | undefined): StateUiConfig {
  if (!state || !(state in STATE_UI_MAP)) {
    return UNKNOWN_STATE_CONFIG;
  }
  return STATE_UI_MAP[state as JobState];
}

export function formatStageTitle(stage: string | undefined): string {
  // ASSUMPTION[A-5]: Stage string vocabulary is opaque; display title-cased.
  if (!stage) return '-';
  return stage
    .replace(/[_-]/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}
