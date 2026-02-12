import { API_BASE_URL, createHeadersAsync, handleResponse } from './apiUtils';
import type { NotificationPreferences, PerformanceAlert } from '../types/settingsTypes';

export async function getNotificationPreferences(): Promise<NotificationPreferences> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/notifications/preferences`, { method: 'GET', headers });
  return handleResponse<NotificationPreferences>(response);
}

export async function updateNotificationPreferences(
  prefs: Partial<NotificationPreferences>,
): Promise<NotificationPreferences> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/notifications/preferences`, {
    method: 'PUT',
    headers,
    body: JSON.stringify(prefs),
  });
  return handleResponse<NotificationPreferences>(response);
}

export async function getPerformanceAlerts(): Promise<PerformanceAlert[]> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/notifications/alerts`, { method: 'GET', headers });
  return handleResponse<PerformanceAlert[]>(response);
}

export async function updatePerformanceAlert(
  alertId: string,
  alert: Partial<PerformanceAlert>,
): Promise<PerformanceAlert> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/notifications/alerts/${alertId}`, {
    method: 'PUT',
    headers,
    body: JSON.stringify(alert),
  });
  return handleResponse<PerformanceAlert>(response);
}

export async function testNotification(channel: string): Promise<{ success: boolean }> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/notifications/test`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ channel }),
  });
  return handleResponse<{ success: boolean }>(response);
}
