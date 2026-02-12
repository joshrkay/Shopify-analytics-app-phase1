import {
  getTeamMembers,
  inviteMember,
  removeMember,
  resendInvite,
  updateMemberRole,
} from '../services/tenantMembersApi';
import type { TeamInvite, TeamInviteRole } from '../types/settingsTypes';
import { useMutationLite, useQueryClientLite, useQueryLite } from './queryClientLite';

const TEAM_MEMBERS_QUERY_KEY = ['settings', 'team-members'] as const;

export function useTeamMembers() {
  const query = useQueryLite({
    queryKey: TEAM_MEMBERS_QUERY_KEY,
    queryFn: getTeamMembers,
  });

  return {
    members: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error.message : null,
    refetch: query.refetch,
  };
}

export function useInviteMember() {
  const queryClient = useQueryClientLite();

  return useMutationLite({
    mutationFn: inviteMember,
    onSuccess: () => {
      queryClient.invalidateQueries(TEAM_MEMBERS_QUERY_KEY);
    },
  });
}

export function useUpdateMemberRole() {
  const queryClient = useQueryClientLite();

  return useMutationLite({
    mutationFn: ({ memberId, role }: { memberId: string; role: TeamInviteRole }) => updateMemberRole(memberId, role),
    onSuccess: () => {
      queryClient.invalidateQueries(TEAM_MEMBERS_QUERY_KEY);
    },
  });
}

export function useRemoveMember() {
  const queryClient = useQueryClientLite();

  return useMutationLite({
    mutationFn: (memberId: string) => removeMember(memberId),
    onSuccess: () => {
      queryClient.invalidateQueries(TEAM_MEMBERS_QUERY_KEY);
    },
  });
}

export function useResendInvite() {
  return useMutationLite({
    mutationFn: (memberId: string) => resendInvite(memberId),
  });
}

export { TEAM_MEMBERS_QUERY_KEY };
