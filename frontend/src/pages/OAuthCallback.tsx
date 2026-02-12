/**
 * OAuth Callback Page
 *
 * Handles OAuth redirect callback from external platforms (Meta Ads, Google Ads, etc.)
 * Parses authorization code and state from query params, completes OAuth flow via backend,
 * then redirects to /sources page.
 *
 * Security: State parameter is validated by backend to prevent CSRF attacks.
 *
 * Phase 3 — Subphase 3.4: OAuth Redirect Handler
 */

import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Page, Card, Banner, Spinner, BlockStack, Text } from '@shopify/polaris';
import { completeOAuth } from '../services/sourcesApi';

export default function OAuthCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [completing, setCompleting] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function handleCallback() {
      // Extract OAuth callback parameters
      const code = searchParams.get('code');
      const state = searchParams.get('state');
      const errorParam = searchParams.get('error');
      const errorDescription = searchParams.get('error_description');

      // Handle OAuth error from provider
      if (errorParam) {
        if (!cancelled) {
          setError(
            errorDescription ||
              `OAuth authorization failed: ${errorParam}` ||
              'Authorization was denied or failed'
          );
          setCompleting(false);
        }
        return;
      }

      // Validate required parameters
      if (!code || !state) {
        if (!cancelled) {
          setError('Invalid OAuth callback: missing code or state parameter');
          setCompleting(false);
        }
        return;
      }

      // Complete OAuth flow via backend
      try {
        const response = await completeOAuth({ code, state });

        if (!cancelled) {
          if (response.success) {
            // Success: redirect to sources page
            navigate('/sources', {
              replace: true,
              state: {
                message: 'Data source connected successfully',
                connectionId: response.connection_id,
              },
            });
          } else {
            setError(response.error || 'Failed to complete OAuth authorization');
            setCompleting(false);
          }
        }
      } catch (err) {
        if (!cancelled) {
          console.error('OAuth completion failed:', err);
          setError(
            err instanceof Error ? err.message : 'Failed to complete OAuth authorization'
          );
          setCompleting(false);
        }
      }
    }

    handleCallback();

    return () => {
      cancelled = true;
    };
  }, [searchParams, navigate]);

  if (completing) {
    return (
      <Page narrowWidth>
        <Card>
          <BlockStack gap="400" inlineAlign="center">
            <Spinner size="large" />
            <BlockStack gap="200" inlineAlign="center">
              <Text as="h2" variant="headingMd">
                Completing Connection...
              </Text>
              <Text as="p" tone="subdued">
                Please wait while we finish setting up your data source.
              </Text>
            </BlockStack>
          </BlockStack>
        </Card>
      </Page>
    );
  }

  if (error) {
    return (
      <Page narrowWidth>
        <BlockStack gap="400">
          <Banner
            title="Connection Failed"
            tone="critical"
            action={{
              content: 'Try Again',
              onAction: () => navigate('/sources'),
            }}
          >
            <p>{error}</p>
          </Banner>
          <Card>
            <BlockStack gap="400">
              <Text as="h2" variant="headingMd">
                Unable to Connect Data Source
              </Text>
              <Text as="p">
                We encountered an error while connecting your data source. This may be due to:
              </Text>
              <ul>
                <li>Authorization was denied or cancelled</li>
                <li>Invalid or expired authorization code</li>
                <li>Network connectivity issues</li>
              </ul>
              <Text as="p">
                Please try connecting again. If the problem persists, contact support.
              </Text>
            </BlockStack>
          </Card>
        </BlockStack>
      </Page>
    );
  }

  return null;
}
