/**
 * ErrorBoundary Component
 *
 * React error boundary that catches JavaScript errors in child components
 * and displays a fallback UI instead of crashing the entire app.
 *
 * Usage:
 * - Root level: Wrap entire app to catch unhandled errors
 * - Page level: Wrap individual pages for isolated failures
 * - Component level: Wrap high-risk components (e.g., embedded iframes)
 */

import { Component, ErrorInfo, ReactNode } from 'react';

export interface ErrorBoundaryProps {
  /** Child components to wrap */
  children: ReactNode;
  /** Custom fallback UI to render on error */
  fallback?: ReactNode;
  /** Render prop for fallback with error info and reset function */
  fallbackRender?: (props: {
    error: Error;
    errorInfo: ErrorInfo | null;
    resetErrorBoundary: () => void;
  }) => ReactNode;
  /** Callback when an error is caught */
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
  /** Callback when boundary is reset */
  onReset?: () => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    // Update state so next render shows fallback UI
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Store error info for rendering
    this.setState({ errorInfo });

    // Call optional error callback
    this.props.onError?.(error, errorInfo);

    // Log to console in development
    if (import.meta.env.DEV) {
      console.error('ErrorBoundary caught an error:', error);
      console.error('Component stack:', errorInfo.componentStack);
    }
  }

  resetErrorBoundary = (): void => {
    this.props.onReset?.();
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  render(): ReactNode {
    const { hasError, error, errorInfo } = this.state;
    const { children, fallback, fallbackRender } = this.props;

    if (hasError && error) {
      // Use fallbackRender if provided (allows access to error info and reset)
      if (fallbackRender) {
        return fallbackRender({
          error,
          errorInfo,
          resetErrorBoundary: this.resetErrorBoundary,
        });
      }

      // Use static fallback if provided
      if (fallback) {
        return fallback;
      }

      // Default fallback (minimal)
      return (
        <div style={{ padding: '20px', textAlign: 'center' }}>
          <h2>Something went wrong</h2>
          <button onClick={this.resetErrorBoundary}>Try again</button>
        </div>
      );
    }

    return children;
  }
}

export default ErrorBoundary;
