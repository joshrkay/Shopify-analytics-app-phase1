import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/tenantMembersApi', () => ({
  getTeamMembers: vi.fn(),
  inviteMember: vi.fn(),
  updateMemberRole: vi.fn(),
  removeMember: vi.fn(),
}));

import {
  REMOVE_UNDO_WINDOW_MS,
  useInviteMember,
  useRemoveMember,
  useTeamMembers,
  useUpdateMemberRole,
} from '../hooks/useTeamMembers';
import * as teamApi from '../services/tenantMembersApi';

const mocked = vi.mocked(teamApi);

beforeEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
  mocked.getTeamMembers.mockResolvedValue([{ id: '1', userId: 'u1', name: 'A', email: 'a@a.com', role: 'admin', status: 'active', joinedDate: '' }]);
  mocked.inviteMember.mockResolvedValue({ id: '2', userId: 'u2', name: 'B', email: 'b@b.com', role: 'viewer', status: 'pending', joinedDate: '' });
  mocked.updateMemberRole.mockResolvedValue({ id: '1', userId: 'u1', name: 'A', email: 'a@a.com', role: 'editor', status: 'active', joinedDate: '' });
  mocked.removeMember.mockResolvedValue({ success: true });
});

describe('useTeamMembers', () => {
  it('useTeamMembers returns member list', async () => {
    const { result } = renderHook(() => useTeamMembers());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.members).toHaveLength(1);
  });

  it('useInviteMember adds pending member optimistically', async () => {
    const membersHook = renderHook(() => useTeamMembers());
    const inviteHook = renderHook(() => useInviteMember());

    await waitFor(() => expect(membersHook.result.current.isLoading).toBe(false));

    mocked.inviteMember.mockImplementation(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
      return { id: '2', userId: 'u2', name: 'B', email: 'b@b.com', role: 'viewer', status: 'pending', joinedDate: '' };
    });

    let mutationPromise: Promise<unknown> | null = null;
    await act(async () => {
      mutationPromise = inviteHook.result.current.mutateAsync({ email: 'b@b.com', role: 'viewer' });
    });

    await waitFor(() => expect(membersHook.result.current.members.length).toBeGreaterThan(1));
    expect(membersHook.result.current.members.some((member) => member.id.startsWith('optimistic-member-'))).toBe(true);

    await act(async () => {
      await mutationPromise;
    });

    await waitFor(() => expect(mocked.inviteMember).toHaveBeenCalledWith({ email: 'b@b.com', role: 'viewer' }));
  });

  it('useUpdateMemberRole optimistic role change', async () => {
    const membersHook = renderHook(() => useTeamMembers());
    const updateHook = renderHook(() => useUpdateMemberRole());

    await waitFor(() => expect(membersHook.result.current.isLoading).toBe(false));

    mocked.updateMemberRole.mockImplementation(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
      return { id: '1', userId: 'u1', name: 'A', email: 'a@a.com', role: 'editor', status: 'active', joinedDate: '' };
    });

    let mutationPromise: Promise<unknown> | null = null;
    await act(async () => {
      mutationPromise = updateHook.result.current.mutateAsync({ memberId: '1', role: 'editor' });
    });

    await waitFor(() => expect(membersHook.result.current.members[0]?.role).toBe('editor'));

    await act(async () => {
      await mutationPromise;
    });

    expect(mocked.updateMemberRole).toHaveBeenCalledWith('1', 'editor');
  });

  it('useRemoveMember supports undo within toast window', async () => {
    const membersHook = renderHook(() => useTeamMembers());
    const removeHook = renderHook(() => useRemoveMember());

    await waitFor(() => expect(membersHook.result.current.isLoading).toBe(false));

    let mutationPromise: Promise<{ success: boolean; undone?: boolean }> | null = null;
    await act(async () => {
      mutationPromise = removeHook.result.current.mutateAsync('1');
    });

    await waitFor(() => expect(removeHook.result.current.undoMemberId).toBe('1'));

    await act(async () => {
      removeHook.result.current.undoLastRemove();
    });

    await waitFor(() => expect(membersHook.result.current.members.find((member) => member.id === '1')).toBeDefined());

    await expect(mutationPromise!).resolves.toMatchObject({ undone: true });
    expect(mocked.removeMember).not.toHaveBeenCalled();
  });

  it('Query invalidation after mutations executes delete after undo window', async () => {
    const membersHook = renderHook(() => useTeamMembers());
    const removeHook = renderHook(() => useRemoveMember());

    await waitFor(() => expect(membersHook.result.current.isLoading).toBe(false));
    vi.useFakeTimers();

    const mutationPromise = removeHook.result.current.mutateAsync('1');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(REMOVE_UNDO_WINDOW_MS + 1);
    });

    await expect(mutationPromise).resolves.toEqual({ success: true });
    expect(mocked.removeMember).toHaveBeenCalledWith('1');
  });
});
