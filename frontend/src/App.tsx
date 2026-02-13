/** Main App Component
 *
 * Sets up Shopify Polaris provider, data health context, and routing.
 * Includes root-level error boundary for graceful error handling.
 *
 * Authentication: Clerk (https://clerk.com)
 * - ClerkProvider is set up in main.tsx
 * - SignedIn/SignedOut components control access
 * - useClerkToken hook syncs tokens for API calls
 *
 * Feature gating:
 * - FeatureGateRoute wraps routes that require entitlements
 * - Redirect loop prevention: checks pathname !== '/paywall'
 * - Shared dashboard view (/dashboards/:id) is NOT gated — viewable on any plan
 */

import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { SignedIn, SignedOut, RedirectToSignIn } from '@clerk/clerk-react';
import { AppProvider, SkeletonPage, Page, Banner } from '@shopify/polaris';
import enTranslations from '@shopify/polaris/locales/en.json';
import '@shopify/polaris/build/esm/styles.css';

import { ErrorBoundary } from './components/ErrorBoundary';
import { RootErrorFallback } from './components/ErrorFallback';
import { DataHealthProvider } from './contexts/DataHealthContext';
import { AgencyProvider } from './contexts/AgencyContext';
import { Root } from './components/layout/Root';
import { useAutoOrganization } from './hooks/useAutoOrganization';
import { useClerkToken } from './hooks/useClerkToken';
import { useEntitlements } from './hooks/useEntitlements';
import { isFeatureEntitled } from './services/entitlementsApi';
import type { EntitlementsResponse } from './services/entitlementsApi';
import AdminPlans from './pages/AdminPlans';
import RootCausePanel from './pages/admin/RootCausePanel';
import Analytics from './pages/Analytics';
import Paywall from './pages/Paywall';
import InsightsFeed from './pages/InsightsFeed';
import ApprovalsInbox from './pages/ApprovalsInbox';
import WhatsNew from './pages/WhatsNew';
import { DashboardList } from './pages/DashboardList';
import { DashboardView } from './pages/DashboardView';
import { DashboardBuilder } from './pages/DashboardBuilder';
import { WizardFlow } from './components/dashboards/wizard/WizardFlow';
import { DashboardBuilderProvider } from './contexts/DashboardBuilderContext';
import DataSources from './pages/DataSources';
import OAuthCallback from './pages/OAuthCallback';
import Settings from './pages/Settings';
import { DashboardHome } from './pages/DashboardHome';
import { Dashboard } from './pages/Dashboard';

// =============================================================================
// FeatureGateRoute — redirects to paywall if feature not entitled
// =============================================================================

interface FeatureGateRouteProps {
  feature: string;
  entitlements: EntitlementsResponse | null;
  entitlementsLoading: boolean;
  entitlementsError: string | null;
  onRetry: () => Promise<void>;
  children: React.ReactNode;
}

function FeatureGateRoute({
  feature,
  entitlements,
  entitlementsLoading,
  entitlementsError,
  onRetry,
  children,
}: FeatureGateRouteProps) {
  const location = useLocation();

  // Still loading entitlements
  if (entitlementsLoading && entitlements === null) return <SkeletonPage />;

  // Failed to load entitlements — show error with retry
  if (entitlementsError && entitlements === null) {
    return (
      <Page title="Unable to load">
        <Banner
          tone="critical"
          title="Failed to check feature access"
          action={{ content: 'Retry', onAction: onRetry }}
        >
          {entitlementsError}
        </Banner>
      </Page>
    );
  }

  if (!isFeatureEntitled(entitlements, feature)) {
    // Edge case: prevent redirect loop if already on /paywall
    if (location.pathname === '/paywall') return <Paywall />;
    return <Navigate to={`/paywall?feature=${feature}`} replace />;
  }

  return <>{children}</>;
}

// =============================================================================
// Authenticated app content
// =============================================================================

/**
 * AuthenticatedApp — waits for Clerk organization to be active before
 * mounting the token provider and routes.  This guarantees that
 * getToken() returns a JWT that contains org_id, which the backend
 * tenant_context middleware requires.
 */
