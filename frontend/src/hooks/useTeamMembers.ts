import { useCallback, useEffect, useState } from 'react';
import {
  getTeamMembers,
  inviteMember,
  removeMember,
  resendInvite,
  updateMemberRole,
} from '../services/tenantMembersApi';
import type { TeamInvite, TeamInviteRole, TeamMember } from '../types/settingsTypes';

export function useTeamMembers() {
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      setMembers(await getTeamMembers());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load team members');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { members, isLoading, error, refetch, setMembers };
}

export function useInviteMember() {
  return useCallback((invite: TeamInvite) => inviteMember(invite), []);
}

export function useUpdateMemberRole() {
  return useCallback((memberId: string, role: TeamInviteRole) => updateMemberRole(memberId, role), []);
}

export function useRemoveMember() {
  return useCallback((memberId: string) => removeMember(memberId), []);
}

export function useResendInvite() {
  return useCallback((memberId: string) => resendInvite(memberId), []);
}
