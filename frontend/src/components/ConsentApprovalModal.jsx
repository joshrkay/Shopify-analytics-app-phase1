/**
 * ConsentApprovalModal Component
 *
 * Modal for merchant admin to approve or deny a data ingestion connection.
 * Displays the app name, connection details, and captures the decision
 * with an immutable audit trail.
 *
 * FLOW:
 * 1. Agency/Merchant Admin requests connection → creates PENDING consent
 * 2. Merchant Admin opens this modal → sees consent details
 * 3. Merchant approves or denies → decision is immutable
 * 4. Denied requests cannot auto-retry
 */

import { useState, useCallback } from 'react';
import {
  Modal,
  BlockStack,
  InlineStack,
  Text,
  Badge,
  TextField,
  Banner,
  Box,
} from '@shopify/polaris';

/**
 * @typedef {Object} ConsentRequest
 * @property {string} id - Consent record ID
 * @property {string} connection_id - Connection being consented
 * @property {string} connection_name - Human-readable connection label
 * @property {string} source_type - Connector type (shopify, meta, etc.)
 * @property {string} app_name - App requesting data access
 * @property {string} status - pending | approved | denied
 * @property {string} requested_by - Who initiated the request
 * @property {string} created_at - ISO timestamp
 */

/**
 * @param {Object} props
 * @param {boolean} props.open - Whether modal is visible
 * @param {ConsentRequest} props.consent - The consent request to act on
 * @param {(reason?: string) => void} props.onApprove - Called on approval
 * @param {(reason?: string) => void} props.onDeny - Called on denial
 * @param {() => void} props.onClose - Called on modal close
 * @param {boolean} [props.isLoading=false] - Loading state for actions
 */
export function ConsentApprovalModal({
  open,
  consent,
  onApprove,
  onDeny,
  onClose,
  isLoading = false,
}) {
  const [reason, setReason] = useState('');
  const [showDenyForm, setShowDenyForm] = useState(false);

  const handleApprove = useCallback(() => {
    onApprove(reason || undefined);
    setReason('');
    setShowDenyForm(false);
  }, [onApprove, reason]);

  const handleDeny = useCallback(() => {
    onDeny(reason || undefined);
    setReason('');
    setShowDenyForm(false);
  }, [onDeny, reason]);

  const handleClose = useCallback(() => {
    onClose();
    setReason('');
    setShowDenyForm(false);
  }, [onClose]);

  const handleDenyClick = useCallback(() => {
    setShowDenyForm(true);
  }, []);

  if (!consent) {
    return null;
  }

  const sourceLabel = consent.source_type
    ? consent.source_type.charAt(0).toUpperCase() +
      consent.source_type.slice(1).replace(/_/g, ' ')
    : 'Unknown';

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Data Connection Approval"
      primaryAction={
        showDenyForm
          ? {
              content: 'Deny Connection',
              onAction: handleDeny,
              loading: isLoading,
              destructive: true,
            }
          : {
              content: 'Approve Connection',
              onAction: handleApprove,
              loading: isLoading,
            }
      }
      secondaryActions={
        showDenyForm
          ? [
              {
                content: 'Back',
                onAction: () => setShowDenyForm(false),
              },
            ]
          : [
              {
                content: 'Deny',
                onAction: handleDenyClick,
                destructive: true,
              },
            ]
      }
    >
      <Modal.Section>
        <BlockStack gap="400">
          {/* Consent message */}
          <Banner tone="info">
            <Text as="p" variant="bodyMd">
              We are testing <Text as="span" fontWeight="bold">{consent.app_name}</Text> to
              bring in your reporting data. Please approve or deny.
            </Text>
          </Banner>

          {/* Connection details */}
          <BlockStack gap="200">
            <Text as="h3" variant="headingSm">
              Connection Details
            </Text>

            <Box paddingBlockStart="100">
              <BlockStack gap="100">
                <InlineStack gap="200">
                  <Text as="span" variant="bodySm" tone="subdued">
                    Connection:
                  </Text>
                  <Text as="span" variant="bodyMd">
                    {consent.connection_name}
                  </Text>
                </InlineStack>

                <InlineStack gap="200">
                  <Text as="span" variant="bodySm" tone="subdued">
                    Source Type:
                  </Text>
                  <Badge>{sourceLabel}</Badge>
                </InlineStack>

                <InlineStack gap="200">
                  <Text as="span" variant="bodySm" tone="subdued">
                    Status:
                  </Text>
                  <Badge
                    tone={
                      consent.status === 'approved'
                        ? 'success'
                        : consent.status === 'denied'
                          ? 'critical'
                          : 'attention'
                    }
                  >
                    {consent.status.charAt(0).toUpperCase() +
                      consent.status.slice(1)}
                  </Badge>
                </InlineStack>
              </BlockStack>
            </Box>
          </BlockStack>

          {/* Deny reason form */}
          {showDenyForm && (
            <BlockStack gap="200">
              <Banner tone="warning">
                <Text as="p" variant="bodySm">
                  Denying this request will block the connection. A new
                  consent request must be created to try again.
                </Text>
              </Banner>
              <TextField
                label="Reason for denial (optional)"
                value={reason}
                onChange={setReason}
                multiline={3}
                autoComplete="off"
                helpText="Providing a reason helps the requesting team understand your decision"
              />
            </BlockStack>
          )}

          {/* Audit notice */}
          <Banner tone="info">
            <Text as="p" variant="bodySm">
              Your decision will be recorded with a timestamp for audit
              purposes and cannot be changed.
            </Text>
          </Banner>
        </BlockStack>
      </Modal.Section>
    </Modal>
  );
}

export default ConsentApprovalModal;
