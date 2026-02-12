import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getNotificationPreferences,
  getPerformanceAlerts,
  updateNotificationPreferences,
  updatePerformanceAlert,
} from '../services/notificationsApi';
import type { NotificationPreferences, PerformanceAlert } from '../types/settingsTypes';

const DEBOUNCE_REPLACED_ERROR = 'Debounced update replaced by a newer request.';
const DEBOUNCE_CANCELLED_ERROR = 'Debounced update cancelled because the component unmounted.';

export function useNotificationPreferences() {
  const [preferences, setPreferences] = useState<NotificationPreferences | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const isMountedRef = useRef(true);

  useEffect(() => () => {
    isMountedRef.current = false;
  }, []);

  const refetch = useCallback(async () => {
    try {
      if (isMountedRef.current) {
        setIsLoading(true);
        setError(null);
      }

      const nextPreferences = await getNotificationPreferences();

      if (isMountedRef.current) {
        setPreferences(nextPreferences);
      }
    } catch (err) {
      if (isMountedRef.current) {
        setError(err instanceof Error ? err.message : 'Failed to load notification preferences');
      }
    } finally {
      if (isMountedRef.current) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { preferences, isLoading, error, refetch, setPreferences };
}

export function useUpdateNotificationPreferences() {
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

  return useCallback((prefs: Partial<NotificationPreferences>) =>
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
    }), []);
}

export function usePerformanceAlerts() {
  const [alerts, setAlerts] = useState<PerformanceAlert[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isMountedRef = useRef(true);

  useEffect(() => () => {
    isMountedRef.current = false;
  }, []);

  const refetch = useCallback(async () => {
    if (isMountedRef.current) {
      setIsLoading(true);
      setError(null);
    }

    try {
      const nextAlerts = await getPerformanceAlerts();
      if (isMountedRef.current) {
        setAlerts(nextAlerts);
      }
    } catch (err) {
      if (isMountedRef.current) {
        setError(err instanceof Error ? err.message : 'Failed to load performance alerts');
      }
    } finally {
      if (isMountedRef.current) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { alerts, isLoading, error, refetch };
}

export function useUpdatePerformanceAlert() {
  return useCallback((alertId: string, alert: Partial<PerformanceAlert>) => updatePerformanceAlert(alertId, alert), []);
}
