import { useEffect, useMemo, useRef, useState } from 'react';
import {
  getTeamMembers,
  inviteMember,
  removeMember,
  resendInvite,
  updateMemberRole,
} from '../services/tenantMembersApi';
import type { TeamInvite, TeamInviteRole, TeamMember } from '../types/settingsTypes';
import { useMutationLite, useQueryClientLite, useQueryLite } from './queryClientLite';

const TEAM_MEMBERS_QUERY_KEY = ['settings', 'team-members'] as const;
const REMOVE_UNDO_WINDOW_MS = 5000;

interface TeamMembersStore {
  members: TeamMember[];
  listeners: Set<() => void>;
}

interface PendingRemoval {
  member: TeamMember;
  index: number;
  timeoutId: ReturnType<typeof setTimeout>;
  reject: (error: unknown) => void;
  resolve: (value: { success: boolean; undone?: boolean }) => void;
}

const teamMembersStore: TeamMembersStore = {
  members: [],
  listeners: new Set(),
};

const pendingRemovalMap = new Map<string, PendingRemoval>();

function emitTeamMembersStore() {
  teamMembersStore.listeners.forEach((listener) => listener());
}

function getTeamMembersStoreSnapshot(): TeamMember[] {
  return teamMembersStore.members;
}

function setTeamMembersStoreSnapshot(nextMembers: TeamMember[]) {
  teamMembersStore.members = nextMembers;
  emitTeamMembersStore();
}

function replaceTeamMembersStore(updater: (members: TeamMember[]) => TeamMember[]) {
  const next = updater(teamMembersStore.members);
  setTeamMembersStoreSnapshot(next);
}

function subscribeToTeamMembersStore(listener: () => void): () => void {
  teamMembersStore.listeners.add(listener);
  return () => {
    teamMembersStore.listeners.delete(listener);
  };
}

function flushPendingRemovals(reason: string) {
  pendingRemovalMap.forEach((pending, memberId) => {
    clearTimeout(pending.timeoutId);
    pending.resolve({ success: false, undone: true });
    pendingRemovalMap.delete(memberId);
  });
}

export function useTeamMembers() {
  const query = useQueryLite({
    queryKey: TEAM_MEMBERS_QUERY_KEY,
    queryFn: getTeamMembers,
  });
  const [membersSnapshot, setMembersSnapshot] = useState<TeamMember[]>(() => getTeamMembersStoreSnapshot());

  useEffect(() => subscribeToTeamMembersStore(() => {
    setMembersSnapshot(getTeamMembersStoreSnapshot());
  }), []);

  useEffect(() => {
    if (query.data) {
      const pendingIds = new Set(pendingRemovalMap.keys());
      const filteredMembers = query.data.filter((member) => !pendingIds.has(member.id));
      setTeamMembersStoreSnapshot(filteredMembers);
    }
  }, [query.data]);

  const members = useMemo(
    () => (membersSnapshot.length > 0 || query.isLoading ? membersSnapshot : query.data ?? []),
    [membersSnapshot, query.data, query.isLoading],
  );

  return {
    members,
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error.message : null,
    refetch: query.refetch,
  };
}

export function useInviteMember() {
  const queryClient = useQueryClientLite();
  const optimisticIdRef = useRef(0);

  return useMutationLite({
    mutationFn: async (invite: TeamInvite) => {
      const optimisticId = `optimistic-member-${optimisticIdRef.current++}`;
      const optimisticMember: TeamMember = {
        id: optimisticId,
        userId: optimisticId,
        name: invite.email,
        email: invite.email,
        role: invite.role,
        status: 'pending',
        joinedDate: new Date().toISOString(),
      };

      replaceTeamMembersStore((members) => [...members, optimisticMember]);

      try {
        const createdMember = await inviteMember(invite);
        replaceTeamMembersStore((members) => members.map((member) => (
          member.id === optimisticId ? createdMember : member
        )));
        return createdMember;
      } catch (error) {
        replaceTeamMembersStore((members) => members.filter((member) => member.id !== optimisticId));
        throw error;
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries(TEAM_MEMBERS_QUERY_KEY);
    },
  });
}

export function useUpdateMemberRole() {
  const queryClient = useQueryClientLite();

  return useMutationLite({
    mutationFn: async ({ memberId, role }: { memberId: string; role: TeamInviteRole }) => {
      const previousMembers = getTeamMembersStoreSnapshot();
      replaceTeamMembersStore((members) => members.map((member) => (
        member.id === memberId ? { ...member, role } : member
      )));

      try {
        return await updateMemberRole(memberId, role);
      } catch (error) {
        setTeamMembersStoreSnapshot(previousMembers);
        throw error;
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries(TEAM_MEMBERS_QUERY_KEY);
    },
  });
}

export function useRemoveMember() {
  const queryClient = useQueryClientLite();
  const [undoMemberId, setUndoMemberId] = useState<string | null>(null);

  useEffect(() => () => {
    flushPendingRemovals('Remove member undo window closed because component unmounted.');
  }, []);

  const undoLastRemove = () => {
    if (!undoMemberId) {
      return false;
    }

    const pending = pendingRemovalMap.get(undoMemberId);
    if (!pending) {
      setUndoMemberId(null);
      return false;
    }

    clearTimeout(pending.timeoutId);
    replaceTeamMembersStore((members) => {
      const nextMembers = members.slice();
      nextMembers.splice(pending.index, 0, pending.member);
      return nextMembers;
    });

    pending.resolve({ success: true, undone: true });
    pendingRemovalMap.delete(undoMemberId);
    setUndoMemberId(null);
    return true;
  };

  const mutation = useMutationLite({
    mutationFn: async (memberId: string) => {
      const existingMembers = getTeamMembersStoreSnapshot();
      const index = existingMembers.findIndex((member) => member.id === memberId);

      if (index < 0) {
        return { success: false };
      }

      const removedMember = existingMembers[index];
      replaceTeamMembersStore((members) => members.filter((member) => member.id !== memberId));
      setUndoMemberId(memberId);

      const result = await new Promise<{ success: boolean; undone?: boolean }>((resolve, reject) => {
        const timeoutId = setTimeout(async () => {
          pendingRemovalMap.delete(memberId);
          try {
            const response = await removeMember(memberId);
            resolve(response);
          } catch (error) {
            replaceTeamMembersStore((members) => {
              const nextMembers = members.slice();
              nextMembers.splice(index, 0, removedMember);
              return nextMembers;
            });
            reject(error);
          } finally {
            setUndoMemberId((current) => (current === memberId ? null : current));
          }
        }, REMOVE_UNDO_WINDOW_MS);

        pendingRemovalMap.set(memberId, {
          member: removedMember,
          index,
          timeoutId,
          resolve,
          reject,
        });
      });

      return result;
    },
    onSuccess: (result) => {
      if (!result.undone) {
        queryClient.invalidateQueries(TEAM_MEMBERS_QUERY_KEY);
      }
    },
  });

  return {
    ...mutation,
    undoMemberId,
    undoLastRemove,
    undoWindowMs: REMOVE_UNDO_WINDOW_MS,
  };
}

export function useResendInvite() {
  return useMutationLite({
    mutationFn: (memberId: string) => resendInvite(memberId),
  });
}

export { TEAM_MEMBERS_QUERY_KEY, REMOVE_UNDO_WINDOW_MS };
