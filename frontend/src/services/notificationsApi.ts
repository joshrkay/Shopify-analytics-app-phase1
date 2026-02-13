import type { NotificationPreferences, PerformanceAlert } from '../types/settingsTypes';

// Backend notifications.py serves notification items (unread count, mark read),
// NOT preferences/alerts/test. These endpoints have no backend implementation.
// Return sensible defaults to prevent the Settings page from crashing.
const NOT_IMPLEMENTED_MSG = 'Notification preferences: backend endpoints not yet implemented';

export async function getNotificationPreferences(): Promise<NotificationPreferences> {
  console.warn(NOT_IMPLEMENTED_MSG);
  return {} as NotificationPreferences;
}

export async function updateNotificationPreferences(
  _prefs: Partial<NotificationPreferences>,
): Promise<NotificationPreferences> {
  console.warn(NOT_IMPLEMENTED_MSG);
  return getNotificationPreferences();
}

export async function getPerformanceAlerts(): Promise<PerformanceAlert[]> {
  console.warn(NOT_IMPLEMENTED_MSG);
  return [];
}

export async function updatePerformanceAlert(
  _alertId: string,
  _alert: Partial<PerformanceAlert>,
): Promise<PerformanceAlert> {
  console.warn(NOT_IMPLEMENTED_MSG);
  throw new Error('Performance alert updates are not yet available');
}

export async function testNotification(_channel: string): Promise<{ success: boolean }> {
  console.warn(NOT_IMPLEMENTED_MSG);
  return { success: false };
}
