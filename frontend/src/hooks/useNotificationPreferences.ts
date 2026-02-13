import { useEffect, useRef } from 'react';
import {
  getNotificationPreferences,
  getPerformanceAlerts,
  updateNotificationPreferences,
  updatePerformanceAlert,
} from '../services/notificationsApi';
import type { NotificationPreferences, PerformanceAlert } from '../types/settingsTypes';
import { useMutationLite, useQueryClientLite, useQueryLite } from './queryClientLite';

const DEBOUNCE_REPLACED_ERROR = 'Debounced update replaced by a newer request.';
const DEBOUNCE_CANCELLED_ERROR = 'Debounced update cancelled because the component unmounted.';
const NOTIFICATION_QUERY_KEYS = {
  preferences: ['settings', 'notifications', 'preferences'] as const,
  alerts: ['settings', 'notifications', 'alerts'] as const,
};

export function useNotificationPreferences() {
  const query = useQueryLite({
    queryKey: NOTIFICATION_QUERY_KEYS.preferences,
    queryFn: getNotificationPreferences,
  });

  return {
    preferences: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error.message : null,
    refetch: query.refetch,
  };
}

export function useUpdateNotificationPreferences() {
  const queryClient = useQueryClientLite();
  const timeoutIdRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingRejectRef = useRef<((reason?: unknown) => void) | null>(null);

  useEffect(() => () => {
    if (timeoutIdRef.current) {
      clearTimeout(timeoutIdRef.current);
      timeoutIdRef.current = null;
    }

    if (pendingRejectRef.current) {
      pendingRejectRef.current(new Error(DEBOUNCE_CANCELLED_ERROR));
      pendingRejectRef.current = null;
    }
  }, []);

  const mutation = useMutationLite({
    mutationFn: (prefs: Partial<NotificationPreferences>) =>
      new Promise<NotificationPreferences>((resolve, reject) => {
        if (timeoutIdRef.current) {
          clearTimeout(timeoutIdRef.current);
        }

        if (pendingRejectRef.current) {
          pendingRejectRef.current(new Error(DEBOUNCE_REPLACED_ERROR));
        }

        pendingRejectRef.current = reject;

        timeoutIdRef.current = setTimeout(async () => {
          try {
            const updatedPreferences = await updateNotificationPreferences(prefs);
            pendingRejectRef.current = null;
            timeoutIdRef.current = null;
            resolve(updatedPreferences);
          } catch (err) {
            pendingRejectRef.current = null;
            timeoutIdRef.current = null;
            reject(err);
          }
        }, 500);
      }),
    onSuccess: () => {
      queryClient.invalidateQueries(NOTIFICATION_QUERY_KEYS.preferences);
    },
  });

  return mutation;
}

export function usePerformanceAlerts() {
  const query = useQueryLite({
    queryKey: NOTIFICATION_QUERY_KEYS.alerts,
    queryFn: getPerformanceAlerts,
  });

  return {
    alerts: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error.message : null,
    refetch: query.refetch,
  };
}

export function useUpdatePerformanceAlert() {
  const queryClient = useQueryClientLite();

  return useMutationLite({
    mutationFn: ({ alertId, alert }: { alertId: string; alert: Partial<PerformanceAlert> }) =>
      updatePerformanceAlert(alertId, alert),
    onSuccess: () => {
      queryClient.invalidateQueries(NOTIFICATION_QUERY_KEYS.alerts);
      queryClient.invalidateQueries(NOTIFICATION_QUERY_KEYS.preferences);
    },
  });
}

export { NOTIFICATION_QUERY_KEYS };
