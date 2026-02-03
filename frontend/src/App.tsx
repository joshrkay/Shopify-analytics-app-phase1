/**
 * Main App Component
 *
 * Sets up Shopify Polaris provider, data health context, and routing.
 * Includes root-level error boundary for graceful error handling.
 */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppProvider } from '@shopify/polaris';
import enTranslations from '@shopify/polaris/locales/en.json';
import '@shopify/polaris/build/esm/styles.css';

import { ErrorBoundary } from './components/ErrorBoundary';
import { RootErrorFallback } from './components/ErrorFallback';
import { DataHealthProvider } from './contexts/DataHealthContext';
import { AppHeader } from './components/layout/AppHeader';
import AdminPlans from './pages/AdminPlans';
import Analytics from './pages/Analytics';
import Paywall from './pages/Paywall';
import InsightsFeed from './pages/InsightsFeed';
import ApprovalsInbox from './pages/ApprovalsInbox';
import WhatsNew from './pages/WhatsNew';

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
      <AppProvider i18n={enTranslations}>
        <DataHealthProvider>
          <BrowserRouter>
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
          </BrowserRouter>
        </DataHealthProvider>
      </AppProvider>
    </ErrorBoundary>
  );
}

export default App;
