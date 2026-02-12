/**
 * Tests for useConnectSourceWizard hook
 *
 * Tests the 6-step wizard state machine: step transitions,
 * API calls, account management, and sync triggering.
 *
 * Phase 3 — Subphase 3.4/3.5: Connection Wizard Hook
 */

import { renderHook, act } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/dataSourcesApi', () => ({
  initiateOAuth: vi.fn(),
  completeOAuth: vi.fn(),
  updateSyncConfig: vi.fn(),
  triggerSync: vi.fn(),
  getSyncProgress: vi.fn(),
  getAvailableAccounts: vi.fn(),
  updateSelectedAccounts: vi.fn(),
  listSources: vi.fn(),
  getConnections: vi.fn(),
  getAvailableSources: vi.fn(),
  disconnectSource: vi.fn(),
  testConnection: vi.fn(),
}));

vi.mock('../services/apiUtils', () => ({
  getErrorMessage: vi.fn((err: unknown, fallback: string) =>
    err instanceof Error ? err.message : fallback,
  ),
}));

import { useConnectSourceWizard } from '../hooks/useConnectSourceWizard';
import * as api from '../services/dataSourcesApi';
import type { DataSourceDefinition } from '../types/sourceConnection';

const mocked = vi.mocked(api);

const mockAdsPlatform: DataSourceDefinition = {
  id: 'meta_ads',
  platform: 'meta_ads',
  displayName: 'Meta Ads',
  description: 'Connect your Facebook and Instagram ad accounts',
  authType: 'oauth',
  category: 'ads',
  isEnabled: true,
};

const mockShopifyPlatform: DataSourceDefinition = {
  id: 'shopify',
  platform: 'shopify',
  displayName: 'Shopify',
  description: 'Connect your Shopify store',
  authType: 'oauth',
  category: 'ecommerce',
  isEnabled: true,
};

const mockAccounts = [
  { id: 'acc-1', accountId: 'act_111', accountName: 'Campaign A', platform: 'meta_ads', isEnabled: true },
  { id: 'acc-2', accountId: 'act_222', accountName: 'Campaign B', platform: 'meta_ads', isEnabled: false },
];

beforeEach(() => {
  vi.clearAllMocks();
  // Suppress window.open in test environment
  vi.spyOn(window, 'open').mockReturnValue({} as Window);
  mocked.getAvailableAccounts.mockResolvedValue(mockAccounts);
  mocked.updateSelectedAccounts.mockResolvedValue(undefined);
  mocked.updateSyncConfig.mockResolvedValue(undefined);
  mocked.triggerSync.mockResolvedValue(undefined);
});

