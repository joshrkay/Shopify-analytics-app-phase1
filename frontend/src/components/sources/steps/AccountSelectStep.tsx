/**
 * Account Select Step Component
 *
 * Step 3 of the connection wizard.
 * Shows discoverable ad accounts with checkboxes for selection.
 *
 * Phase 3 — Subphase 3.4: Connection Wizard Steps 1-3
 */

import {
  BlockStack,
  Text,
  Button,
  Checkbox,
  InlineStack,
  Spinner,
  Banner,
  Box,
} from '@shopify/polaris';
import type { AccountOption } from '../../../types/sourceConnection';

interface AccountSelectStepProps {
  accounts: AccountOption[];
  selectedAccountIds: string[];
  loading: boolean;
  error: string | null;
  onToggleAccount: (accountId: string) => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
  onConfirm: () => void;
  onBack: () => void;
}

export function AccountSelectStep({
  accounts,
  selectedAccountIds,
  loading,
  error,
  onToggleAccount,
  onSelectAll,
  onDeselectAll,
  onConfirm,
  onBack,
}: AccountSelectStepProps) {
  const selectedCount = selectedAccountIds.length;

  if (loading) {
    return (
      <BlockStack gap="400" inlineAlign="center">
        <Spinner size="large" />
        <Text as="p" tone="subdued">
          Loading accounts...
        </Text>
      </BlockStack>
    );
  }

  return (
    <BlockStack gap="500">
      <BlockStack gap="200">
        <Text as="h2" variant="headingLg">
          Select Accounts
        </Text>
        <Text as="p" variant="bodyMd" tone="subdued">
          Choose which accounts to sync data from.
        </Text>
      </BlockStack>

      {error && (
        <Banner tone="critical">
          <p>{error}</p>
        </Banner>
      )}

      {accounts.length === 0 && !error ? (
        <Banner tone="warning">
          <p>No accounts found. Go back and re-authorize to try again.</p>
        </Banner>
      ) : (
        <>
          <InlineStack gap="200">
            <Button variant="plain" onClick={onSelectAll}>
              Select All
            </Button>
            <Button variant="plain" onClick={onDeselectAll}>
              Deselect All
            </Button>
          </InlineStack>

          <BlockStack gap="200">
            {accounts.map((account) => (
              <Box
                key={account.id}
                background="bg-surface"
                borderColor="border"
                borderWidth="025"
                borderRadius="200"
                padding="300"
              >
                <Checkbox
                  label={account.accountName}
                  helpText={`Account ID: ${account.accountId}`}
                  checked={selectedAccountIds.includes(account.id)}
                  onChange={() => onToggleAccount(account.id)}
                />
              </Box>
            ))}
          </BlockStack>
        </>
      )}

      <Banner tone="info">
        <p>You can change this later in settings.</p>
      </Banner>

      <InlineStack gap="200" align="end">
        <Button onClick={onBack}>Back</Button>
        <Button
          variant="primary"
          onClick={onConfirm}
          disabled={selectedCount === 0}
        >
          {selectedCount > 0 ? `Connect (${selectedCount})` : 'Connect'} →
        </Button>
      </InlineStack>
    </BlockStack>
  );
}
