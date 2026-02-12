/**
 * Settings Page
 *
 * Settings hub with links to configuration pages.
 * Phase 3 — Minimal MVP with link to Data Sources page.
 * Future: Tabs for Billing, Team, AI, etc. (Phase 4+)
 */

import { Page, Layout, Card, BlockStack, Text, Button } from '@shopify/polaris';
import { useNavigate } from 'react-router-dom';

export default function Settings() {
  const navigate = useNavigate();

  return (
    <Page title="Settings">
      <Layout>
        <Layout.Section>
          <Card>
            <BlockStack gap="400">
              <BlockStack gap="200">
                <Text as="h2" variant="headingMd">
                  Data Sources
                </Text>
                <Text as="p" tone="subdued">
                  Manage your connected data sources, configure sync schedules, and monitor data
                  health.
                </Text>
              </BlockStack>
              <Button onClick={() => navigate('/sources')}>Go to Data Sources</Button>
            </BlockStack>
          </Card>
        </Layout.Section>

        <Layout.Section>
          <Card>
            <BlockStack gap="400">
              <BlockStack gap="200">
                <Text as="h2" variant="headingMd">
                  Additional Settings
                </Text>
                <Text as="p" tone="subdued">
                  Billing, team management, AI configuration, and other settings coming soon.
                </Text>
              </BlockStack>
            </BlockStack>
          </Card>
        </Layout.Section>
      </Layout>
    </Page>
  );
}
