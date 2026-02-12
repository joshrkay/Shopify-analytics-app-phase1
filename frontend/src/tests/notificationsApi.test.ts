import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/apiUtils', () => ({
  API_BASE_URL: '',
  createHeadersAsync: vi.fn().mockResolvedValue({ Authorization: 'Bearer token' }),
  handleResponse: vi.fn(async (res: Response) => res.json()),
}));

import {
  getNotificationPreferences,
  getPerformanceAlerts,
  testNotification,
  updateNotificationPreferences,
  updatePerformanceAlert,
} from '../services/notificationsApi';

beforeEach(() => {
  vi.clearAllMocks();
  global.fetch = vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue({}) });
});

describe('notificationsApi', () => {
  it('getNotificationPreferences returns full shape', async () => {
    const payload = { deliveryMethods: {}, syncNotifications: {}, performanceAlerts: [], reportSchedules: [], quietHours: {} };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue(payload) });
    await expect(getNotificationPreferences()).resolves.toEqual(payload);
  });

  it('updateNotificationPreferences sends partial update', async () => {
    await updateNotificationPreferences({ quietHours: { enabled: true } } as never);
    expect(global.fetch).toHaveBeenCalledWith('/api/notifications/preferences', expect.objectContaining({ method: 'PUT' }));
  });

  it('getPerformanceAlerts returns alert list', async () => {
    const payload = [{ id: 'a1' }];
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue(payload) });
    await expect(getPerformanceAlerts()).resolves.toEqual(payload);
  });

  it('updatePerformanceAlert sends threshold update', async () => {
    await updatePerformanceAlert('a1', { threshold: '> 10m' });
    expect(global.fetch).toHaveBeenCalledWith('/api/notifications/alerts/a1', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ threshold: '> 10m' }) }));
  });

  it('testNotification sends channel type', async () => {
    await testNotification('email');
    expect(global.fetch).toHaveBeenCalledWith('/api/notifications/test', expect.objectContaining({ body: JSON.stringify({ channel: 'email' }) }));
  });
});
