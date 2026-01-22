/**
 * Tests for AppRouter component
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, renderHook } from '@testing-library/react';
import { AppRouter, useAppNavigation } from '../AppRouter';
import { useAppBridge } from '@shopify/app-bridge-react';
import { isEmbedded } from '../../lib/shopifyAppBridge';

// Mock dependencies
vi.mock('@shopify/app-bridge-react', () => ({
  useAppBridge: vi.fn(),
}));

vi.mock('../../lib/shopifyAppBridge', () => ({
  isEmbedded: vi.fn(),
}));

vi.mock('../ProtectedRoute', () => ({
  ProtectedRoute: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

describe('AppRouter', () => {
  const mockRoutes = [
    {
      path: '/admin/plans',
      element: <div>Plans Page</div>,
    },
    {
      path: '/admin/settings',
      element: <div>Settings Page</div>,
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    (useAppBridge as any).mockReturnValue(null);
    (isEmbedded as any).mockReturnValue(false);
    // Reset window.location.pathname
    Object.defineProperty(window, 'location', {
      value: {
        pathname: '/',
        search: '',
      },
      writable: true,
      configurable: true,
    });
  });

  it('renders default route when path is root', () => {
    window.location.pathname = '/';
    render(<AppRouter routes={mockRoutes} defaultPath="/admin/plans" />);

    expect(screen.getByText('Plans Page')).toBeInTheDocument();
  });

  it('renders matching route based on pathname', () => {
    window.location.pathname = '/admin/settings';
    render(<AppRouter routes={mockRoutes} defaultPath="/admin/plans" />);

    expect(screen.getByText('Settings Page')).toBeInTheDocument();
  });

  it('shows error message for unknown route', () => {
    window.location.pathname = '/unknown/route';
    render(<AppRouter routes={mockRoutes} defaultPath="/admin/plans" />);

    expect(screen.getByText(/Route not found/)).toBeInTheDocument();
  });

  it('redirects to default path when route does not match', () => {
    const replaceStateSpy = vi.spyOn(window.history, 'replaceState');
    window.location.pathname = '/unknown';
    render(<AppRouter routes={mockRoutes} defaultPath="/admin/plans" />);

    // Should redirect to default path
    expect(replaceStateSpy).toHaveBeenCalled();
  });
});

describe('useAppNavigation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window.history, 'pushState').mockImplementation(() => {});
    vi.spyOn(window, 'dispatchEvent').mockImplementation(() => true);
  });

  it('navigates using history API when not embedded', () => {
    (useAppBridge as any).mockReturnValue(null);
    (isEmbedded as any).mockReturnValue(false);

    const pushStateSpy = vi.spyOn(window.history, 'pushState');
    const { result } = renderHook(() => useAppNavigation());

    result.current('/admin/plans');

    expect(pushStateSpy).toHaveBeenCalledWith(null, '', '/admin/plans');
  });

  it('navigates using history API when embedded', () => {
    const mockApp = { id: 'test-app' };
    (useAppBridge as any).mockReturnValue(mockApp);
    (isEmbedded as any).mockReturnValue(true);

    const pushStateSpy = vi.spyOn(window.history, 'pushState');
    const { result } = renderHook(() => useAppNavigation());

    result.current('/admin/settings');

    expect(pushStateSpy).toHaveBeenCalledWith(null, '', '/admin/settings');
  });
});
