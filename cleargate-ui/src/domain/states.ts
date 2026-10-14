export type JobState =
  | 'RECEIVED'
  | 'PROCESSING'
  | 'REVIEW_REQUIRED'
  | 'BLOCKED'
  | 'VALIDATED_SAFE'
  | 'FAILED';

export const TERMINAL_STATES: ReadonlyArray<JobState> = [
  'BLOCKED',
  'FAILED',
  'VALIDATED_SAFE',
];

export function isTerminalState(state: JobState): boolean {
  return TERMINAL_STATES.includes(state);
}

export type RiskLevel = 'HIGH' | 'MEDIUM' | 'LOW';

export type TierLevel =
  | 'DETERMINISTIC'
  | 'CORROBORATED'
  | 'SINGLE_SIGNAL'
  | 'LOW';

export type FindingDecision =
  | 'auto_redact'
  | 'review'
  | 'suppressed'
  | 'discarded';

export type UserRole = 'submitter' | 'reviewer';
