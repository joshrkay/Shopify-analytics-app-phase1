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

export async function getTeamMembers(): Promise<TeamMember[]> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/tenant-members`, { method: 'GET', headers });
  return handleResponse<TeamMember[]>(response);
}

export async function inviteMember(invite: TeamInvite): Promise<TeamMember> {
  const email = normalizeAndValidateInviteEmail(invite.email);
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/tenant-members/invite`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ ...invite, email }),
  });
  return handleResponse<TeamMember>(response);
}

export async function updateMemberRole(memberId: string, role: TeamInviteRole): Promise<TeamMember> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/tenant-members/${memberId}/role`, {
    method: 'PUT',
    headers,
    body: JSON.stringify({ role }),
  });
  return handleResponse<TeamMember>(response);
}

export async function removeMember(memberId: string): Promise<{ success: boolean }> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/tenant-members/${memberId}`, {
    method: 'DELETE',
    headers,
  });
  return handleResponse<{ success: boolean }>(response);
}

export async function resendInvite(memberId: string): Promise<{ success: boolean }> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/tenant-members/${memberId}/resend`, {
    method: 'POST',
    headers,
  });
  return handleResponse<{ success: boolean }>(response);
}
