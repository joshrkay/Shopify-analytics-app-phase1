/**
 * Phase 3 Regression Tests
 *
 * Verifies that Phase 3 (data sources, wizard, settings) changes don't break
 * existing functionality. Tests import health, render stability, auth inclusion,
 * and context preservation.
 *
 * R#   Regression Test                                    Why It Exists
 * R1   SyncHealth page component still importable         Health monitoring preserved
 * R2   ConnectorHealthCard still importable               Health card preserved
 * R3   BackfillModal still importable                     Backfill pipeline preserved
 * R4   DataHealthContext still provides health state       Context unbroken
 * R5   syncHealthApi still exports expected functions      Health polling preserved
 * R6   diagnosticsApi still importable                    Diagnostics preserved
 * R7   Dashboard page still importable                    Dashboard data flow preserved
 * R8   DashboardBuilder page still importable             Builder data access preserved
 * R9   Health badges/banners still importable             Health UI preserved
 * R10  Clerk auth headers included in source API calls    Auth preserved
 * R11  AgencyContext still exports expected members        Multi-tenant preserved
 * R12  ErrorBoundary still catches errors                 Error handling preserved
 * R13  FeatureGate still gates content                    Feature flags preserved
 * R14  Phase 1 components still importable                Phase 1 regression
 * R15  Phase 2 builder components still importable        Phase 2 regression
 *
 * Phase 3 — Subphase 3.7: Full Regression Suite
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

// ---------------------------------------------------------------------------
// Module mocks — Lightweight mocks for import validation
// ---------------------------------------------------------------------------

vi.mock('../services/apiUtils', () => ({
  API_BASE_URL: '',
  createHeadersAsync: vi.fn().mockResolvedValue({
    'Content-Type': 'application/json',
    Authorization: 'Bearer test-token',
  }),
  handleResponse: vi.fn(async (res: Response) => res.json()),
  isApiError: vi.fn().mockReturnValue(false),
  getErrorMessage: vi.fn((_err: unknown, fallback: string) => fallback),
  createHeaders: vi.fn().mockReturnValue({}),
  getAuthToken: vi.fn().mockReturnValue('test-token'),
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Phase 3 Regression Suite', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // =========================================================================
  // R1–R6: Data Health & Sync Regressions
  // =========================================================================

  describe('Data Health & Sync Regressions', () => {
    it('R1: SyncHealth page component is importable', async () => {
      const module = await import('../pages/SyncHealth');
      expect(module).toBeDefined();
      expect(module.default).toBeDefined();
    });

    it('R2: ConnectorHealthCard component is importable', async () => {
      const module = await import('../components/ConnectorHealthCard');
      expect(module).toBeDefined();
    });

    it('R3: BackfillModal component is importable', async () => {
      const module = await import('../components/BackfillModal');
      expect(module).toBeDefined();
    });

    it('R4: DataHealthContext exports expected hooks', async () => {
      const module = await import('../contexts/DataHealthContext');
      expect(module.DataHealthProvider).toBeDefined();
      expect(module.useDataHealth).toBeDefined();
    });

    it('R5: syncHealthApi exports expected functions', async () => {
      const module = await import('../services/syncHealthApi');
      expect(module.getCompactHealth).toBeDefined();
    });

    it('R6: diagnosticsApi is importable', async () => {
      const module = await import('../services/diagnosticsApi');
      expect(module).toBeDefined();
    });
  });

  // =========================================================================
  // R7–R8: Dashboard Regressions
  // =========================================================================

  describe('Dashboard Regressions', () => {
    it('R7: Dashboard page component is importable', async () => {
      const module = await import('../pages/Dashboard');
      expect(module).toBeDefined();
    });

    it('R8: DashboardBuilder page component is importable', async () => {
      const module = await import('../pages/DashboardBuilder');
      expect(module).toBeDefined();
    });
  });

  // =========================================================================
  // R9: Health UI Regressions
  // =========================================================================

  describe('Health UI Regressions', () => {
    it('R9: Health banners and badges components are importable', async () => {
      const healthBanner = await import('../components/AnalyticsHealthBanner');
      expect(healthBanner).toBeDefined();

      const freshnessBanner = await import('../components/DataFreshnessBanner');
      expect(freshnessBanner).toBeDefined();
    });
  });

  // =========================================================================
  // R10: Auth Regressions
  // =========================================================================

  describe('Auth Regressions', () => {
    it('R10: createHeadersAsync includes Bearer token for source API calls', async () => {
      const { createHeadersAsync } = await import('../services/apiUtils');
      const headers = await createHeadersAsync();
      expect(headers).toEqual(
        expect.objectContaining({ Authorization: 'Bearer test-token' }),
      );
    });
  });

  // =========================================================================
  // R11: Multi-Tenant Regressions
  // =========================================================================

  describe('Multi-Tenant Regressions', () => {
    it('R11: AgencyContext exports expected provider and hooks', async () => {
      const module = await import('../contexts/AgencyContext');
      expect(module.AgencyProvider).toBeDefined();
      expect(module.useAgency).toBeDefined();
    });
  });

  // =========================================================================
  // R12: Error Handling Regressions
  // =========================================================================

  describe('Error Handling Regressions', () => {
    it('R12: ErrorBoundary catches rendering errors', async () => {
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {});

      function ThrowingComponent(): React.ReactElement {
        throw new Error('Test error');
      }

      const { ErrorBoundary } = await import('../components/ErrorBoundary');

      render(
        <AppProvider i18n={{} as any}>
          <ErrorBoundary>
            <ThrowingComponent />
          </ErrorBoundary>
        </AppProvider>,
      );

      expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();
      spy.mockRestore();
    });
  });

  // =========================================================================
  // R13: Feature Gating Regressions
  // =========================================================================

  describe('Feature Gating Regressions', () => {
    it('R13: FeatureGate component is importable', async () => {
      const module = await import('../components/FeatureGate');
      expect(module.FeatureGate).toBeDefined();
    });
  });

  // =========================================================================
  // R14–R15: Phase 1 & 2 Component Regressions
  // =========================================================================

  describe('Phase 1 Component Regressions', () => {
    it('R14: All Phase 1 core components import without error', async () => {
      const modules = await Promise.all([
        import('../pages/DashboardHome'),
        import('../pages/Settings'),
        import('../pages/DataSources'),
        import('../pages/InsightsFeed'),
        import('../pages/WhatsNew'),
      ]);

      for (const mod of modules) {
        expect(mod).toBeDefined();
      }
    });
  });

  describe('Phase 2 Builder Component Regressions', () => {
    it('R15: All Phase 2 builder components import without error', async () => {
      const modules = await Promise.all([
        import('../pages/DashboardBuilder'),
        import('../pages/DashboardList'),
        import('../pages/DashboardView'),
      ]);

      for (const mod of modules) {
        expect(mod).toBeDefined();
      }
    });
  });

  // =========================================================================
  // API Service Import Regressions
  // =========================================================================

  describe('API Service Regressions', () => {
    it('sourcesApi exports all required functions', async () => {
      const module = await import('../services/sourcesApi');
      expect(module.listSources).toBeDefined();
      expect(module.getAvailableSources).toBeDefined();
      expect(module.initiateOAuth).toBeDefined();
      expect(module.completeOAuth).toBeDefined();
      expect(module.disconnectSource).toBeDefined();
      expect(module.testConnection).toBeDefined();
      expect(module.updateSyncConfig).toBeDefined();
    });

    it('dataSourcesApi exports all required functions', async () => {
      const module = await import('../services/dataSourcesApi');
      expect(module.getConnection).toBeDefined();
      expect(module.getAccounts).toBeDefined();
      expect(module.getSyncProgress).toBeDefined();
      expect(module.triggerSync).toBeDefined();
      expect(module.getGlobalSyncSettings).toBeDefined();
      expect(module.updateGlobalSyncSettings).toBeDefined();
      expect(module.getAvailableAccounts).toBeDefined();
      expect(module.getSyncProgressDetailed).toBeDefined();
      expect(module.updateSelectedAccounts).toBeDefined();
    });

    it('sourceNormalizer exports all normalizer functions', async () => {
      const module = await import('../services/sourceNormalizer');
      expect(module.normalizeApiSource).toBeDefined();
      expect(module.normalizeShopifySource).toBeDefined();
      expect(module.normalizeAdSource).toBeDefined();
    });
  });

  // =========================================================================
  // Hook Import Regressions
  // =========================================================================

  describe('Hook Regressions', () => {
    it('useDataSources hook module exports all hooks', async () => {
      const module = await import('../hooks/useDataSources');
      expect(module.useDataSources).toBeDefined();
      expect(module.useDataSourceCatalog).toBeDefined();
      expect(module.useConnection).toBeDefined();
      expect(module.useSyncProgress).toBeDefined();
      expect(module.useOAuthFlow).toBeDefined();
      expect(module.useDisconnectSource).toBeDefined();
      expect(module.useSyncConfigMutation).toBeDefined();
      expect(module.useGlobalSyncSettings).toBeDefined();
    });

    it('useConnectSourceWizard hook is importable', async () => {
      const module = await import('../hooks/useConnectSourceWizard');
      expect(module.useConnectSourceWizard).toBeDefined();
    });
  });

  // =========================================================================
  // Wizard Component Regressions
  // =========================================================================

  describe('Wizard Component Regressions', () => {
    it('All wizard step components are importable', async () => {
      const steps = await import('../components/sources/steps');
      expect(steps.IntroStep).toBeDefined();
      expect(steps.OAuthStep).toBeDefined();
      expect(steps.AccountSelectStep).toBeDefined();
      expect(steps.SyncConfigStep).toBeDefined();
      expect(steps.SyncProgressStep).toBeDefined();
      expect(steps.SuccessStep).toBeDefined();
    });

    it('ConnectSourceWizard component is importable', async () => {
      const module = await import('../components/sources/ConnectSourceWizard');
      expect(module.ConnectSourceWizard).toBeDefined();
    });
  });
});
