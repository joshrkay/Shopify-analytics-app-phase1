import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/notificationsApi', () => ({
  getPerformanceAlerts: vi.fn(),
  updateNotificationPreferences: vi.fn(),
}));

import {
  usePerformanceAlerts,
  useUpdateNotificationPreferences,
} from '../hooks/useNotificationPreferences';
import {
  getPerformanceAlerts,
  updateNotificationPreferences,
} from '../services/notificationsApi';

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
});

describe('useUpdateNotificationPreferences edge cases', () => {
  it('rejects older debounced call when replaced by a newer request', async () => {
    vi.mocked(updateNotificationPreferences).mockResolvedValue({} as never);
    const { result } = renderHook(() => useUpdateNotificationPreferences());

    const firstCall = result.current({ quietHours: { enabled: true } } as never).catch((error) => error);
    const secondCall = result.current({ quietHours: { enabled: false } } as never);

    await act(async () => {
      vi.advanceTimersByTime(500);
      await secondCall;
    });

    await expect(firstCall).resolves.toBeInstanceOf(Error);
    await expect(firstCall).resolves.toMatchObject({ message: expect.stringContaining('Debounced update replaced') });
    expect(updateNotificationPreferences).toHaveBeenCalledTimes(1);
  });

  it('rejects pending call when component unmounts', async () => {
    vi.mocked(updateNotificationPreferences).mockResolvedValue({} as never);
    const { result, unmount } = renderHook(() => useUpdateNotificationPreferences());

    const pendingCall = result.current({ quietHours: { enabled: true } } as never).catch((error) => error);
    unmount();

    await expect(pendingCall).resolves.toBeInstanceOf(Error);
    await expect(pendingCall).resolves.toMatchObject({ message: expect.stringContaining('component unmounted') });
  });
});

describe('usePerformanceAlerts edge cases', () => {
  it('captures errors instead of leaking unhandled promise rejections', async () => {
    vi.useRealTimers();
    vi.mocked(getPerformanceAlerts).mockRejectedValue(new Error('alerts failed'));

    const { result } = renderHook(() => usePerformanceAlerts());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toContain('alerts failed');
  });
});
