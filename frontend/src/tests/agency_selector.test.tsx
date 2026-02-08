/**
 * Tests for Agency Store Selector and auth utilities.
 *
 * Story 5.5.3 - Tenant Selector + JWT Refresh for Active Tenant Context
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock the agencyApi module
vi.mock('../services/agencyApi', () => ({
  refreshJwtToken: vi.fn(),
  fetchAssignedStores: vi.fn(),
  fetchUserContext: vi.fn(),
  switchActiveStore: vi.fn(),
}));

vi.mock('../services/apiUtils', () => ({
  setAuthToken: vi.fn(),
  getAuthToken: vi.fn(() => 'mock-token'),
}));

describe('detectAccessSurface', () => {
  it('returns external_app when not in iframe', async () => {
    const { detectAccessSurface } = await import('../utils/auth');

    // In test environment, window.top === window.self
    const result = detectAccessSurface();
    expect(result).toBe('external_app');
  });

  it('returns shopify_embed when in iframe', async () => {
    const { detectAccessSurface } = await import('../utils/auth');

    // Mock iframe environment
    const originalTop = window.top;
    Object.defineProperty(window, 'top', {
      value: { different: true },
      writable: true,
      configurable: true,
    });

    const result = detectAccessSurface();
    expect(result).toBe('shopify_embed');

    // Restore
    Object.defineProperty(window, 'top', {
      value: originalTop,
      writable: true,
      configurable: true,
    });
  });
});

describe('refreshTenantToken', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls refreshJwtToken and returns typed result', async () => {
    const { refreshJwtToken } = await import('../services/agencyApi');
    const { refreshTenantToken } = await import('../utils/auth');

    const mockResponse = {
      jwt_token: 'new-jwt-token',
      active_tenant_id: 'tenant-123',
      access_surface: 'external_app',
      access_expiring_at: null,
    };

    vi.mocked(refreshJwtToken).mockResolvedValueOnce(mockResponse as any);

    const result = await refreshTenantToken('tenant-123', ['tenant-123']);

    expect(refreshJwtToken).toHaveBeenCalledWith('tenant-123', ['tenant-123']);
    expect(result.jwt_token).toBe('new-jwt-token');
    expect(result.active_tenant_id).toBe('tenant-123');
    expect(result.access_expiring_at).toBeNull();
  });

  it('returns access_expiring_at when present', async () => {
    const { refreshJwtToken } = await import('../services/agencyApi');
    const { refreshTenantToken } = await import('../utils/auth');

    const expiringAt = '2026-03-01T12:00:00+00:00';
    const mockResponse = {
      jwt_token: 'new-jwt-token',
      active_tenant_id: 'tenant-123',
      access_surface: 'external_app',
      access_expiring_at: expiringAt,
    };

    vi.mocked(refreshJwtToken).mockResolvedValueOnce(mockResponse as any);

    const result = await refreshTenantToken('tenant-123');

    expect(result.access_expiring_at).toBe(expiringAt);
  });

  it('throws on 403 access expired', async () => {
    const { refreshJwtToken } = await import('../services/agencyApi');
    const { refreshTenantToken } = await import('../utils/auth');

    vi.mocked(refreshJwtToken).mockRejectedValueOnce(
      new Error('Access to this tenant has expired'),
    );

    await expect(refreshTenantToken('tenant-123')).rejects.toThrow(
      'Access to this tenant has expired',
    );
  });
});

describe('AgencyStoreSelector', () => {
  it('exports the component', async () => {
    const mod = await import('../components/AgencyStoreSelector');
    expect(mod.AgencyStoreSelector).toBeDefined();
    expect(typeof mod.AgencyStoreSelector).toBe('function');
  });
});

describe('AgencyContext', () => {
  it('exports the provider and hooks', async () => {
    const mod = await import('../contexts/AgencyContext');
    expect(mod.AgencyProvider).toBeDefined();
    expect(mod.useAgency).toBeDefined();
    expect(mod.useActiveStore).toBeDefined();
    expect(mod.useIsAgencyUser).toBeDefined();
  });
});
