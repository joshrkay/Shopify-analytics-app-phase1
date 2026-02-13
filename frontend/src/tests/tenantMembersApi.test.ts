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

const TENANT_ID = 'tenant-123';

beforeEach(() => {
  vi.clearAllMocks();
  (globalThis as any).fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: vi.fn().mockResolvedValue({ members: [], total_count: 0, tenant_id: TENANT_ID }),
  });
});

describe('tenantMembersApi', () => {
  it('getTeamMembers sends auth header with tenant path', async () => {
    await getTeamMembers(TENANT_ID);
    expect((globalThis as any).fetch).toHaveBeenCalledWith(
      `/api/tenants/${TENANT_ID}/members`,
      expect.objectContaining({ headers: { Authorization: 'Bearer token' } }),
    );
  });

  it('inviteMember validates email format', async () => {
    await expect(inviteMember(TENANT_ID, { email: 'bad-email', role: 'admin' })).rejects.toThrow('valid email');
  });

  it('inviteMember trims email before sending payload', async () => {
    await inviteMember(TENANT_ID, { email: '  member@example.com  ', role: 'viewer' });
    expect((globalThis as any).fetch).toHaveBeenCalledWith(
      `/api/tenants/${TENANT_ID}/members`,
      expect.objectContaining({ body: JSON.stringify({ email: 'member@example.com', role: 'viewer' }) }),
    );
  });

  it('updateMemberRole sends PATCH with correct payload', async () => {
    await updateMemberRole(TENANT_ID, 'm1', 'editor');
    expect((globalThis as any).fetch).toHaveBeenCalledWith(
      `/api/tenants/${TENANT_ID}/members/m1`,
      expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ role: 'editor' }) }),
    );
  });

  it('removeMember calls correct endpoint', async () => {
    await removeMember(TENANT_ID, 'm1');
    expect((globalThis as any).fetch).toHaveBeenCalledWith(
      `/api/tenants/${TENANT_ID}/members/m1`,
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('resendInvite returns stub response (not yet implemented)', async () => {
    const result = await resendInvite(TENANT_ID, 'm1');
    expect(result).toEqual({ success: false });
  });

  it('All endpoints use Clerk token', async () => {
    await getTeamMembers(TENANT_ID);
    await updateMemberRole(TENANT_ID, 'm2', 'viewer');
    expect(createHeadersAsync).toHaveBeenCalledTimes(2);
  });
});
