import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  getNotificationPreferences,
  getPerformanceAlerts,
  updateNotificationPreferences,
  updatePerformanceAlert,
} from '../services/notificationsApi';
import type { NotificationPreferences, PerformanceAlert } from '../types/settingsTypes';

export function useNotificationPreferences() {
  const [preferences, setPreferences] = useState<NotificationPreferences | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      setPreferences(await getNotificationPreferences());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load notification preferences');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { preferences, isLoading, error, refetch, setPreferences };
}

export function useUpdateNotificationPreferences() {
  return useMemo(() => {
    let timeoutId: ReturnType<typeof setTimeout> | undefined;

    return (prefs: Partial<NotificationPreferences>) =>
      new Promise<NotificationPreferences>((resolve, reject) => {
        if (timeoutId) clearTimeout(timeoutId);
        timeoutId = setTimeout(async () => {
          try {
            resolve(await updateNotificationPreferences(prefs));
          } catch (err) {
            reject(err);
          }
        }, 500);
      });
  }, []);
}

export function usePerformanceAlerts() {
  const [alerts, setAlerts] = useState<PerformanceAlert[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const refetch = useCallback(async () => {
    setIsLoading(true);
    try {
      setAlerts(await getPerformanceAlerts());
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { alerts, isLoading, refetch };
}

export function useUpdatePerformanceAlert() {
  return useCallback((alertId: string, alert: Partial<PerformanceAlert>) => updatePerformanceAlert(alertId, alert), []);
}
