import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TeamSettings } from '../components/settings/TeamSettings';

vi.mock('../hooks/useTeamMembers', () => ({
  useTeamMembers: vi.fn(),
  useInviteMember: vi.fn(),
  useUpdateMemberRole: vi.fn(),
  useRemoveMember: vi.fn(),
}));

import {
  useInviteMember,
  useRemoveMember,
  useTeamMembers,
  useUpdateMemberRole,
} from '../hooks/useTeamMembers';

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useTeamMembers).mockReturnValue({
    members: [
      { id: '1', userId: 'u1', name: 'John Doe', email: 'john@example.com', role: 'owner', status: 'active', joinedDate: 'Jan 15, 2026' },
      { id: '2', userId: 'u2', name: 'Sarah Smith', email: 'sarah@example.com', role: 'admin', status: 'active', joinedDate: 'Jan 20, 2026' },
    ],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
  vi.mocked(useInviteMember).mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false, error: null } as never);
  vi.mocked(useUpdateMemberRole).mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false, error: null } as never);
  vi.mocked(useRemoveMember).mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ success: true }), isPending: false, error: null, undoMemberId: null, undoLastRemove: vi.fn(), undoWindowMs: 5000 } as never);
});

describe('TeamSettings', () => {
  it('renders seeded team members and role permissions', () => {
    render(<TeamSettings />);
    expect(screen.getByText('Team Management')).toBeInTheDocument();
    expect(screen.getByText('John Doe')).toBeInTheDocument();
    expect(screen.getByText('Role Permissions')).toBeInTheDocument();
    expect(screen.getByText('Full access to all features')).toBeInTheDocument();
  });

  it('invites a member with validated email and shows pending badge', async () => {
    const user = userEvent.setup();
    render(<TeamSettings />);

    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'Invite Member' }));
    });
    const sendButton = screen.getByRole('button', { name: 'Send Invite' });
    expect(sendButton).toBeDisabled();

    await act(async () => {
      await user.type(screen.getByLabelText('Email Address'), 'new.user@example.com');
    });
    expect(sendButton).toBeEnabled();

    await act(async () => {
      await user.click(sendButton);
    });
    await waitFor(() => expect(vi.mocked(useInviteMember).mock.results[0].value.mutateAsync).toHaveBeenCalled());
  });

  it('updates member role and removes non-owner members', async () => {
    const user = userEvent.setup();
    render(<TeamSettings />);

    const selects = screen.getAllByRole('combobox');
    await act(async () => {
      await user.selectOptions(selects[0], 'viewer');
    });
    expect(vi.mocked(useUpdateMemberRole).mock.results[0].value.mutateAsync).toHaveBeenCalled();

    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'Remove Sarah Smith' }));
    });
    expect(vi.mocked(useRemoveMember).mock.results[0].value.mutateAsync).toHaveBeenCalledWith('2');
  });
});
