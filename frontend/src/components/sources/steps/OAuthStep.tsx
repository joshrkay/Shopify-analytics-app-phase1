/**
 * OAuth Step Component
 *
 * Step 2 of the connection wizard.
 * Shows OAuth authorization explanation, redirect button, loading state, and error handling.
 *
 * Phase 3 — Subphase 3.4: Connection Wizard Steps 1-3
 */

import { BlockStack, Text, Banner, Button, Spinner, InlineStack, List } from '@shopify/polaris';
import type { DataSourceDefinition } from '../../../types/sourceConnection';

interface OAuthStepProps {
  platform: DataSourceDefinition;
  loading: boolean;
  error: string | null;
  onStartOAuth: () => Promise<void>;
  onCancel: () => void;
}

export function OAuthStep({ platform, loading, error, onStartOAuth, onCancel }: OAuthStepProps) {
  return (
    <BlockStack gap="500">
      <BlockStack gap="200" inlineAlign="center">
        <Text as="h2" variant="headingLg" alignment="center">
          Authorize {platform.displayName}
        </Text>
        <Text as="p" variant="bodyMd" tone="subdued" alignment="center">
          {loading
            ? `Redirecting to ${platform.displayName}...`
            : `Connect your ${platform.displayName} account securely via OAuth.`}
        </Text>
      </BlockStack>

      {loading && (
        <InlineStack align="center" gap="200">
          <Spinner size="large" />
        </InlineStack>
      )}

      {error && (
        <Banner tone="critical" title="Authorization Failed">
          <p>{error}</p>
        </Banner>
      )}

      {!loading && (
        <BlockStack gap="300">
          <Text as="h3" variant="headingSm">
            How it works
          </Text>
          <List type="number">
            <List.Item>Click "Authorize" below to open {platform.displayName}</List.Item>
            <List.Item>Sign in and grant read-only access</List.Item>
            <List.Item>You'll be redirected back here automatically</List.Item>
            <List.Item>Select which accounts to sync</List.Item>
          </List>
        </BlockStack>
      )}

      <InlineStack gap="200" align="end">
        <Button onClick={onCancel}>Cancel</Button>
        <Button
          variant="primary"
          onClick={onStartOAuth}
          loading={loading}
          disabled={loading}
        >
          {error ? 'Try Again' : `Authorize ${platform.displayName}`}
        </Button>
      </InlineStack>
    </BlockStack>
  );
}
