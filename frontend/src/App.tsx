/**
 * Main App Component
 *
 * Sets up Shopify App Bridge, Polaris provider, and routing.
 * Uses App Bridge navigation for embedded apps.
 */

import { useEffect } from 'react';
import { ShopifyProvider } from './providers/ShopifyProvider';
import { ShopifyApiProvider } from './providers/ShopifyApiProvider';
import { AppRouter } from './components/AppRouter';
import AdminPlans from './pages/AdminPlans';

function App() {
  // Handle initial route redirect
  useEffect(() => {
    const path = window.location.pathname;
    if (path === '/') {
      // Redirect to default route
      window.history.replaceState(null, '', '/admin/plans');
    }
  }, []);

  const routes = [
    {
      path: '/admin/plans',
      element: <AdminPlans />,
      requireEmbedded: false, // Allow access in both embedded and non-embedded contexts
    },
  ];

  return (
    <ShopifyProvider>
      <ShopifyApiProvider>
        <AppRouter routes={routes} defaultPath="/admin/plans" />
      </ShopifyApiProvider>
    </ShopifyProvider>
  );
}

export default App;
