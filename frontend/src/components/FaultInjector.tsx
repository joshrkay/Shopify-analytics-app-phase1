/**
 * FaultInjector Component
 *
 * Development-only component for testing error boundaries.
 * Provides buttons to trigger errors at different levels.
 *
 * Usage: Import and render this component in development to test error boundaries.
 * The component only renders in development mode (NODE_ENV !== 'production').
 *
 * Manual Testing Instructions:
 * 1. Import FaultInjector in the component you want to test
 * 2. Render it within the error boundary you want to verify
 * 3. Click the "Trigger Error" button
 * 4. Verify the error boundary catches the error and shows fallback
 * 5. Click "Try again" to reset and verify recovery works
 */

import React, { useState } from 'react';
import { Card, BlockStack, Text, Button, Banner, InlineStack } from '@shopify/polaris';

interface FaultInjectorProps {
  /** Label to identify which boundary this will test */
  label?: string;
  /** Error message to throw */
  errorMessage?: string;
}

/**
 * Component that throws an error when triggered.
 * Only renders in development mode.
 */
export function FaultInjector({
  label = 'Error Boundary',
  errorMessage = 'Intentional error for testing error boundaries',
}: FaultInjectorProps) {
  const [shouldThrow, setShouldThrow] = useState(false);

  // Only render in development
  if (import.meta.env.PROD) {
    return null;
  }

  // Throw error during render if triggered
  if (shouldThrow) {
    throw new Error(errorMessage);
  }

  return (
    <Card>
      <BlockStack gap="300">
        <Text as="h3" variant="headingSm">
          Fault Injection: {label}
        </Text>
        <Text as="p" variant="bodySm" tone="subdued">
          Click the button below to trigger an error and test the error boundary.
        </Text>
        <InlineStack gap="200">
          <Button variant="primary" tone="critical" onClick={() => setShouldThrow(true)}>
            Trigger Error
          </Button>
        </InlineStack>
      </BlockStack>
    </Card>
  );
}

/**
 * DevErrorPanel - A floating panel for triggering errors at different levels.
 * Activated with keyboard shortcut Ctrl+Shift+E (development only).
 */
export function DevErrorPanel() {
  const [isVisible, setIsVisible] = useState(false);
  const [errorLevel, setErrorLevel] = useState<'none' | 'root' | 'page' | 'component'>('none');

  // Only render in development
  if (import.meta.env.PROD) {
    return null;
  }

  // Listen for keyboard shortcut
  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl+Shift+E toggles the panel
      if (e.ctrlKey && e.shiftKey && e.key === 'E') {
        e.preventDefault();
        setIsVisible((prev) => !prev);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Throw error at requested level
  if (errorLevel !== 'none') {
    throw new Error(`Dev error triggered at ${errorLevel} level`);
  }

  if (!isVisible) {
    return null;
  }

  return (
    <div
      style={{
        position: 'fixed',
        bottom: '20px',
        right: '20px',
        zIndex: 9999,
        maxWidth: '300px',
      }}
    >
      <Card>
        <BlockStack gap="300">
          <InlineStack align="space-between">
            <Text as="h3" variant="headingSm">
              Error Boundary Tester
            </Text>
            <Button variant="plain" onClick={() => setIsVisible(false)}>
              Close
            </Button>
          </InlineStack>

          <Banner tone="warning">
            <Text as="p" variant="bodySm">
              Development only. Press Ctrl+Shift+E to toggle.
            </Text>
          </Banner>

          <BlockStack gap="200">
            <Button
              variant="primary"
              tone="critical"
              onClick={() => setErrorLevel('root')}
              fullWidth
            >
              Trigger Root Error
            </Button>
            <Text as="p" variant="bodySm" tone="subdued">
              Tests the global error boundary in App.tsx
            </Text>
          </BlockStack>
        </BlockStack>
      </Card>
    </div>
  );
}

export default FaultInjector;
