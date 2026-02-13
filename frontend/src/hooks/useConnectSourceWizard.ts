/**
 * useConnectSourceWizard Hook
 *
 * 6-step wizard state machine for connecting new data sources:
 * 1. intro — Source info, features, permissions
 * 2. oauth — OAuth redirect/popup flow
 * 3. accounts — Select ad accounts (ads platforms only)
 * 4. syncConfig — Historical range, frequency
 * 5. syncing — Real-time sync progress polling
 * 6. success — Confirmation + next steps
 *
 * Follows useConnectionWizard pattern (useState + useCallback).
 *
 * Phase 3 — Subphase 3.4/3.5: Connect Source Wizard
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import type {
  DataSourceDefinition,
  WizardStep,
  WizardSyncConfig,
  ConnectSourceWizardState,
  OAuthCallbackParams,
} from '../types/sourceConnection';
import {
  initiateOAuth,
  completeOAuth,
  updateSyncConfig,
  triggerSync,
  getSyncProgressDetailed,
  getAvailableAccounts,
  updateSelectedAccounts,
} from '../services/dataSourcesApi';
import { getErrorMessage } from '../services/apiUtils';

// =============================================================================
// Constants
// =============================================================================

const DEFAULT_SYNC_CONFIG: WizardSyncConfig = {
  historicalRange: '90d',
  frequency: 'hourly',
  enabledMetrics: [],
};

const INITIAL_STATE: ConnectSourceWizardState = {
  step: 'intro',
  platform: null,
  connectionId: null,
  oauthState: null,
  accounts: [],
  selectedAccountIds: [],
  syncConfig: DEFAULT_SYNC_CONFIG,
  syncProgress: null,
  error: null,
  loading: false,
};

const STEP_ORDER: WizardStep[] = ['intro', 'oauth', 'accounts', 'syncConfig', 'syncing', 'success'];

const SYNC_POLL_INTERVAL = 3_000;

// Map frequency to backend value
const FREQUENCY_TO_BACKEND: Record<string, string> = {
  hourly: 'hourly',
  six_hourly: 'six_hourly',
  daily: 'daily',
  weekly: 'weekly',
};

// =============================================================================
// Hook Result Interface
// =============================================================================

export interface UseConnectSourceWizardResult {
  state: ConnectSourceWizardState;

  // Initialization
  initWithPlatform: (platform: DataSourceDefinition) => void;

  // Step 1: Intro
  proceedFromIntro: () => void;

  // Step 2: OAuth
  startOAuth: () => Promise<void>;
  handleOAuthComplete: (params: OAuthCallbackParams) => Promise<void>;

  // Step 3: Accounts
  loadAccounts: () => Promise<void>;
  toggleAccount: (accountId: string) => void;
  selectAllAccounts: () => void;
  deselectAllAccounts: () => void;
  confirmAccounts: () => Promise<void>;

  // Step 4: Sync Config
  updateWizardSyncConfig: (config: Partial<WizardSyncConfig>) => void;
  confirmSyncConfig: () => Promise<void>;

  // Navigation
  goBack: () => void;

  // General
  setError: (error: string | null) => void;
  reset: () => void;
}

// =============================================================================
// Hook Implementation
// =============================================================================

export function useConnectSourceWizard(): UseConnectSourceWizardResult {
  const [state, setState] = useState<ConnectSourceWizardState>(INITIAL_STATE);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, []);

  // Auto-poll sync progress when on syncing step (single source of truth)
  useEffect(() => {
    if (state.step !== 'syncing' || !state.connectionId) {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      return;
    }

    const poll = async () => {
      try {
        const progress = await getSyncProgressDetailed(stateRef.current.connectionId!);

        if (progress.status === 'completed' || progress.lastSyncStatus === 'succeeded') {
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }
          setState((prev) => ({
            ...prev,
            syncProgress: { ...progress, percentComplete: 100 },
            step: 'success',
            loading: false,
            error: null,
          }));
        } else if (progress.status === 'failed' || progress.lastSyncStatus === 'failed') {
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }
          setState((prev) => ({
            ...prev,
            syncProgress: progress,
            loading: false,
            error: 'Sync failed. Please try again or check your connection.',
          }));
        } else {
          // Update progress data for display (running, pending, etc.)
          setState((prev) => ({ ...prev, syncProgress: progress }));
        }
      } catch {
        // Silently ignore poll errors; will retry on next interval
      }
    };

    // Initial poll immediately
    poll();

    pollIntervalRef.current = setInterval(poll, SYNC_POLL_INTERVAL);

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, [state.step, state.connectionId]);

  const initWithPlatform = useCallback((platform: DataSourceDefinition) => {
    setState({
      ...INITIAL_STATE,
      platform,
    });
  }, []);

  const proceedFromIntro = useCallback(() => {
    setState((prev) => ({ ...prev, step: 'oauth', error: null }));
  }, []);

  const startOAuth = useCallback(async () => {
    if (!stateRef.current.platform) {
      setState((prev) => ({ ...prev, error: 'No platform selected' }));
      return;
    }

    setState((prev) => ({ ...prev, loading: true, error: null }));

    try {
      const response = await initiateOAuth(stateRef.current.platform.platform);
      setState((prev) => ({
        ...prev,
        oauthState: response.state,
        loading: false,
      }));

      // Open OAuth in popup window
      const popup = window.open(
        response.authorization_url,
        'oauth_popup',
        'width=600,height=700,scrollbars=yes',
      );

      if (!popup) {
        setState((prev) => ({
          ...prev,
          error: 'Popup was blocked. Please allow popups and try again.',
          loading: false,
        }));
      }
    } catch (err) {
      setState((prev) => ({
        ...prev,
        error: getErrorMessage(err, 'Failed to start authorization'),
        loading: false,
      }));
    }
  }, []);

  const handleOAuthComplete = useCallback(async (params: OAuthCallbackParams) => {
    setState((prev) => ({ ...prev, loading: true, error: null }));

    try {
      const result = await completeOAuth(params);

      if (!result.success) {
        setState((prev) => ({
          ...prev,
          error: result.error ?? 'Authorization failed',
          loading: false,
        }));
        return;
      }

      const platform = stateRef.current.platform;
      const isAdsPlatform = platform?.category === 'ads';

      setState((prev) => ({
        ...prev,
        connectionId: result.connection_id,
        step: isAdsPlatform ? 'accounts' : 'syncConfig',
        loading: false,
        error: null,
      }));

      // Auto-load accounts for ads platforms
      if (isAdsPlatform && result.connection_id) {
        try {
          const accounts = await getAvailableAccounts(result.connection_id);
          setState((prev) => ({
            ...prev,
            accounts,
            selectedAccountIds: accounts.filter((a) => a.isEnabled).map((a) => a.id),
          }));
        } catch (err) {
          console.error('Failed to auto-load accounts:', err);
          // Accounts will be empty; user can still proceed
        }
      }
    } catch (err) {
      setState((prev) => ({
        ...prev,
        error: getErrorMessage(err, 'Failed to complete authorization'),
        loading: false,
      }));
    }
  }, []);

  const loadAccounts = useCallback(async () => {
    if (!stateRef.current.connectionId) return;

    setState((prev) => ({ ...prev, loading: true, error: null }));

    try {
      const accounts = await getAvailableAccounts(stateRef.current.connectionId);
      setState((prev) => ({
        ...prev,
        accounts,
        selectedAccountIds: accounts.filter((a) => a.isEnabled).map((a) => a.id),
        loading: false,
      }));
    } catch (err) {
      setState((prev) => ({
        ...prev,
        error: getErrorMessage(err, 'Failed to load accounts'),
        loading: false,
      }));
    }
  }, []);

  const toggleAccount = useCallback((accountId: string) => {
    setState((prev) => {
      const isSelected = prev.selectedAccountIds.includes(accountId);
      return {
        ...prev,
        selectedAccountIds: isSelected
          ? prev.selectedAccountIds.filter((id) => id !== accountId)
          : [...prev.selectedAccountIds, accountId],
      };
    });
  }, []);

  const selectAllAccounts = useCallback(() => {
    setState((prev) => ({
      ...prev,
      selectedAccountIds: prev.accounts.map((a) => a.id),
    }));
  }, []);

  const deselectAllAccounts = useCallback(() => {
    setState((prev) => ({ ...prev, selectedAccountIds: [] }));
  }, []);

  const confirmAccounts = useCallback(async () => {
    if (!stateRef.current.connectionId) return;

    setState((prev) => ({ ...prev, loading: true, error: null }));

    try {
      await updateSelectedAccounts(
        stateRef.current.connectionId,
        stateRef.current.selectedAccountIds,
      );
      setState((prev) => ({ ...prev, step: 'syncConfig', loading: false, error: null }));
    } catch (err) {
      setState((prev) => ({
        ...prev,
        error: getErrorMessage(err, 'Failed to save account selection'),
        loading: false,
      }));
    }
  }, []);

  const updateWizardSyncConfig = useCallback((config: Partial<WizardSyncConfig>) => {
    setState((prev) => ({
      ...prev,
      syncConfig: { ...prev.syncConfig, ...config },
    }));
  }, []);

  const confirmSyncConfig = useCallback(async () => {
    if (!stateRef.current.connectionId) return;

    setState((prev) => ({ ...prev, loading: true, error: null }));

    try {
      const freq = FREQUENCY_TO_BACKEND[stateRef.current.syncConfig.frequency] ?? 'daily';
      await updateSyncConfig(stateRef.current.connectionId, {
        sync_frequency: freq as 'hourly' | 'six_hourly' | 'daily' | 'weekly',
      });
      await triggerSync(stateRef.current.connectionId);
      setState((prev) => ({ ...prev, step: 'syncing', loading: false, error: null }));
    } catch (err) {
      setState((prev) => ({
        ...prev,
        error: getErrorMessage(err, 'Failed to start sync'),
        loading: false,
      }));
    }
  }, []);

  const goBack = useCallback(() => {
    setState((prev) => {
      const currentIndex = STEP_ORDER.indexOf(prev.step);
      if (currentIndex <= 0) return prev;

      // Skip accounts step when going back for non-ads platforms
      let prevIndex = currentIndex - 1;
      if (STEP_ORDER[prevIndex] === 'accounts' && prev.platform?.category !== 'ads') {
        prevIndex--;
      }

      if (prevIndex < 0) return prev;

      return { ...prev, step: STEP_ORDER[prevIndex], error: null };
    });
  }, []);

  const setError = useCallback((error: string | null) => {
    setState((prev) => ({ ...prev, error }));
  }, []);

  const reset = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    setState(INITIAL_STATE);
  }, []);

  return {
    state,
    initWithPlatform,
    proceedFromIntro,
    startOAuth,
    handleOAuthComplete,
    loadAccounts,
    toggleAccount,
    selectAllAccounts,
    deselectAllAccounts,
    confirmAccounts,
    updateWizardSyncConfig,
    confirmSyncConfig,
    goBack,
    setError,
    reset,
  };
}
