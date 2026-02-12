/**
 * Connect Source Modal Component
 *
 * Multi-step wizard modal for connecting new data sources.
 * Handles platform selection, configuration, OAuth flow, and connection testing.
 *
 * Steps:
 * 1. Select Platform — Browse available integrations
 * 2. Configure — Platform-specific setup (shop domain, API keys, etc.)
 * 3. Authenticate — OAuth redirect or credential validation
 * 4. Test Connection — Verify connectivity
 * 5. Complete — Success confirmation
 *
 * Phase 3 — Subphase 3.5: Connection Wizard UI
 */

import { useState, useCallback, useEffect } from 'react';
import {
  Modal,
  BlockStack,
  InlineGrid,
  TextField,
  Button,
  Banner,
  Text,
  Spinner,
  InlineStack,
} from '@shopify/polaris';
import type { DataSourceDefinition } from '../../types/sourceConnection';
import { useConnectionWizard, useSourceCatalog } from '../../hooks/useSourceConnection';
import { ConnectionSteps } from './ConnectionSteps';
import { PlatformCard } from './PlatformCard';

interface ConnectSourceModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: (connectionId: string) => void;
  initialPlatform?: DataSourceDefinition | null;
}

/**
 * Modal wizard for connecting new data sources.
 *
 * Usage:
 * ```tsx
 * <ConnectSourceModal
 *   open={showModal}
 *   onClose={() => setShowModal(false)}
 *   onSuccess={(id) => {
 *     console.log('Connected:', id);
 *     loadSources();
 *   }}
 * />
 * ```
 */
