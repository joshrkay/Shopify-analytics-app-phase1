/**
 * ErrorFallback Components
 *
 * Fallback UI components for error boundaries at different levels.
 * All include retry functionality and support link per acceptance criteria.
 *
 * Variants:
 * - RootErrorFallback: Full-page error for app-level crashes
 * - PageErrorFallback: Card-based error for page-level failures
 * - ComponentErrorFallback: Compact inline error for component failures
 */

import React, { ErrorInfo } from 'react';
import {
  Page,
  Layout,
  Card,
  BlockStack,
  InlineStack,
  Text,
  Button,
  Banner,
  Link,
  Collapsible,
  Box,
} from '@shopify/polaris';

const SUPPORT_EMAIL = 'support@example.com';
const SUPPORT_URL = `mailto:${SUPPORT_EMAIL}?subject=App%20Error%20Report`;

interface ErrorFallbackProps {
  error: Error;
  errorInfo?: ErrorInfo | null;
  resetErrorBoundary: () => void;
}

/**
 * Root-level error fallback.
 * Full-page error UI for when the entire app crashes.
 */
export function RootErrorFallback({
  error,
  errorInfo,
  resetErrorBoundary,
}: ErrorFallbackProps) {
  const [showDetails, setShowDetails] = React.useState(false);

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px',
        backgroundColor: '#f6f6f7',
      }}
    >
      <div style={{ maxWidth: '600px', width: '100%' }}>
        <Card>
          <BlockStack gap="400">
            <BlockStack gap="200">
              <Text as="h1" variant="headingLg">
                Something went wrong
              </Text>
              <Text as="p" variant="bodyMd" tone="subdued">
                We're sorry, but something unexpected happened. Please try
                refreshing the page or contact support if the problem persists.
              </Text>
            </BlockStack>

            <InlineStack gap="300">
              <Button variant="primary" onClick={resetErrorBoundary}>
                Try again
              </Button>
              <Button url={SUPPORT_URL} external>
                Contact support
              </Button>
            </InlineStack>

            <Box paddingBlockStart="200">
              <Button
                variant="plain"
                onClick={() => setShowDetails(!showDetails)}
              >
                {showDetails ? 'Hide error details' : 'Show error details'}
              </Button>
              <Collapsible open={showDetails} id="error-details">
                <Box
                  paddingBlockStart="200"
                  paddingBlockEnd="200"
                  paddingInlineStart="300"
                  paddingInlineEnd="300"
                  background="bg-surface-secondary"
                  borderRadius="200"
                >
                  <BlockStack gap="200">
                    <Text as="p" variant="bodySm" fontWeight="semibold">
                      Error: {error.message}
                    </Text>
                    {errorInfo?.componentStack && (
                      <Text as="p" variant="bodySm" tone="subdued">
                        <pre
                          style={{
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                            fontSize: '12px',
                            margin: 0,
                          }}
                        >
                          {errorInfo.componentStack}
                        </pre>
                      </Text>
                    )}
                  </BlockStack>
                </Box>
              </Collapsible>
            </Box>
          </BlockStack>
        </Card>
      </div>
    </div>
  );
}

interface PageErrorFallbackProps extends ErrorFallbackProps {
  /** Page name to display in error message */
  pageName?: string;
}

/**
 * Page-level error fallback.
 * Card-based error UI for when a specific page crashes.
 */
export function PageErrorFallback({
  error,
  errorInfo,
  resetErrorBoundary,
  pageName = 'This page',
}: PageErrorFallbackProps) {
  const [showDetails, setShowDetails] = React.useState(false);

  return (
    <Page title="Error">
      <Layout>
        <Layout.Section>
          <Banner
            title={`${pageName} encountered an error`}
            tone="critical"
            action={{ content: 'Try again', onAction: resetErrorBoundary }}
            secondaryAction={{
              content: 'Contact support',
              url: SUPPORT_URL,
              external: true,
            }}
          >
            <BlockStack gap="200">
              <Text as="p" variant="bodyMd">
                Something went wrong while loading this page. You can try again
                or navigate to another section of the app.
              </Text>

              <Button
                variant="plain"
                onClick={() => setShowDetails(!showDetails)}
              >
                {showDetails ? 'Hide details' : 'Show details'}
              </Button>

              <Collapsible open={showDetails} id="page-error-details">
                <Box
                  paddingBlockStart="200"
                  background="bg-surface-secondary"
                  borderRadius="100"
                >
                  <Text as="p" variant="bodySm" tone="subdued">
                    Error: {error.message}
                  </Text>
                  {errorInfo?.componentStack && (
                    <Text as="p" variant="bodySm" tone="subdued">
                      <pre
                        style={{
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          fontSize: '11px',
                          margin: '8px 0 0 0',
                          maxHeight: '150px',
                          overflow: 'auto',
                        }}
                      >
                        {errorInfo.componentStack}
                      </pre>
                    </Text>
                  )}
                </Box>
              </Collapsible>
            </BlockStack>
          </Banner>
        </Layout.Section>
      </Layout>
    </Page>
  );
}

interface ComponentErrorFallbackProps extends ErrorFallbackProps {
  /** Component name to display in error message */
  componentName?: string;
}

/**
 * Component-level error fallback.
 * Compact inline error UI for when a specific component crashes.
 */
export function ComponentErrorFallback({
  error,
  resetErrorBoundary,
  componentName = 'This component',
}: ComponentErrorFallbackProps) {
  return (
    <Card>
      <BlockStack gap="300">
        <BlockStack gap="100">
          <Text as="h3" variant="headingSm">
            {componentName} failed to load
          </Text>
          <Text as="p" variant="bodySm" tone="subdued">
            Something went wrong. Please try again or{' '}
            <Link url={SUPPORT_URL} external>
              contact support
            </Link>{' '}
            if the problem persists.
          </Text>
        </BlockStack>

        <InlineStack gap="200">
          <Button size="slim" onClick={resetErrorBoundary}>
            Try again
          </Button>
        </InlineStack>

        {process.env.NODE_ENV === 'development' && (
          <Text as="p" variant="bodySm" tone="subdued">
            Dev: {error.message}
          </Text>
        )}
      </BlockStack>
    </Card>
  );
}
