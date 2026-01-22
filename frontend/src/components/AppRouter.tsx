/**
 * App Router Component
 *
 * Custom router that works in both embedded and non-embedded contexts.
 * For embedded apps, App Bridge handles URL synchronization automatically.
 * We just need to match routes based on the current pathname.
 */

import { ReactNode, useEffect, useState } from 'react';
import { useAppBridge } from '@shopify/app-bridge-react';
import { isEmbedded } from '../lib/shopifyAppBridge';
import { ProtectedRoute } from './ProtectedRoute';

interface Route {
  path: string;
  element: ReactNode;
  requireEmbedded?: boolean;
}

interface AppRouterProps {
  routes: Route[];
  defaultPath?: string;
}

/**
 * AppRouter component that handles routing for both embedded and non-embedded contexts.
 *
 * When embedded:
 * - App Bridge automatically syncs the iframe URL with Shopify Admin
 * - We match routes based on window.location.pathname
 *
 * When not embedded:
 * - Uses standard browser history for admin routes
 *
 * @param routes - Array of route definitions
 * @param defaultPath - Default path to redirect to (default: '/')
 */
export function AppRouter({ routes, defaultPath = '/' }: AppRouterProps) {
  const app = useAppBridge();
  const embedded = isEmbedded();
  const [currentPath, setCurrentPath] = useState(() => {
    // Get initial path from URL
    if (typeof window !== 'undefined') {
      const path = window.location.pathname;
      // If path is root and we have a default, use default
      if (path === '/' && defaultPath !== '/') {
        return defaultPath;
      }
      return path;
    }
    return defaultPath;
  });

  // Sync with URL changes (both embedded and non-embedded)
  useEffect(() => {
    const handleLocationChange = () => {
      const path = window.location.pathname;
      setCurrentPath(path);
    };

    // Listen for popstate events (back/forward navigation)
    window.addEventListener('popstate', handleLocationChange);

    // Check if we need to redirect to default
    const matchedRoute = routes.find(route => route.path === currentPath);
    if (!matchedRoute && currentPath === '/' && defaultPath !== '/') {
      // Redirect to default path
      if (embedded && app) {
        // In embedded context, App Bridge will handle URL updates
        // We can use history API which App Bridge will sync
        window.history.replaceState(null, '', defaultPath);
      } else {
        window.history.replaceState(null, '', defaultPath);
      }
      setCurrentPath(defaultPath);
    }

    return () => {
      window.removeEventListener('popstate', handleLocationChange);
    };
  }, [currentPath, routes, defaultPath, embedded, app]);

  // Find the matching route
  const matchedRoute = routes.find(route => route.path === currentPath);

  // If no match and we're at root, try default path
  const routeToRender = matchedRoute || 
                       routes.find(route => route.path === defaultPath);

  if (!routeToRender) {
    return (
      <div style={{ padding: '20px' }}>
        <p>Route not found: {currentPath}</p>
      </div>
    );
  }

  // Render the matched route with protection
  return (
    <ProtectedRoute
      requireEmbedded={routeToRender.requireEmbedded}
    >
      {routeToRender.element}
    </ProtectedRoute>
  );
}

/**
 * Hook for programmatic navigation.
 * Works in both embedded and non-embedded contexts.
 *
 * @returns Navigation function that accepts a path string
 */
export function useAppNavigation(): (path: string) => void {
  const app = useAppBridge();
  const embedded = isEmbedded();

  return (path: string) => {
    // In both embedded and non-embedded contexts, use history API
    // App Bridge will sync the URL automatically in embedded context
    window.history.pushState(null, '', path);
    window.dispatchEvent(new PopStateEvent('popstate'));
  };
}
