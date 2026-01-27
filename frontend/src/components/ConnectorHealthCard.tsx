/**
 * Connector Health Card Component
 *
 * Displays health status for a single connector.
 * Shows status, last sync time, row count, and recommended actions.
 */

import React, { useState } from 'react';
import {
  Card,
  BlockStack,
  InlineStack,
  Text,
  Badge,
  Button,
  Collapsible,
  Box,
  Icon,
  List,
  Divider,
} from '@shopify/polaris';
import {
  ClockIcon,
  DatabaseIcon,
  AlertCircleIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  RefreshIcon,
  PlayIcon,
} from '@shopify/polaris-icons';

import {
  type ConnectorHealth,
  formatTimeSinceSync,
  getStatusBadgeTone,
  getSeverityBadgeTone,
} from '../services/syncHealthApi';

interface ConnectorHealthCardProps {
  connector: ConnectorHealth;
  onBackfillClick?: () => void;
  onRetrySync?: () => void;
}

const ConnectorHealthCard: React.FC<ConnectorHealthCardProps> = ({
  connector,
  onBackfillClick,
  onRetrySync,
}) => {
  const [expanded, setExpanded] = useState(false);

  // Format source type for display
  const formatSourceType = (sourceType: string | null): string => {
    if (!sourceType) return 'Unknown';
    return sourceType
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  };

  // Get status icon
  const getStatusIcon = () => {
    switch (connector.status) {
      case 'healthy':
        return <Icon source={DatabaseIcon} tone="success" />;
      case 'delayed':
        return <Icon source={ClockIcon} tone="caution" />;
      case 'error':
        return <Icon source={AlertCircleIcon} tone="critical" />;
      default:
        return <Icon source={DatabaseIcon} />;
    }
  };

  // Format last sync time
  const formatLastSync = (): string => {
    if (connector.last_sync_at) {
      const date = new Date(connector.last_sync_at);
      return date.toLocaleString();
    }
    return 'Never synced';
  };

  // Format row count
  const formatRowCount = (count: number | null): string => {
    if (count === null) return 'N/A';
    return count.toLocaleString();
  };

  return (
    <Box
      background={
        connector.is_blocking
          ? 'bg-surface-critical'
          : connector.status === 'error'
          ? 'bg-surface-warning'
          : 'bg-surface'
      }
      borderColor={
        connector.is_blocking
          ? 'border-critical'
          : connector.status !== 'healthy'
          ? 'border-caution'
          : 'border'
      }
      borderWidth="025"
      borderRadius="200"
      padding="300"
    >
      <BlockStack gap="300">
        {/* Header */}
        <InlineStack align="space-between" blockAlign="center">
          <InlineStack gap="200" blockAlign="center">
            {getStatusIcon()}
            <BlockStack gap="100">
              <Text as="span" variant="bodyMd" fontWeight="semibold">
                {connector.connector_name}
              </Text>
              <Text as="span" variant="bodySm" tone="subdued">
                {formatSourceType(connector.source_type)}
              </Text>
            </BlockStack>
          </InlineStack>

          <InlineStack gap="200" blockAlign="center">
            <Badge tone={getStatusBadgeTone(connector.status)}>
              {connector.status === 'healthy'
                ? 'Healthy'
                : connector.status === 'delayed'
                ? 'Delayed'
                : 'Error'}
            </Badge>

            {connector.severity && (
              <Badge tone={getSeverityBadgeTone(connector.severity)}>
                {connector.severity.toUpperCase()}
              </Badge>
            )}

            {connector.is_blocking && (
              <Badge tone="critical">Blocking</Badge>
            )}

            {connector.has_open_incidents && (
              <Badge tone="attention">
                {connector.open_incident_count} Issue{connector.open_incident_count > 1 ? 's' : ''}
              </Badge>
            )}
          </InlineStack>
        </InlineStack>

        {/* Sync Info */}
        <InlineStack gap="400" wrap={false}>
          <BlockStack gap="100">
            <Text as="span" variant="bodySm" tone="subdued">
              Last Sync
            </Text>
            <Text as="span" variant="bodySm">
              {formatTimeSinceSync(connector.minutes_since_sync)}
            </Text>
          </BlockStack>

          <BlockStack gap="100">
            <Text as="span" variant="bodySm" tone="subdued">
              Rows Synced
            </Text>
            <Text as="span" variant="bodySm">
              {formatRowCount(connector.last_rows_synced)}
            </Text>
          </BlockStack>
        </InlineStack>

        {/* Merchant Message (if not healthy) */}
        {connector.status !== 'healthy' && connector.merchant_message && (
          <Box
            background="bg-surface-secondary"
            padding="200"
            borderRadius="100"
          >
            <Text as="p" variant="bodySm">
              {connector.merchant_message}
            </Text>
          </Box>
        )}

        {/* Expand/Collapse Toggle */}
        <InlineStack align="space-between">
          <Button
            variant="plain"
            onClick={() => setExpanded(!expanded)}
            icon={expanded ? ChevronUpIcon : ChevronDownIcon}
          >
            {expanded ? 'Show less' : 'Show details'}
          </Button>

          <InlineStack gap="200">
            {onRetrySync && connector.status !== 'healthy' && (
              <Button
                variant="plain"
                icon={RefreshIcon}
                onClick={onRetrySync}
              >
                Retry Sync
              </Button>
            )}
            {onBackfillClick && (
              <Button
                variant="plain"
                icon={PlayIcon}
                onClick={onBackfillClick}
              >
                Run Backfill
              </Button>
            )}
          </InlineStack>
        </InlineStack>

        {/* Collapsible Details */}
        <Collapsible open={expanded} id={`connector-${connector.connector_id}-details`}>
          <BlockStack gap="300">
            <Divider />

            {/* Full Sync Info */}
            <BlockStack gap="200">
              <Text as="h4" variant="headingSm">
                Sync Details
              </Text>
              <InlineStack gap="400" wrap>
                <BlockStack gap="100">
                  <Text as="span" variant="bodySm" tone="subdued">
                    Last Sync Time
                  </Text>
                  <Text as="span" variant="bodySm">
                    {formatLastSync()}
                  </Text>
                </BlockStack>

                <BlockStack gap="100">
                  <Text as="span" variant="bodySm" tone="subdued">
                    Freshness Status
                  </Text>
                  <Text as="span" variant="bodySm">
                    {connector.freshness_status === 'fresh'
                      ? 'Fresh'
                      : connector.freshness_status === 'stale'
                      ? 'Stale'
                      : connector.freshness_status === 'critical'
                      ? 'Critical'
                      : 'Never Synced'}
                  </Text>
                </BlockStack>

                <BlockStack gap="100">
                  <Text as="span" variant="bodySm" tone="subdued">
                    Connector ID
                  </Text>
                  <Text as="span" variant="bodySm" fontWeight="medium">
                    {connector.connector_id.slice(0, 8)}...
                  </Text>
                </BlockStack>
              </InlineStack>
            </BlockStack>

            {/* Recommended Actions */}
            {connector.recommended_actions.length > 0 && (
              <BlockStack gap="200">
                <Text as="h4" variant="headingSm">
                  Recommended Actions
                </Text>
                <List type="bullet">
                  {connector.recommended_actions.map((action, index) => (
                    <List.Item key={index}>{action}</List.Item>
                  ))}
                </List>
              </BlockStack>
            )}

            {/* Technical Message (for debugging) */}
            {connector.message && (
              <BlockStack gap="200">
                <Text as="h4" variant="headingSm">
                  Status Message
                </Text>
                <Text as="p" variant="bodySm" tone="subdued">
                  {connector.message}
                </Text>
              </BlockStack>
            )}
          </BlockStack>
        </Collapsible>
      </BlockStack>
    </Box>
  );
};

export default ConnectorHealthCard;
