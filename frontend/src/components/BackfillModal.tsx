/**
 * Backfill Modal Component
 *
 * Modal for triggering data backfills.
 * Validates date range (max 90 days for merchants).
 * Shows estimated scope and warnings about rate limits.
 */

import React, { useState, useCallback, useEffect } from 'react';
import {
  Modal,
  BlockStack,
  InlineStack,
  Text,
  TextField,
  Banner,
  Box,
  ProgressBar,
  Spinner,
  Badge,
  List,
} from '@shopify/polaris';

import {
  type ConnectorHealth,
  type BackfillEstimate,
  estimateBackfill,
  triggerBackfill,
  calculateBackfillDateRange,
} from '../services/syncHealthApi';

interface BackfillModalProps {
  open: boolean;
  connector: ConnectorHealth;
  onClose: () => void;
  onSuccess: () => void;
}

const BackfillModal: React.FC<BackfillModalProps> = ({
  open,
  connector,
  onClose,
  onSuccess,
}) => {
  // Form state
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  // Validation state
  const [validation, setValidation] = useState<{
    isValid: boolean;
    days: number;
    message: string;
  } | null>(null);

  // API state
  const [estimate, setEstimate] = useState<BackfillEstimate | null>(null);
  const [loading, setLoading] = useState(false);
  const [estimating, setEstimating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Initialize dates (default to last 7 days)
  useEffect(() => {
    if (open) {
      const today = new Date();
      const weekAgo = new Date(today);
      weekAgo.setDate(weekAgo.getDate() - 7);

      setEndDate(today.toISOString().split('T')[0]);
      setStartDate(weekAgo.toISOString().split('T')[0]);
      setError(null);
      setSuccess(false);
      setEstimate(null);
    }
  }, [open]);

  // Validate date range when dates change
  useEffect(() => {
    if (startDate && endDate) {
      const start = new Date(startDate);
      const end = new Date(endDate);
      const result = calculateBackfillDateRange(start, end);
      setValidation(result);

      // Fetch estimate if valid
      if (result.isValid) {
        fetchEstimate();
      } else {
        setEstimate(null);
      }
    } else {
      setValidation(null);
      setEstimate(null);
    }
  }, [startDate, endDate]);

  // Fetch backfill estimate
  const fetchEstimate = useCallback(async () => {
    if (!startDate || !endDate) return;

    setEstimating(true);
    try {
      const result = await estimateBackfill(
        connector.connector_id,
        startDate,
        endDate
      );
      setEstimate(result);
      setError(null);
    } catch (err) {
      console.error('Failed to fetch estimate:', err);
      // Don't show error for estimate failure, just clear estimate
      setEstimate(null);
    } finally {
      setEstimating(false);
    }
  }, [connector.connector_id, startDate, endDate]);

  // Handle form submission
  const handleSubmit = async () => {
    if (!validation?.isValid) return;

    setLoading(true);
    setError(null);

    try {
      await triggerBackfill(connector.connector_id, {
        start_date: startDate,
        end_date: endDate,
      });

      setSuccess(true);

      // Auto-close after success
      setTimeout(() => {
        onSuccess();
      }, 2000);
    } catch (err: any) {
      console.error('Failed to trigger backfill:', err);
      setError(err.detail || 'Failed to trigger backfill. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  // Get today's date for max date
  const today = new Date().toISOString().split('T')[0];

  // Calculate max start date (90 days ago)
  const maxStartDate = new Date();
  maxStartDate.setDate(maxStartDate.getDate() - 90);
  const minStartDateStr = maxStartDate.toISOString().split('T')[0];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Run Backfill: ${connector.connector_name}`}
      primaryAction={{
        content: success ? 'Done' : 'Start Backfill',
        onAction: success ? onSuccess : handleSubmit,
        loading: loading,
        disabled: !validation?.isValid || loading || success,
      }}
      secondaryActions={[
        {
          content: 'Cancel',
          onAction: onClose,
          disabled: loading,
        },
      ]}
    >
      <Modal.Section>
        <BlockStack gap="400">
          {/* Success Banner */}
          {success && (
            <Banner
              title="Backfill Started"
              tone="success"
            >
              <p>
                Your backfill has been queued and will begin shortly.
                You will be notified when it completes.
              </p>
            </Banner>
          )}

          {/* Error Banner */}
          {error && (
            <Banner
              title="Backfill Failed"
              tone="critical"
              onDismiss={() => setError(null)}
            >
              <p>{error}</p>
            </Banner>
          )}

          {/* Info */}
          {!success && (
            <>
              <Text as="p" variant="bodyMd">
                Select a date range to backfill data for{' '}
                <strong>{connector.connector_name}</strong>.
              </Text>

              {/* Date Range Inputs */}
              <InlineStack gap="400" wrap={false}>
                <Box minWidth="45%">
                  <TextField
                    label="Start Date"
                    type="date"
                    value={startDate}
                    onChange={setStartDate}
                    min={minStartDateStr}
                    max={endDate || today}
                    autoComplete="off"
                  />
                </Box>
                <Box minWidth="45%">
                  <TextField
                    label="End Date"
                    type="date"
                    value={endDate}
                    onChange={setEndDate}
                    min={startDate || minStartDateStr}
                    max={today}
                    autoComplete="off"
                  />
                </Box>
              </InlineStack>

              {/* Validation Message */}
              {validation && (
                <Box
                  background={
                    validation.isValid ? 'bg-surface-success' : 'bg-surface-critical'
                  }
                  padding="200"
                  borderRadius="100"
                >
                  <InlineStack gap="200" blockAlign="center">
                    <Badge tone={validation.isValid ? 'success' : 'critical'}>
                      {validation.isValid ? 'Valid' : 'Invalid'}
                    </Badge>
                    <Text as="span" variant="bodySm">
                      {validation.message}
                    </Text>
                  </InlineStack>
                </Box>
              )}

              {/* Estimate Loading */}
              {estimating && (
                <InlineStack gap="200" blockAlign="center">
                  <Spinner size="small" />
                  <Text as="span" variant="bodySm" tone="subdued">
                    Calculating estimate...
                  </Text>
                </InlineStack>
              )}

              {/* Estimate Display */}
              {estimate && !estimating && (
                <Box
                  background="bg-surface-secondary"
                  padding="300"
                  borderRadius="200"
                >
                  <BlockStack gap="300">
                    <Text as="h4" variant="headingSm">
                      Backfill Estimate
                    </Text>

                    <InlineStack gap="400">
                      <BlockStack gap="100">
                        <Text as="span" variant="bodySm" tone="subdued">
                          Days to Process
                        </Text>
                        <Text as="span" variant="bodyMd" fontWeight="semibold">
                          {estimate.days_count}
                        </Text>
                      </BlockStack>

                      <BlockStack gap="100">
                        <Text as="span" variant="bodySm" tone="subdued">
                          Max Allowed
                        </Text>
                        <Text as="span" variant="bodyMd">
                          {estimate.max_allowed_days} days
                        </Text>
                      </BlockStack>
                    </InlineStack>

                    {/* Progress indicator */}
                    <BlockStack gap="100">
                      <Text as="span" variant="bodySm" tone="subdued">
                        Range Usage
                      </Text>
                      <ProgressBar
                        progress={(estimate.days_count / estimate.max_allowed_days) * 100}
                        tone={
                          estimate.days_count / estimate.max_allowed_days > 0.8
                            ? 'critical'
                            : estimate.days_count / estimate.max_allowed_days > 0.5
                            ? 'highlight'
                            : 'success'
                        }
                      />
                    </BlockStack>
                  </BlockStack>
                </Box>
              )}

              {/* Warning for large backfills */}
              {estimate?.warning && (
                <Banner
                  title="Large Backfill Warning"
                  tone="warning"
                >
                  <p>{estimate.warning}</p>
                </Banner>
              )}

              {/* Rate Limit Warning */}
              {validation?.isValid && validation.days > 30 && (
                <Banner
                  title="Rate Limit Advisory"
                  tone="info"
                >
                  <BlockStack gap="200">
                    <Text as="p" variant="bodySm">
                      Large backfills may be affected by API rate limits:
                    </Text>
                    <List type="bullet">
                      <List.Item>
                        Processing may take several hours to complete
                      </List.Item>
                      <List.Item>
                        Some data sources have daily API quotas
                      </List.Item>
                      <List.Item>
                        You will be notified when the backfill completes
                      </List.Item>
                    </List>
                  </BlockStack>
                </Banner>
              )}

              {/* Max Days Info */}
              <Box
                background="bg-surface-secondary"
                padding="200"
                borderRadius="100"
              >
                <Text as="p" variant="bodySm" tone="subdued">
                  Merchants can backfill up to 90 days. For larger backfills,
                  please contact support.
                </Text>
              </Box>
            </>
          )}
        </BlockStack>
      </Modal.Section>
    </Modal>
  );
};

export default BackfillModal;
