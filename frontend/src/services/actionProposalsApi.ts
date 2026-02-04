/**
 * Action Proposals API Service
 *
 * Handles API calls for action proposal approval workflow:
 * - Listing proposals with filtering
 * - Approving/rejecting proposals
 * - Viewing audit trail
 *
 * Story 9.4 - Action Approval UX
 */

import type {
  ActionProposal,
  ActionProposalsListResponse,
  ProposalActionResponse,
  ActionProposalsFilters,
  AuditTrailResponse,
  PendingCountResponse,
} from '../types/actionProposals';
import { API_BASE_URL, createHeaders, handleResponse, buildQueryString } from './apiUtils';

/**
 * List action proposals with optional filtering.
 *
 * @param filters - Optional filters for proposals
 * @returns List of proposals with pagination info
 */
export async function listActionProposals(
  filters: ActionProposalsFilters = {}
): Promise<ActionProposalsListResponse> {
  const queryString = buildQueryString(filters);
  const response = await fetch(`${API_BASE_URL}/api/action-proposals${queryString}`, {
    method: 'GET',
    headers: createHeaders(),
  });
  return handleResponse<ActionProposalsListResponse>(response);
}

/**
 * Get a single action proposal by ID.
 *
 * @param proposalId - The proposal ID
 * @returns The proposal details
 */
export async function getActionProposal(proposalId: string): Promise<ActionProposal> {
  const response = await fetch(`${API_BASE_URL}/api/action-proposals/${proposalId}`, {
    method: 'GET',
    headers: createHeaders(),
  });
  return handleResponse<ActionProposal>(response);
}

/**
 * Get pending action proposals.
 *
 * @returns List of proposals with status 'proposed'
 */
export async function getPendingProposals(): Promise<ActionProposalsListResponse> {
  return listActionProposals({ status: 'proposed' });
}

/**
 * Approve an action proposal.
 *
 * Only users with MERCHANT_ADMIN or AGENCY_ADMIN role can approve.
 * Creates an audit trail entry.
 *
 * @param proposalId - The proposal ID to approve
 * @returns Action response with new status
 */
export async function approveProposal(
  proposalId: string
): Promise<ProposalActionResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/action-proposals/${proposalId}/approve`,
    {
      method: 'POST',
      headers: createHeaders(),
    }
  );
  return handleResponse<ProposalActionResponse>(response);
}

/**
 * Reject an action proposal.
 *
 * Only users with MERCHANT_ADMIN or AGENCY_ADMIN role can reject.
 * Creates an audit trail entry.
 *
 * @param proposalId - The proposal ID to reject
 * @param reason - Optional reason for rejection
 * @returns Action response with new status
 */
export async function rejectProposal(
  proposalId: string,
  reason?: string
): Promise<ProposalActionResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/action-proposals/${proposalId}/reject`,
    {
      method: 'POST',
      headers: createHeaders(),
      body: reason ? JSON.stringify({ reason }) : undefined,
    }
  );
  return handleResponse<ProposalActionResponse>(response);
}

/**
 * Get the audit trail for an action proposal.
 *
 * Returns all state changes in chronological order.
 *
 * @param proposalId - The proposal ID
 * @returns Audit trail with all entries
 */
export async function getProposalAuditTrail(
  proposalId: string
): Promise<AuditTrailResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/action-proposals/${proposalId}/audit`,
    {
      method: 'GET',
      headers: createHeaders(),
    }
  );
  return handleResponse<AuditTrailResponse>(response);
}

/**
 * Get count of pending action proposals.
 *
 * Useful for badge displays.
 *
 * @returns Count of pending proposals
 */
export async function getPendingProposalsCount(): Promise<number> {
  const response = await fetch(`${API_BASE_URL}/api/action-proposals/stats/pending`, {
    method: 'GET',
    headers: createHeaders(),
  });
  const data = await handleResponse<PendingCountResponse>(response);
  return data.pending_count;
}
