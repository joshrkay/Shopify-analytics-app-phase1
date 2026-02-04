/**
 * Main App Component
 *
 * Sets up Clerk authentication, Shopify Polaris provider, data health context, and routing.
 * Includes root-level error boundary for graceful error handling.
 *
 * Authentication: Clerk (https://clerk.com)
 * - ClerkProvider wraps the entire app
 * - SignedIn/SignedOut components control access
 * - useAuth() hook provides token for API calls
 */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ClerkProvider, SignedIn, SignedOut, RedirectToSignIn } from '@clerk/clerk-react';
import { AppProvider } from '@shopify/polaris';
import enTranslations from '@shopify/polaris/locales/en.json';
import '@shopify/polaris/build/esm/styles.css';

import { ErrorBoundary } from './components/ErrorBoundary';
import { RootErrorFallback } from './components/ErrorFallback';
import { DataHealthProvider } from './contexts/DataHealthContext';
import { AppHeader } from './components/layout/AppHeader';
import { useClerkToken } from './hooks/useClerkToken';
import AdminPlans from './pages/AdminPlans';
import Analytics from './pages/Analytics';
import Paywall from './pages/Paywall';
import InsightsFeed from './pages/InsightsFeed';
import ApprovalsInbox from './pages/ApprovalsInbox';
import WhatsNew from './pages/WhatsNew';

// Clerk publishable key from environment
const CLERK_PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

if (!CLERK_PUBLISHABLE_KEY) {
  console.warn('Missing VITE_CLERK_PUBLISHABLE_KEY environment variable. Authentication will not work.');
}

/**
 * Authenticated app content.
 * Sets up Clerk token integration with API utilities.
 */
function AuthenticatedApp() {
  // Set up Clerk token provider for API calls
  useClerkToken();

  return (
    <>
      <AppHeader />
      <Routes>
        <Route path="/admin/plans" element={<AdminPlans />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/paywall" element={<Paywall />} />
        <Route path="/insights" element={<InsightsFeed />} />
        <Route path="/approvals" element={<ApprovalsInbox />} />
        <Route path="/whats-new" element={<WhatsNew />} />
        <Route path="/" element={<Navigate to="/analytics" replace />} />
      </Routes>
    </>
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
        // Log error to console (could be extended to send to error tracking service)
        console.error('Root error boundary caught error:', error);
        console.error('Component stack:', errorInfo.componentStack);
      }}
    >
      <ClerkProvider publishableKey={CLERK_PUBLISHABLE_KEY || ''}>
        <AppProvider i18n={enTranslations}>
          <DataHealthProvider>
            <BrowserRouter>
              {/* Show app content only when signed in */}
              <SignedIn>
                <AuthenticatedApp />
              </SignedIn>
              {/* Redirect to sign-in when not authenticated */}
              <SignedOut>
                <RedirectToSignIn />
              </SignedOut>
            </BrowserRouter>
          </DataHealthProvider>
        </AppProvider>
      </ClerkProvider>
    </ErrorBoundary>
  );
}

export default App;
