/**
 * Tests for Error Boundary Components
 *
 * Tests cover:
 * - ErrorBoundary catching render errors
 * - Fallback UI rendering
 * - Reset functionality
 * - onError callback
 * - Different fallback variants (Root, Page, Component)
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import { BrowserRouter } from 'react-router-dom';

import { ErrorBoundary } from '../components/ErrorBoundary';
import {
  RootErrorFallback,
  PageErrorFallback,
  ComponentErrorFallback,
} from '../components/ErrorFallback';

// Mock translations
const mockTranslations = {
  Polaris: {
    Common: { ok: 'OK', cancel: 'Cancel' },
  },
};

// Helper to render with providers
const renderWithProviders = (ui: React.ReactElement) => {
  return render(
    <AppProvider i18n={mockTranslations as any}>
      <BrowserRouter>{ui}</BrowserRouter>
    </AppProvider>
  );
};

// Component that throws an error
function ThrowingComponent({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error('Test error from ThrowingComponent');
  }
  return <div data-testid="normal-content">Normal content</div>;
}

// Component that throws on click
function ThrowOnClickComponent() {
  const [shouldThrow, setShouldThrow] = React.useState(false);

  if (shouldThrow) {
    throw new Error('Error triggered by click');
  }

  return (
    <button onClick={() => setShouldThrow(true)} data-testid="throw-button">
      Click to throw
    </button>
  );
}

describe('ErrorBoundary', () => {
  // Suppress console.error for these tests since we're testing error handling
  let consoleSpy: any;

  beforeEach(() => {
    consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    consoleSpy.mockRestore();
  });

  describe('normal rendering', () => {
    it('renders children when no error occurs', () => {
      render(
        <ErrorBoundary>
          <div data-testid="child">Child content</div>
        </ErrorBoundary>
      );

      expect(screen.getByTestId('child')).toBeInTheDocument();
      expect(screen.getByText('Child content')).toBeInTheDocument();
    });

    it('does not show fallback when no error occurs', () => {
      render(
        <ErrorBoundary fallback={<div>Error fallback</div>}>
          <div>Normal content</div>
        </ErrorBoundary>
      );

      expect(screen.getByText('Normal content')).toBeInTheDocument();
      expect(screen.queryByText('Error fallback')).not.toBeInTheDocument();
    });
  });

  describe('error catching', () => {
    it('catches render errors and displays default fallback', () => {
      render(
        <ErrorBoundary>
          <ThrowingComponent shouldThrow={true} />
        </ErrorBoundary>
      );

      expect(screen.queryByTestId('normal-content')).not.toBeInTheDocument();
      expect(screen.getByText('Something went wrong')).toBeInTheDocument();
      expect(screen.getByText('Try again')).toBeInTheDocument();
    });

    it('displays custom static fallback when provided', () => {
      render(
        <ErrorBoundary fallback={<div>Custom error message</div>}>
          <ThrowingComponent shouldThrow={true} />
        </ErrorBoundary>
      );

      expect(screen.getByText('Custom error message')).toBeInTheDocument();
    });

    it('displays fallbackRender with error info', () => {
      render(
        <ErrorBoundary
          fallbackRender={({ error }) => (
            <div data-testid="custom-fallback">Error: {error.message}</div>
          )}
        >
          <ThrowingComponent shouldThrow={true} />
        </ErrorBoundary>
      );

      expect(screen.getByTestId('custom-fallback')).toBeInTheDocument();
      expect(
        screen.getByText('Error: Test error from ThrowingComponent')
      ).toBeInTheDocument();
    });

    it('calls onError callback when error is caught', () => {
      const onError = vi.fn();

      render(
        <ErrorBoundary onError={onError}>
          <ThrowingComponent shouldThrow={true} />
        </ErrorBoundary>
      );

      expect(onError).toHaveBeenCalledTimes(1);
      expect(onError).toHaveBeenCalledWith(
        expect.any(Error),
        expect.objectContaining({
          componentStack: expect.any(String),
        })
      );
    });
  });

  describe('reset functionality', () => {
    it('resets error state when resetErrorBoundary is called', async () => {
      const user = userEvent.setup();

      const TestComponent = () => {
        const [shouldThrow, setShouldThrow] = React.useState(true);

        return (
          <ErrorBoundary
            fallbackRender={({ resetErrorBoundary }) => (
              <div>
                <span>Error occurred</span>
                <button
                  onClick={() => {
                    setShouldThrow(false);
                    resetErrorBoundary();
                  }}
                >
                  Reset
                </button>
              </div>
            )}
          >
            <ThrowingComponent shouldThrow={shouldThrow} />
          </ErrorBoundary>
        );
      };

      render(<TestComponent />);

      // Initially shows error
      expect(screen.getByText('Error occurred')).toBeInTheDocument();

      // Click reset
      await user.click(screen.getByText('Reset'));

      // Now shows normal content
      expect(screen.getByTestId('normal-content')).toBeInTheDocument();
    });

    it('calls onReset callback when boundary is reset', async () => {
      const user = userEvent.setup();
      const onReset = vi.fn();

      const TestComponent = () => {
        const [shouldThrow, setShouldThrow] = React.useState(true);

        return (
          <ErrorBoundary
            onReset={onReset}
            fallbackRender={({ resetErrorBoundary }) => (
              <button
                onClick={() => {
                  setShouldThrow(false);
                  resetErrorBoundary();
                }}
              >
                Reset
              </button>
            )}
          >
            <ThrowingComponent shouldThrow={shouldThrow} />
          </ErrorBoundary>
        );
      };

      render(<TestComponent />);

      await user.click(screen.getByText('Reset'));

      expect(onReset).toHaveBeenCalledTimes(1);
    });
  });

  describe('error triggered by interaction', () => {
    it('catches errors thrown during event handlers that cause re-renders', async () => {
      const user = userEvent.setup();

      render(
        <ErrorBoundary>
          <ThrowOnClickComponent />
        </ErrorBoundary>
      );

      expect(screen.getByTestId('throw-button')).toBeInTheDocument();

      await user.click(screen.getByTestId('throw-button'));

      expect(screen.queryByTestId('throw-button')).not.toBeInTheDocument();
      expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    });
  });
});

describe('RootErrorFallback', () => {
  const mockError = new Error('Test root error');
  const mockResetFn = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders error message and retry button', () => {
    renderWithProviders(
      <RootErrorFallback error={mockError} resetErrorBoundary={mockResetFn} />
    );

    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(screen.getByText('Try again')).toBeInTheDocument();
    expect(screen.getByText('Contact support')).toBeInTheDocument();
  });

  it('calls resetErrorBoundary when retry button is clicked', async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <RootErrorFallback error={mockError} resetErrorBoundary={mockResetFn} />
    );

    await user.click(screen.getByText('Try again'));

    expect(mockResetFn).toHaveBeenCalledTimes(1);
  });

  it('shows error details when expanded', async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <RootErrorFallback error={mockError} resetErrorBoundary={mockResetFn} />
    );

    // Details toggle button should exist
    expect(screen.getByText('Show error details')).toBeInTheDocument();

    // Click to show details
    await user.click(screen.getByText('Show error details'));

    // Details should now be visible and button text should change
    expect(screen.getByText(/Error: Test root error/)).toBeInTheDocument();
    expect(screen.getByText('Hide error details')).toBeInTheDocument();
  });
});

describe('PageErrorFallback', () => {
  const mockError = new Error('Test page error');
  const mockResetFn = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders with page name in error message', () => {
    renderWithProviders(
      <PageErrorFallback
        error={mockError}
        resetErrorBoundary={mockResetFn}
        pageName="Analytics"
      />
    );

    expect(
      screen.getByText('Analytics encountered an error')
    ).toBeInTheDocument();
  });

  it('renders retry action in banner', () => {
    renderWithProviders(
      <PageErrorFallback
        error={mockError}
        resetErrorBoundary={mockResetFn}
        pageName="Test Page"
      />
    );

    expect(screen.getByText('Try again')).toBeInTheDocument();
    expect(screen.getByText('Contact support')).toBeInTheDocument();
  });

  it('uses default page name when not provided', () => {
    renderWithProviders(
      <PageErrorFallback error={mockError} resetErrorBoundary={mockResetFn} />
    );

    expect(
      screen.getByText('This page encountered an error')
    ).toBeInTheDocument();
  });
});

describe('ComponentErrorFallback', () => {
  const mockError = new Error('Test component error');
  const mockResetFn = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders with component name', () => {
    renderWithProviders(
      <ComponentErrorFallback
        error={mockError}
        resetErrorBoundary={mockResetFn}
        componentName="Dashboard Widget"
      />
    );

    expect(
      screen.getByText('Dashboard Widget failed to load')
    ).toBeInTheDocument();
  });

  it('renders retry button', () => {
    renderWithProviders(
      <ComponentErrorFallback
        error={mockError}
        resetErrorBoundary={mockResetFn}
      />
    );

    expect(screen.getByText('Try again')).toBeInTheDocument();
  });

  it('calls resetErrorBoundary when retry is clicked', async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <ComponentErrorFallback
        error={mockError}
        resetErrorBoundary={mockResetFn}
      />
    );

    await user.click(screen.getByText('Try again'));

    expect(mockResetFn).toHaveBeenCalledTimes(1);
  });

  it('renders support link', () => {
    renderWithProviders(
      <ComponentErrorFallback
        error={mockError}
        resetErrorBoundary={mockResetFn}
      />
    );

    expect(screen.getByText('contact support')).toBeInTheDocument();
  });

  it('uses default component name when not provided', () => {
    renderWithProviders(
      <ComponentErrorFallback
        error={mockError}
        resetErrorBoundary={mockResetFn}
      />
    );

    expect(
      screen.getByText('This component failed to load')
    ).toBeInTheDocument();
  });
});