function AuthenticatedApp() {
  const { isLoading: isOrgLoading, hasOrg } = useAutoOrganization();

  if (isOrgLoading) {
    return <SkeletonPage />;
  }

  if (!hasOrg) {
    return (
      <div style={{ padding: '2rem', textAlign: 'center' }}>
        <h2>Organization Required</h2>
        <p>
          Your account is not part of an organization yet.
          Please contact your administrator or create an organization
          in the Clerk dashboard.
        </p>
      </div>
    );
  }

  // Org is active — safe to mount the token provider
  return <AppWithOrg />;
}

/** Inner shell: only mounts once the Clerk org is active so the token has org_id. */
function AppWithOrg() {
  const { isTokenReady } = useClerkToken();
  const { entitlements, loading: entitlementsLoading, error: entitlementsError, refetch: refetchEntitlements } = useEntitlements(isTokenReady);

  if (!isTokenReady) {
    return <SkeletonPage />;
  }

  return (
    <AgencyProvider>
      <DataHealthProvider>
        <Routes>
          {/* New Tailwind-based layout with sidebar + header */}
          <Route element={<Root />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/builder" element={
              <FeatureGateRoute feature="custom_reports" entitlements={entitlements} entitlementsLoading={entitlementsLoading} entitlementsError={entitlementsError} onRetry={refetchEntitlements}>
                <DashboardBuilderProvider>
                  <WizardFlow />
                </DashboardBuilderProvider>
              </FeatureGateRoute>
            } />
            <Route path="/sources" element={<DataSources />} />
            <Route path="/oauth/callback" element={<OAuthCallback />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/home" element={<DashboardHome />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/paywall" element={<Paywall />} />
            <Route path="/insights" element={<InsightsFeed />} />
            <Route path="/approvals" element={<ApprovalsInbox />} />
            <Route path="/whats-new" element={<WhatsNew />} />
            <Route path="/data-sources" element={<DataSources />} />
            <Route path="/admin/plans" element={<AdminPlans />} />
            <Route path="/admin/diagnostics" element={<RootCausePanel />} />

            {/* Custom Dashboards — gated routes */}
            <Route
              path="/dashboards"
              element={
                <FeatureGateRoute feature="custom_reports" entitlements={entitlements} entitlementsLoading={entitlementsLoading} entitlementsError={entitlementsError} onRetry={refetchEntitlements}>
                  <DashboardList />
                </FeatureGateRoute>
              }
            />
            <Route
              path="/dashboards/wizard"
              element={
                <FeatureGateRoute feature="custom_reports" entitlements={entitlements} entitlementsLoading={entitlementsLoading} entitlementsError={entitlementsError} onRetry={refetchEntitlements}>
                  <DashboardBuilderProvider>
                    <WizardFlow />
                  </DashboardBuilderProvider>
                </FeatureGateRoute>
              }
            />
            <Route
              path="/dashboards/:dashboardId/edit"
              element={
                <FeatureGateRoute feature="custom_reports" entitlements={entitlements} entitlementsLoading={entitlementsLoading} entitlementsError={entitlementsError} onRetry={refetchEntitlements}>
                  <DashboardBuilder />
                </FeatureGateRoute>
              }
            />
            {/* View route is NOT gated — shared dashboards viewable on any plan */}
            <Route path="/dashboards/:dashboardId" element={<DashboardView />} />
          </Route>
        </Routes>
      </DataHealthProvider>
    </AgencyProvider>
  );
}

function App() {
  return (
    <ErrorBoundary
      fallbackRender={({ error, errorInfo, resetErrorBoundary }) => (
        <AppProvider i18n={enTranslations}>
          <RootErrorFallback
            error={error}
            errorInfo={errorInfo}
            resetErrorBoundary={resetErrorBoundary}
          />
        </AppProvider>
      )}
      onError={(error, errorInfo) => {
        console.error('Root error boundary caught error:', error);
        console.error('Component stack:', errorInfo.componentStack);
      }}
    >
      <AppProvider i18n={enTranslations}>
        <BrowserRouter>
          <SignedIn>
            <AuthenticatedApp />
          </SignedIn>
          <SignedOut>
            <RedirectToSignIn />
          </SignedOut>
        </BrowserRouter>
      </AppProvider>
    </ErrorBoundary>
  );
}

export default App;