describe('useConnectSourceWizard', () => {
  it('initializes with intro step and null platform', () => {
    const { result } = renderHook(() => useConnectSourceWizard());

    expect(result.current.state.step).toBe('intro');
    expect(result.current.state.platform).toBeNull();
  });

  it('initWithPlatform sets platform and stays on intro step', () => {
    const { result } = renderHook(() => useConnectSourceWizard());

    act(() => {
      result.current.initWithPlatform(mockAdsPlatform);
    });

    expect(result.current.state.platform).toEqual(mockAdsPlatform);
    expect(result.current.state.step).toBe('intro');
  });

  it('proceedFromIntro advances to oauth step', () => {
    const { result } = renderHook(() => useConnectSourceWizard());

    act(() => {
      result.current.initWithPlatform(mockAdsPlatform);
    });
    act(() => {
      result.current.proceedFromIntro();
    });

    expect(result.current.state.step).toBe('oauth');
  });

  it('startOAuth calls initiateOAuth and opens popup', async () => {
    mocked.initiateOAuth.mockResolvedValue({
      authorization_url: 'https://fb.com/oauth',
      state: 'csrf-token',
    });

    const { result } = renderHook(() => useConnectSourceWizard());

    act(() => {
      result.current.initWithPlatform(mockAdsPlatform);
    });
    act(() => {
      result.current.proceedFromIntro();
    });

    await act(async () => {
      await result.current.startOAuth();
    });

    expect(mocked.initiateOAuth).toHaveBeenCalledWith('meta_ads');
    expect(window.open).toHaveBeenCalled();
    expect(result.current.state.oauthState).toBe('csrf-token');
  });

  it('handleOAuthComplete for ads platform advances to accounts step', async () => {
    mocked.completeOAuth.mockResolvedValue({
      success: true,
      connection_id: 'conn-123',
      message: 'OK',
    });

    const { result } = renderHook(() => useConnectSourceWizard());

    act(() => {
      result.current.initWithPlatform(mockAdsPlatform);
    });

    await act(async () => {
      await result.current.handleOAuthComplete({ code: 'auth-code', state: 'csrf' });
    });

    expect(result.current.state.step).toBe('accounts');
    expect(result.current.state.connectionId).toBe('conn-123');
  });

  it('handleOAuthComplete for non-ads platform advances to syncConfig step', async () => {
    mocked.completeOAuth.mockResolvedValue({
      success: true,
      connection_id: 'conn-456',
      message: 'OK',
    });

    const { result } = renderHook(() => useConnectSourceWizard());

    act(() => {
      result.current.initWithPlatform(mockShopifyPlatform);
    });

    await act(async () => {
      await result.current.handleOAuthComplete({ code: 'auth-code', state: 'csrf' });
    });

    expect(result.current.state.step).toBe('syncConfig');
    expect(result.current.state.connectionId).toBe('conn-456');
  });

  it('toggleAccount adds and removes accounts from selection', async () => {
    mocked.completeOAuth.mockResolvedValue({
      success: true,
      connection_id: 'conn-123',
      message: 'OK',
    });

    const { result } = renderHook(() => useConnectSourceWizard());

    act(() => {
      result.current.initWithPlatform(mockAdsPlatform);
    });

    await act(async () => {
      await result.current.handleOAuthComplete({ code: 'code', state: 'state' });
    });

    // Pre-selected: acc-1 (isEnabled=true)
    expect(result.current.state.selectedAccountIds).toContain('acc-1');

    // Toggle off
    act(() => {
      result.current.toggleAccount('acc-1');
    });
    expect(result.current.state.selectedAccountIds).not.toContain('acc-1');

    // Toggle on
    act(() => {
      result.current.toggleAccount('acc-1');
    });
    expect(result.current.state.selectedAccountIds).toContain('acc-1');
  });

  it('selectAllAccounts selects all available accounts', async () => {
    mocked.completeOAuth.mockResolvedValue({
      success: true,
      connection_id: 'conn-123',
      message: 'OK',
    });

    const { result } = renderHook(() => useConnectSourceWizard());

    act(() => {
      result.current.initWithPlatform(mockAdsPlatform);
    });

    await act(async () => {
      await result.current.handleOAuthComplete({ code: 'code', state: 'state' });
    });

    act(() => {
      result.current.selectAllAccounts();
    });

    expect(result.current.state.selectedAccountIds).toEqual(['acc-1', 'acc-2']);
  });

  it('confirmAccounts calls updateSelectedAccounts and advances to syncConfig', async () => {
    mocked.completeOAuth.mockResolvedValue({
      success: true,
      connection_id: 'conn-123',
      message: 'OK',
    });

    const { result } = renderHook(() => useConnectSourceWizard());

    act(() => {
      result.current.initWithPlatform(mockAdsPlatform);
    });

    await act(async () => {
      await result.current.handleOAuthComplete({ code: 'code', state: 'state' });
    });

    await act(async () => {
      await result.current.confirmAccounts();
    });

    expect(mocked.updateSelectedAccounts).toHaveBeenCalledWith('conn-123', ['acc-1']);
    expect(result.current.state.step).toBe('syncConfig');
  });

  it('reset returns to initial state', async () => {
    const { result } = renderHook(() => useConnectSourceWizard());

    act(() => {
      result.current.initWithPlatform(mockAdsPlatform);
    });
    act(() => {
      result.current.proceedFromIntro();
    });

    expect(result.current.state.step).toBe('oauth');

    act(() => {
      result.current.reset();
    });

    expect(result.current.state.step).toBe('intro');
    expect(result.current.state.platform).toBeNull();
    expect(result.current.state.connectionId).toBeNull();
  });
});
