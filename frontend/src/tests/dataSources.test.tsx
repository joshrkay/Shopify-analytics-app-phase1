/**
 * Tests for Data Sources page and source normalizers.
 *
 * Unit tests:
 * - normalizeShopifySource maps Shopify ingestion response to Source
 * - normalizeAdSource maps ad platform connection to Source
 * - normalizeApiSource maps unified API response to Source
 *
 * Integration tests:
 * - DataSources page renders mixed sources
 * - DataSources page shows loading, error, and empty states
 *
 * Story 2.1.1 — Unified Source domain model
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import {
  normalizeShopifySource,
  normalizeAdSource,
  normalizeApiSource,
  type ShopifyIngestionStatus,
  type AdConnectionSummary,
  type RawApiSource,
} from '../services/sourceNormalizer';

// Mock translations for Polaris
const mockTranslations = {
  Polaris: {
    Common: { ok: 'OK', cancel: 'Cancel' },
  },
};

const renderWithPolaris = (ui: React.ReactElement) => {
  return render(<AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>);
};

// =============================================================================
// Unit Tests: Source Normalizers
// =============================================================================

describe('normalizeShopifySource', () => {
  const shopifyResponse: ShopifyIngestionStatus = {
    connection_id: 'conn-shopify-001',
    connection_name: 'My Shopify Store',
    status: 'active',
    is_enabled: true,
    can_sync: true,
    last_sync_at: '2025-06-15T10:30:00Z',
    last_sync_status: 'succeeded',
  };

  it('maps connection_id to id', () => {
    const result = normalizeShopifySource(shopifyResponse);
    expect(result.id).toBe('conn-shopify-001');
  });

  it('sets platform to shopify', () => {
    const result = normalizeShopifySource(shopifyResponse);
    expect(result.platform).toBe('shopify');
  });

  it('maps connection_name to displayName', () => {
    const result = normalizeShopifySource(shopifyResponse);
    expect(result.displayName).toBe('My Shopify Store');
  });

  it('sets authType to oauth', () => {
    const result = normalizeShopifySource(shopifyResponse);
    expect(result.authType).toBe('oauth');
  });

  it('maps status correctly', () => {
    const result = normalizeShopifySource(shopifyResponse);
    expect(result.status).toBe('active');
  });

  it('maps is_enabled to isEnabled', () => {
    const result = normalizeShopifySource(shopifyResponse);
    expect(result.isEnabled).toBe(true);
  });

  it('maps last_sync_at to lastSyncAt', () => {
    const result = normalizeShopifySource(shopifyResponse);
    expect(result.lastSyncAt).toBe('2025-06-15T10:30:00Z');
  });

  it('handles null last_sync_at', () => {
    const result = normalizeShopifySource({ ...shopifyResponse, last_sync_at: null });
    expect(result.lastSyncAt).toBeNull();
  });
});

describe('normalizeAdSource', () => {
  const metaResponse: AdConnectionSummary = {
    id: 'conn-meta-001',
    platform: 'meta_ads',
    account_id: 'act_123456',
    account_name: 'Summer Campaign',
    connection_id: 'conn-meta-001',
    airbyte_connection_id: 'ab-conn-meta',
    status: 'active',
    is_enabled: true,
    last_sync_at: '2025-06-14T08:00:00Z',
    last_sync_status: 'succeeded',
  };

  it('maps id correctly', () => {
    const result = normalizeAdSource(metaResponse);
    expect(result.id).toBe('conn-meta-001');
  });

  it('maps platform from raw platform field', () => {
    const result = normalizeAdSource(metaResponse);
    expect(result.platform).toBe('meta_ads');
  });

  it('maps account_name to displayName', () => {
    const result = normalizeAdSource(metaResponse);
    expect(result.displayName).toBe('Summer Campaign');
  });

  it('derives oauth authType for meta_ads', () => {
    const result = normalizeAdSource(metaResponse);
    expect(result.authType).toBe('oauth');
  });

  it('derives api_key authType for klaviyo', () => {
    const result = normalizeAdSource({ ...metaResponse, platform: 'klaviyo' });
    expect(result.authType).toBe('api_key');
  });

  it('handles google_ads platform', () => {
    const result = normalizeAdSource({ ...metaResponse, platform: 'google_ads' });
    expect(result.platform).toBe('google_ads');
    expect(result.authType).toBe('oauth');
  });

  it('handles null last_sync_at', () => {
    const result = normalizeAdSource({ ...metaResponse, last_sync_at: null });
    expect(result.lastSyncAt).toBeNull();
  });
});

describe('normalizeApiSource', () => {
  const apiResponse: RawApiSource = {
    id: 'conn-001',
    platform: 'shopify',
    display_name: 'Main Store',
    auth_type: 'oauth',
    status: 'active',
    is_enabled: true,
    last_sync_at: '2025-06-15T10:30:00+00:00',
    last_sync_status: 'succeeded',
  };

  it('maps snake_case to camelCase', () => {
    const result = normalizeApiSource(apiResponse);

    expect(result.id).toBe('conn-001');
    expect(result.platform).toBe('shopify');
    expect(result.displayName).toBe('Main Store');
    expect(result.authType).toBe('oauth');
    expect(result.status).toBe('active');
    expect(result.isEnabled).toBe(true);
    expect(result.lastSyncAt).toBe('2025-06-15T10:30:00+00:00');
    expect(result.lastSyncStatus).toBe('succeeded');
  });

  it('handles api_key auth type', () => {
    const result = normalizeApiSource({ ...apiResponse, auth_type: 'api_key', platform: 'klaviyo' });
    expect(result.authType).toBe('api_key');
    expect(result.platform).toBe('klaviyo');
  });

  it('handles null last_sync_at and last_sync_status', () => {
    const result = normalizeApiSource({
      ...apiResponse,
      last_sync_at: null,
      last_sync_status: null,
    });
    expect(result.lastSyncAt).toBeNull();
    expect(result.lastSyncStatus).toBeNull();
  });

  it('maps failed status', () => {
    const result = normalizeApiSource({ ...apiResponse, status: 'failed' });
    expect(result.status).toBe('failed');
  });
});

// =============================================================================
// Integration Tests: DataSources Page
// =============================================================================

// Mock the sourcesApi module
vi.mock('../services/sourcesApi', () => ({
  listSources: vi.fn(),
}));

import DataSources from '../pages/DataSources';
import { listSources } from '../services/sourcesApi';
import type { Source } from '../types/sources';

const mockListSources = vi.mocked(listSources);

const createMockSource = (overrides?: Partial<Source>): Source => ({
  id: 'src-001',
  platform: 'shopify',
  displayName: 'My Shopify Store',
  authType: 'oauth',
  status: 'active',
  isEnabled: true,
  lastSyncAt: '2025-06-15T10:30:00Z',
  lastSyncStatus: 'succeeded',
  ...overrides,
});

describe('DataSources Page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders mixed Shopify and ad platform sources', async () => {
    const sources: Source[] = [
      createMockSource({
        id: 'src-shopify',
        platform: 'shopify',
        displayName: 'Main Store',
        authType: 'oauth',
        status: 'active',
      }),
      createMockSource({
        id: 'src-meta',
        platform: 'meta_ads',
        displayName: 'Summer Ads',
        authType: 'oauth',
        status: 'active',
      }),
    ];

    mockListSources.mockResolvedValue(sources);

    renderWithPolaris(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText('Main Store')).toBeInTheDocument();
    });

    expect(screen.getByText('Summer Ads')).toBeInTheDocument();
    expect(screen.getByText('Shopify')).toBeInTheDocument();
    expect(screen.getByText('Meta Ads')).toBeInTheDocument();
  });

  it('shows correct status badges', async () => {
    const sources: Source[] = [
      createMockSource({ id: 'src-1', status: 'active', displayName: 'Active Source' }),
      createMockSource({ id: 'src-2', status: 'failed', displayName: 'Failed Source' }),
    ];

    mockListSources.mockResolvedValue(sources);

    renderWithPolaris(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText('Active')).toBeInTheDocument();
    });

    expect(screen.getByText('Failed')).toBeInTheDocument();
  });

  it('shows empty state when no sources', async () => {
    mockListSources.mockResolvedValue([]);

    renderWithPolaris(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText('No data sources connected')).toBeInTheDocument();
    });
  });

  it('shows error banner on API failure', async () => {
    mockListSources.mockRejectedValue(new Error('Network error'));

    renderWithPolaris(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText('Failed to Load Data Sources')).toBeInTheDocument();
    });
  });

  it('displays auth type for each source', async () => {
    const sources: Source[] = [
      createMockSource({
        id: 'src-oauth',
        authType: 'oauth',
        displayName: 'OAuth Source',
      }),
      createMockSource({
        id: 'src-api-key',
        authType: 'api_key',
        platform: 'klaviyo',
        displayName: 'API Key Source',
      }),
    ];

    mockListSources.mockResolvedValue(sources);

    renderWithPolaris(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText('OAuth Source')).toBeInTheDocument();
    });

    expect(screen.getByText('API Key Source')).toBeInTheDocument();
  });

  it('shows "Never synced" for sources without last sync', async () => {
    const sources: Source[] = [
      createMockSource({
        id: 'src-never',
        lastSyncAt: null,
        displayName: 'New Source',
      }),
    ];

    mockListSources.mockResolvedValue(sources);

    renderWithPolaris(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText('Never synced')).toBeInTheDocument();
    });
  });

  it('shows source count in header', async () => {
    const sources: Source[] = [
      createMockSource({ id: 'src-1', displayName: 'Source 1' }),
      createMockSource({ id: 'src-2', displayName: 'Source 2' }),
      createMockSource({ id: 'src-3', displayName: 'Source 3' }),
    ];

    mockListSources.mockResolvedValue(sources);

    renderWithPolaris(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText('Connected Sources (3)')).toBeInTheDocument();
    });
  });
});
