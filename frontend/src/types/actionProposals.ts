/**
 * TypeScript types for Action Proposals
 *
 * Story 9.4 - Action Approval UX
 */

export type ActionType =
  | 'pause_campaign'
  | 'resume_campaign'
  | 'adjust_budget'
  | 'adjust_bid'
  | 'update_targeting'
  | 'update_schedule';

export type ActionStatus =
  | 'proposed'
  | 'approved'
  | 'rejected'
  | 'expired'
  | 'cancelled'
  | 'executed'
  | 'failed'
  | 'rolled_back';

export type TargetPlatform = 'meta' | 'google' | 'tiktok';

export type TargetEntityType = 'campaign' | 'ad_set' | 'ad';

export type RiskLevel = 'low' | 'medium' | 'high';

export interface TargetInfo {
  platform: TargetPlatform;
  entity_type: TargetEntityType;
  entity_id: string;
  entity_name: string | null;
}

export interface ActionProposal {
  proposal_id: string;
  action_type: ActionType;
  status: ActionStatus;
  target: TargetInfo;
  proposed_change: Record<string, unknown>;
  current_value: Record<string, unknown> | null;
  expected_effect: string;
  risk_disclaimer: string;
  risk_level: RiskLevel;
  confidence_score: number;
  requires_approval: boolean;
  expires_at: string;
  created_at: string;
  decided_at: string | null;
  decided_by: string | null;
  decision_reason: string | null;
  source_recommendation_id: string | null;
}

export interface ActionProposalsListResponse {
  proposals: ActionProposal[];
  total: number;
  has_more: boolean;
  pending_count: number;
}

export interface ProposalActionResponse {
  status: string;
  proposal_id: string;
  new_status: ActionStatus;
}

export interface ActionProposalsFilters {
  status?: ActionStatus;
  action_type?: ActionType;
  platform?: TargetPlatform;
  risk_level?: RiskLevel;
  limit?: number;
  offset?: number;
}

export type AuditAction =
  | 'created'
  | 'approved'
  | 'rejected'
  | 'expired'
  | 'cancelled'
  | 'executed'
  | 'failed'
  | 'rolled_back';

export interface AuditEntry {
  id: string;
  action: AuditAction;
  performed_at: string;
  performed_by: string | null;
  performed_by_role: string | null;
  previous_status: ActionStatus | null;
  new_status: ActionStatus;
  reason: string | null;
}

export interface AuditTrailResponse {
  proposal_id: string;
  entries: AuditEntry[];
}

export interface PendingCountResponse {
  pending_count: number;
}

/**
 * Get display label for action type
 */
export function getActionTypeLabel(type: ActionType): string {
  const labels: Record<ActionType, string> = {
    pause_campaign: 'Pause Campaign',
    resume_campaign: 'Resume Campaign',
    adjust_budget: 'Adjust Budget',
    adjust_bid: 'Adjust Bid',
    update_targeting: 'Update Targeting',
    update_schedule: 'Update Schedule',
  };
  return labels[type] || type;
}

/**
 * Get display label for action status
 */
export function getStatusLabel(status: ActionStatus): string {
  const labels: Record<ActionStatus, string> = {
    proposed: 'Pending Approval',
    approved: 'Approved',
    rejected: 'Rejected',
    expired: 'Expired',
    cancelled: 'Cancelled',
    executed: 'Executed',
    failed: 'Failed',
    rolled_back: 'Rolled Back',
  };
  return labels[status] || status;
}

/**
 * Get status badge tone
 */
export function getStatusTone(status: ActionStatus): 'info' | 'success' | 'warning' | 'critical' | undefined {
  const tones: Record<ActionStatus, 'info' | 'success' | 'warning' | 'critical' | undefined> = {
    proposed: 'warning',
    approved: 'success',
    rejected: 'critical',
    expired: undefined,
    cancelled: undefined,
    executed: 'success',
    failed: 'critical',
    rolled_back: 'warning',
  };
  return tones[status];
}

/**
 * Get risk level badge tone
 */
export function getRiskTone(risk: RiskLevel): 'info' | 'warning' | 'critical' {
  const tones: Record<RiskLevel, 'info' | 'warning' | 'critical'> = {
    low: 'info',
    medium: 'warning',
    high: 'critical',
  };
  return tones[risk];
}

/**
 * Get platform display name
 */
export function getPlatformLabel(platform: TargetPlatform): string {
  const labels: Record<TargetPlatform, string> = {
    meta: 'Meta Ads',
    google: 'Google Ads',
    tiktok: 'TikTok Ads',
  };
  return labels[platform] || platform;
}

/**
 * Check if proposal can be approved/rejected
 */
export function canDecideProposal(proposal: ActionProposal): boolean {
  return proposal.status === 'proposed' && new Date(proposal.expires_at) > new Date();
}

/**
 * Check if proposal is expired
 */
export function isProposalExpired(proposal: ActionProposal): boolean {
  return proposal.status === 'proposed' && new Date(proposal.expires_at) <= new Date();
}
