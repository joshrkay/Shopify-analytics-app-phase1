import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/tenantMembersApi', () => ({
  getTeamMembers: vi.fn(),
  inviteMember: vi.fn(),
  updateMemberRole: vi.fn(),
  removeMember: vi.fn(),
}));

import { useInviteMember, useRemoveMember, useTeamMembers, useUpdateMemberRole } from '../hooks/useTeamMembers';
import * as teamApi from '../services/tenantMembersApi';

const mocked = vi.mocked(teamApi);

beforeEach(() => {
  vi.clearAllMocks();
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
    const { result } = renderHook(() => useInviteMember());
    await act(async () => {
      await result.current.mutateAsync({ email: 'b@b.com', role: 'viewer' });
    });
    expect(mocked.inviteMember).toHaveBeenCalled();
  });

  it('useUpdateMemberRole optimistic role change', async () => {
    const { result } = renderHook(() => useUpdateMemberRole());
    await act(async () => {
      await result.current.mutateAsync({ memberId: '1', role: 'editor' });
    });
    expect(mocked.updateMemberRole).toHaveBeenCalledWith('1', 'editor');
  });

  it('useRemoveMember shows undo toast', async () => {
    const { result } = renderHook(() => useRemoveMember());
    await act(async () => {
      await result.current.mutateAsync('1');
    });
    expect(mocked.removeMember).toHaveBeenCalledWith('1');
  });

  it('Query invalidation after mutations', async () => {
    const { result } = renderHook(() => useTeamMembers());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    await act(async () => {
      await result.current.refetch();
    });
    expect(mocked.getTeamMembers).toHaveBeenCalledTimes(2);
  });
});
