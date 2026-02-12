import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/apiUtils', () => ({
  API_BASE_URL: '',
  createHeadersAsync: vi.fn().mockResolvedValue({ Authorization: 'Bearer token' }),
  handleResponse: vi.fn(async (res: Response) => res.json()),
}));

import {
  getTeamMembers,
  inviteMember,
  removeMember,
  resendInvite,
  updateMemberRole,
} from '../services/tenantMembersApi';
import { createHeadersAsync } from '../services/apiUtils';

beforeEach(() => {
  vi.clearAllMocks();
  global.fetch = vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue([]) });
});

describe('tenantMembersApi', () => {
  it('getTeamMembers sends auth header', async () => {
    await getTeamMembers();
    expect(global.fetch).toHaveBeenCalledWith('/api/tenant-members', expect.objectContaining({ headers: { Authorization: 'Bearer token' } }));
  });

  it('inviteMember validates email format', async () => {
    await expect(inviteMember({ email: 'bad-email', role: 'admin' })).rejects.toThrow('valid email');
  });

  it('inviteMember trims email before sending payload', async () => {
    await inviteMember({ email: '  member@example.com  ', role: 'viewer' });
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/tenant-members/invite',
      expect.objectContaining({ body: JSON.stringify({ email: 'member@example.com', role: 'viewer' }) }),
    );
  });

  it('updateMemberRole sends correct payload', async () => {
    await updateMemberRole('m1', 'editor');
    expect(global.fetch).toHaveBeenCalledWith('/api/tenant-members/m1/role', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ role: 'editor' }) }));
  });

  it('removeMember calls correct endpoint', async () => {
    await removeMember('m1');
    expect(global.fetch).toHaveBeenCalledWith('/api/tenant-members/m1', expect.objectContaining({ method: 'DELETE' }));
  });

  it('resendInvite calls correct endpoint', async () => {
    await resendInvite('m1');
    expect(global.fetch).toHaveBeenCalledWith('/api/tenant-members/m1/resend', expect.objectContaining({ method: 'POST' }));
  });

  it('All endpoints use Clerk token', async () => {
    await getTeamMembers();
    await updateMemberRole('m2', 'viewer');
    expect(createHeadersAsync).toHaveBeenCalledTimes(2);
  });
});