export function ConnectSourceModal({ open, onClose, onSuccess, initialPlatform }: ConnectSourceModalProps) {
  const { catalog, loading: loadingCatalog } = useSourceCatalog();
  const {
    state,
    selectPlatform,
    configure,
    startOAuth,
    testConnection,
    setError,
    reset,
  } = useConnectionWizard();

  // Platform configuration state
  const [shopDomain, setShopDomain] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [configuring, setConfiguring] = useState(false);

  // Auto-select platform when modal opens with an initialPlatform
  useEffect(() => {
    if (open && initialPlatform) {
      selectPlatform(initialPlatform);
    }
  }, [open, initialPlatform, selectPlatform]);

  const handleClose = useCallback(() => {
    reset();
    setShopDomain('');
    setApiKey('');
    setConfiguring(false);
    onClose();
  }, [reset, onClose]);

  const handlePlatformSelect = useCallback(
    (platform: any) => {
      selectPlatform(platform);
    },
    [selectPlatform]
  );

  const handleConfigure = useCallback(async () => {
    if (!state.selectedPlatform) return;

    setConfiguring(true);
    setError(null);

    try {
      const config: Record<string, any> = {};

      // Platform-specific configuration
      if (state.selectedPlatform.platform === 'shopify') {
        if (!shopDomain) {
          setError('Shop domain is required');
          setConfiguring(false);
          return;
        }
        config.shop_domain = shopDomain;
      }

      if (state.selectedPlatform.authType === 'api_key') {
        if (!apiKey) {
          setError('API key is required');
          setConfiguring(false);
          return;
        }
        config.api_key = apiKey;
      }

      configure(config);

      // For OAuth platforms, initiate OAuth flow
      if (state.selectedPlatform.authType === 'oauth') {
        await startOAuth();
      } else {
        // For API key platforms, move to test step
        await testConnection();
      }
    } catch (err) {
      console.error('Configuration failed:', err);
      setError(err instanceof Error ? err.message : 'Configuration failed');
    } finally {
      setConfiguring(false);
    }
  }, [
    state.selectedPlatform,
    shopDomain,
    apiKey,
    configure,
    startOAuth,
    testConnection,
    setError,
  ]);

  // Step 1: Select Platform
  const renderSelectStep = () => (
    <BlockStack gap="400">
      <Text as="p" tone="subdued">
        Choose a data source to connect. We support e-commerce platforms, advertising networks,
        email marketing, and SMS providers.
      </Text>

      {loadingCatalog ? (
        <InlineStack align="center">
          <Spinner size="small" />
          <Text as="span" tone="subdued">
            Loading platforms...
          </Text>
        </InlineStack>
      ) : (
        <InlineGrid columns={{ xs: 1, sm: 2, md: 2 }} gap="400">
          {catalog.map((platform) => (
            <PlatformCard key={platform.id} platform={platform} onSelect={handlePlatformSelect} />
          ))}
        </InlineGrid>
      )}
    </BlockStack>
  );

  // Step 2: Configure
  const renderConfigureStep = () => {
    if (!state.selectedPlatform) return null;

    const isShopify = state.selectedPlatform.platform === 'shopify';
    const isApiKey = state.selectedPlatform.authType === 'api_key';

    return (
      <BlockStack gap="400">
        <Text as="p" tone="subdued">
          {isShopify
            ? 'Enter your Shopify store domain to connect.'
            : isApiKey
              ? `Enter your ${state.selectedPlatform.displayName} API credentials.`
              : `Authorize ${state.selectedPlatform.displayName} to sync your data.`}
        </Text>

        {isShopify && (
          <TextField
            label="Shop Domain"
            value={shopDomain}
            onChange={setShopDomain}
            placeholder="your-store.myshopify.com"
            autoComplete="off"
            helpText="Your Shopify store URL (e.g., your-store.myshopify.com)"
          />
        )}

        {isApiKey && (
          <TextField
            label="API Key"
            value={apiKey}
            onChange={setApiKey}
            type="password"
            autoComplete="off"
            helpText={`Your ${state.selectedPlatform.displayName} API key`}
          />
        )}

        {!isApiKey && !isShopify && (
          <Banner>
            <p>
              You'll be redirected to {state.selectedPlatform.displayName} to authorize access to
              your account. After authorization, you'll be redirected back here.
            </p>
          </Banner>
        )}

        <InlineStack gap="200">
          <Button onClick={handleClose}>Cancel</Button>
          <Button variant="primary" onClick={handleConfigure} loading={configuring}>
            {isApiKey ? 'Connect' : 'Continue to Authorization'}
          </Button>
        </InlineStack>
      </BlockStack>
    );
  };

  // Step 3: Authenticate (OAuth redirect happens automatically)
  const renderAuthenticateStep = () => (
    <BlockStack gap="400" inlineAlign="center">
      <Spinner size="large" />
      <Text as="p" tone="subdued">
        Redirecting to authorization...
      </Text>
    </BlockStack>
  );

  // Step 4: Test Connection
  const renderTestStep = () => (
    <BlockStack gap="400" inlineAlign="center">
      <Spinner size="large" />
      <Text as="p" tone="subdued">
        Testing connection...
      </Text>
    </BlockStack>
  );

  // Step 5: Complete
  const renderCompleteStep = () => (
    <BlockStack gap="400">
      <Banner tone="success">
        <p>
          {state.selectedPlatform?.displayName} connected successfully! Your data will begin
          syncing shortly.
        </p>
      </Banner>

      <Text as="p">
        You can now view and manage this connection in your Data Sources page. The initial sync may
        take a few minutes depending on your data volume.
      </Text>

      <Button variant="primary" onClick={handleClose}>
        Done
      </Button>
    </BlockStack>
  );

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Connect Data Source"
      large
      primaryAction={undefined}
    >
      <Modal.Section>
        <BlockStack gap="400">
          <ConnectionSteps currentStep={state.step} />

          {state.error && (
            <Banner tone="critical" onDismiss={() => setError(null)}>
              <p>{state.error}</p>
            </Banner>
          )}

          {state.step === 'select' && renderSelectStep()}
          {state.step === 'configure' && renderConfigureStep()}
          {state.step === 'authenticate' && renderAuthenticateStep()}
          {state.step === 'test' && renderTestStep()}
          {state.step === 'complete' && renderCompleteStep()}
        </BlockStack>
      </Modal.Section>
    </Modal>
  );
}
