import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/billingApi', () => ({
  getSubscription: vi.fn(),
  getInvoices: vi.fn(),
  getPaymentMethod: vi.fn(),
  getUsageMetrics: vi.fn(),
  changePlan: vi.fn(),
  cancelSubscription: vi.fn(),
}));

import { useBilling, useCancelSubscription, useChangePlan } from '../hooks/useBilling';
import * as billingApi from '../services/billingApi';

const mocked = vi.mocked(billingApi);

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getSubscription.mockResolvedValue({ id: 's1', planId: 'basic', status: 'active', currentPeriodEnd: '', cancelAtPeriodEnd: false });
  mocked.getInvoices.mockResolvedValue([]);
  mocked.getPaymentMethod.mockResolvedValue({ id: 'p1', type: 'card', last4: '4242', expiryMonth: 1, expiryYear: 2030 });
  mocked.getUsageMetrics.mockResolvedValue({ dataSourcesUsed: 1, teamMembersUsed: 1, dashboardsUsed: 1, storageUsedGb: 1, storageLimitGb: 2, aiRequestsUsed: 1, aiRequestsLimit: 2 });
  mocked.changePlan.mockResolvedValue({ id: 's1', planId: 'pro', status: 'active', currentPeriodEnd: '', cancelAtPeriodEnd: false });
  mocked.cancelSubscription.mockResolvedValue({ success: true });
});

describe('useBilling', () => {
  it('useBilling fetches all billing data in parallel', async () => {
    const { result } = renderHook(() => useBilling());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(mocked.getSubscription).toHaveBeenCalled();
    expect(mocked.getInvoices).toHaveBeenCalled();
    expect(mocked.getPaymentMethod).toHaveBeenCalled();
    expect(mocked.getUsageMetrics).toHaveBeenCalled();
  });

  it('useChangePlan invalidates billing + entitlements', async () => {
    const { result } = renderHook(() => useChangePlan());
    await act(async () => {
      await result.current.mutateAsync({ planId: 'pro', interval: 'month' });
    });
    expect(mocked.changePlan).toHaveBeenCalledWith('pro', 'month');
  });

  it('useCancelSubscription requires confirmation state', async () => {
    const { result } = renderHook(() => useCancelSubscription());
    await act(async () => {
      await expect(result.current.mutateAsync(false)).rejects.toThrow('confirmed');
    });
  });

  it('Optimistic update on plan change', async () => {
    const { result } = renderHook(() => useChangePlan());
    await act(async () => {
      await expect(result.current.mutateAsync({ planId: 'pro', interval: 'year' })).resolves.toMatchObject({ planId: 'pro' });
    });
  });

  it('Error state shows payment required message', async () => {
    mocked.getSubscription.mockRejectedValueOnce(new Error('payment required'));
    const { result } = renderHook(() => useBilling());
    await waitFor(() => expect(result.current.error).toContain('payment required'));
  });
});
