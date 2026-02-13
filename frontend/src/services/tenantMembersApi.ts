import { API_BASE_URL, createHeadersAsync, handleResponse } from './apiUtils';
import type { TeamInvite, TeamInviteRole, TeamMember } from '../types/settingsTypes';

function normalizeAndValidateInviteEmail(email: string): string {
  const normalizedEmail = email.trim();
  const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!emailPattern.test(normalizedEmail)) {
    throw new Error('Please provide a valid email address.');
  }
  return normalizedEmail;
}

export async function getTeamMembers(tenantId: string): Promise<TeamMember[]> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/members`, { method: 'GET', headers });
  const data = await handleResponse<{ members: TeamMember[]; total_count: number; tenant_id: string }>(response);
  return data.members;
}

export async function inviteMember(tenantId: string, invite: TeamInvite): Promise<TeamMember> {
  const email = normalizeAndValidateInviteEmail(invite.email);
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/members`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ email, role: invite.role }),
  });
  return handleResponse<TeamMember>(response);
}

export async function updateMemberRole(tenantId: string, memberId: string, role: TeamInviteRole): Promise<TeamMember> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/members/${memberId}`, {
    method: 'PATCH',
    headers,
    body: JSON.stringify({ role }),
  });
  return handleResponse<TeamMember>(response);
}

export async function removeMember(tenantId: string, memberId: string): Promise<{ success: boolean }> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/members/${memberId}`, {
    method: 'DELETE',
    headers,
  });
  return handleResponse<{ success: boolean }>(response);
}

export async function resendInvite(_tenantId: string, _memberId: string): Promise<{ success: boolean }> {
  // Backend route not yet implemented
  console.warn('resendInvite: backend endpoint not yet implemented');
  return { success: false };
}
