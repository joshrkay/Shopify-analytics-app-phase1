import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/apiUtils', () => ({
  API_BASE_URL: '',
  createHeadersAsync: vi.fn().mockResolvedValue({ Authorization: 'Bearer token' }),
  handleResponse: vi.fn(async (res: Response) => {
    if (!res.ok) {
      const err = new Error('payment required') as Error & { status: number };
      err.status = 402;
      throw err;
    }
    return res.json();
  }),
}));

import {
  cancelSubscription,
  changePlan,
  getInvoices,
  getSubscription,
  getUsageMetrics,
} from '../services/billingApi';

beforeEach(() => {
  vi.clearAllMocks();
  global.fetch = vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue({}) });
});

describe('billingApi', () => {
  it('getSubscription returns current subscription', async () => {
    const payload = { id: 's1', planId: 'pro', status: 'active', currentPeriodEnd: 'x', cancelAtPeriodEnd: false };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue(payload) });
    await expect(getSubscription()).resolves.toEqual(payload);
  });

  it('getInvoices returns sorted list', async () => {
    const payload = [
      { id: 'i1', date: '2025-01-01', amount: '1', status: 'paid' },
      { id: 'i2', date: '2025-02-01', amount: '1', status: 'paid' },
    ];
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue(payload) });
    const result = await getInvoices();
    expect(result.map((i) => i.id)).toEqual(['i2', 'i1']);
  });

  it('getInvoices keeps invalid dates at the end without throwing', async () => {
    const payload = [
      { id: 'valid', date: '2025-02-01', amount: '1', status: 'paid' },
      { id: 'invalid', date: 'not-a-date', amount: '1', status: 'paid' },
    ];
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue(payload) });
    const result = await getInvoices();
    expect(result.map((i) => i.id)).toEqual(['valid', 'invalid']);
  });

  it('getUsageMetrics returns all metric fields', async () => {
    const payload = { dataSourcesUsed: 1, teamMembersUsed: 2, dashboardsUsed: 3, storageUsedGb: 4, storageLimitGb: 5, aiRequestsUsed: 6, aiRequestsLimit: 7 };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue(payload) });
    await expect(getUsageMetrics()).resolves.toEqual(payload);
  });

  it('changePlan sends planId and interval', async () => {
    await changePlan('pro', 'month');
    expect(global.fetch).toHaveBeenCalledWith('/api/billing/subscription', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ planId: 'pro', interval: 'month' }) }));
  });

  it('cancelSubscription calls DELETE', async () => {
    await cancelSubscription();
    expect(global.fetch).toHaveBeenCalledWith('/api/billing/subscription', expect.objectContaining({ method: 'DELETE' }));
  });

  it('Error handling for 402 (payment required)', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, json: vi.fn().mockResolvedValue({ detail: 'payment required' }) });
    await expect(getSubscription()).rejects.toMatchObject({ status: 402 });
  });
});
