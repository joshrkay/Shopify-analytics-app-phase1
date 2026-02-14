/**
 * Tests that all agencyApi.ts fetch calls use the /api/ prefix.
 *
 * Regression: these endpoints previously called /agency/* and /auth/*
 * without the /api/ prefix, causing them to bypass backend auth middleware
 * and return HTML (SPA fallback) instead of JSON.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';

// Mock apiUtils BEFORE importing agencyApi
vi.mock('../services/apiUtils', () => ({
  API_BASE_URL: '',
  createHeadersAsync: vi.fn(async () => ({ 'Content-Type': 'application/json' })),
  handleResponse: vi.fn(async () => ({ success: true, jwt_token: 'tok' })),
  setAuthToken: vi.fn(),
}));

// Mock fetch globally — returns a fresh Response each call
const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
  new Response(JSON.stringify({ success: true }), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  }),
);

// Import AFTER mocks are in place
import {
  fetchAssignedStores,
  switchActiveStore,
  fetchUserContext,
  refreshJwtToken,
  checkStoreAccess,
} from '../services/agencyApi';

afterEach(() => {
  fetchSpy.mockClear();
});

describe('agencyApi URL prefix', () => {
  it('fetchAssignedStores calls /api/agency/stores', async () => {
    await fetchAssignedStores();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const url = fetchSpy.mock.calls[0][0];
    expect(url).toBe('/api/agency/stores');
  });

  it('switchActiveStore calls /api/agency/stores/switch', async () => {
    await switchActiveStore('tenant-1');
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const url = fetchSpy.mock.calls[0][0];
    expect(url).toBe('/api/agency/stores/switch');
  });

  it('fetchUserContext calls /api/agency/me', async () => {
    await fetchUserContext();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const url = fetchSpy.mock.calls[0][0];
    expect(url).toBe('/api/agency/me');
  });

  it('refreshJwtToken calls /api/auth/refresh-jwt', async () => {
    await refreshJwtToken('tenant-1', ['tenant-1']);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const url = fetchSpy.mock.calls[0][0];
    expect(url).toBe('/api/auth/refresh-jwt');
  });

  it('checkStoreAccess calls /api/agency/stores/{id}/access', async () => {
    await checkStoreAccess('tenant-1');
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const url = fetchSpy.mock.calls[0][0];
    expect(url).toBe('/api/agency/stores/tenant-1/access');
  });

  it('no endpoint uses a URL without /api/ prefix', async () => {
    const endpoints = [
      () => fetchAssignedStores(),
      () => switchActiveStore('t'),
      () => fetchUserContext(),
      () => refreshJwtToken('t', ['t']),
      () => checkStoreAccess('t'),
    ];

    for (const call of endpoints) {
      fetchSpy.mockClear();
      await call();
      const url = String(fetchSpy.mock.calls[0][0]);
      expect(url).toMatch(/^\/api\//);
    }
  });
});
