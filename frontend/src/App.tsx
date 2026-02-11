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
import { AppProvider } from '@shopify/polaris';
import { SkeletonPage } from '@shopify/polaris';
import enTranslations from '@shopify/polaris/locales/en.json';
import '@shopify/polaris/build/esm/styles.css';

import { ErrorBoundary } from './components/ErrorBoundary';
import { RootErrorFallback } from './components/ErrorFallback';
import { DataHealthProvider } from './contexts/DataHealthContext';
import { AgencyProvider } from './contexts/AgencyContext';
import { AppHeader } from './components/layout/AppHeader';
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
import { RootLayout, SidebarProvider } from './components/layout';
import DataSources from './pages/DataSources';
import Settings from './pages/Settings';
import { DashboardHome } from './pages/DashboardHome';

// =============================================================================
// FeatureGateRoute — redirects to paywall if feature not entitled
// =============================================================================

interface FeatureGateRouteProps {
  feature: string;
  entitlements: EntitlementsResponse | null;
  children: React.ReactNode;
}

function FeatureGateRoute({ feature, entitlements, children }: FeatureGateRouteProps) {
  const location = useLocation();

  // Still loading entitlements
  if (entitlements === null) return <SkeletonPage />;

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
  const { isTokenReady } = useClerkToken();  // was: useClerkToken()
  const { entitlements } = useEntitlements();

  if (!isTokenReady) {
    return <SkeletonPage />;  // NEW: blocks all API calls until token is cached
  }

  return (
    <AgencyProvider>
      <DataHealthProvider>
        <SidebarProvider>
        <AppHeader />
        <RootLayout>
          <Routes>
            <Route path="/admin/plans" element={<AdminPlans />} />
            <Route path="/admin/diagnostics" element={<RootCausePanel />} />
            <Route path="/home" element={<DashboardHome />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/paywall" element={<Paywall />} />
            <Route path="/insights" element={<InsightsFeed />} />
            <Route path="/approvals" element={<ApprovalsInbox />} />
            <Route path="/whats-new" element={<WhatsNew />} />
            <Route path="/data-sources" element={<DataSources />} />
            <Route path="/settings" element={<Settings />} />

            {/* Custom Dashboards — gated routes */}
            <Route
              path="/dashboards"
              element={
                <FeatureGateRoute feature="custom_reports" entitlements={entitlements}>
                  <DashboardList />
                </FeatureGateRoute>
              }
            />
            <Route
              path="/dashboards/:dashboardId/edit"
              element={
                <FeatureGateRoute feature="custom_reports" entitlements={entitlements}>
                  <DashboardBuilder />
                </FeatureGateRoute>
              }
            />
            {/* View route is NOT gated — shared dashboards viewable on any plan */}
            <Route path="/dashboards/:dashboardId" element={<DashboardView />} />

            <Route path="/" element={<Navigate to="/home" replace />} />
          </Routes>
        </RootLayout>
        </SidebarProvider>
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
