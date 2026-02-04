/**
 * InsightCard Component
 *
 * Displays a single AI insight with severity badge, metrics, and actions.
 * Supports dismiss and mark-as-read functionality.
 *
 * Story 9.3 - Insight & Recommendation UX
 */

import { useState } from 'react';
import {
  Card,
  BlockStack,
  InlineStack,
  Text,
  Badge,
  Button,
  Collapsible,
  Box,
  Divider,
  Icon,
  Tooltip,
} from '@shopify/polaris';
import {
  AlertCircleIcon,
  ClockIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  XIcon,
  CheckIcon,
} from '@shopify/polaris-icons';
import type { Insight, SupportingMetric } from '../../types/insights';
import { getInsightTypeLabel, getSeverityTone } from '../../types/insights';
import { formatRelativeTime } from '../../utils/dateUtils';

interface InsightCardProps {
  insight: Insight;
  onDismiss?: (insightId: string) => void;
  onMarkRead?: (insightId: string) => void;
  onViewRecommendations?: (insightId: string) => void;
  isLoading?: boolean;
  showRecommendationsLink?: boolean;
}

/**
 * Format a metric value for display.
 */
function formatMetricValue(value: number | null, metric: string): string {
  if (value === null) return '-';

  // Check if this is a currency or percentage metric
  if (metric.toLowerCase().includes('spend') || metric.toLowerCase().includes('cost')) {
    return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  if (metric.toLowerCase().includes('rate') || metric.toLowerCase().includes('roas') || metric.toLowerCase().includes('ctr')) {
    return `${value.toFixed(2)}%`;
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/**
 * Format change percentage for display.
 */
function formatChange(change: number | null, changePct: number | null): string {
  if (changePct !== null) {
    const sign = changePct >= 0 ? '+' : '';
    return `${sign}${changePct.toFixed(1)}%`;
  }
  if (change !== null) {
    const sign = change >= 0 ? '+' : '';
    return `${sign}${change.toFixed(2)}`;
  }
  return '-';
}

/**
 * Get change tone based on metric type and direction.
 */
function getChangeTone(changePct: number | null, metric: string): 'success' | 'critical' | undefined {
  if (changePct === null) return undefined;

  // For cost metrics, increase is bad, decrease is good
  const isCostMetric = metric.toLowerCase().includes('spend') ||
                       metric.toLowerCase().includes('cost') ||
                       metric.toLowerCase().includes('cpc');

  if (isCostMetric) {
    return changePct > 0 ? 'critical' : 'success';
  }

  // For performance metrics, increase is good
  return changePct > 0 ? 'success' : 'critical';
}

/**
 * Single metric row component.
 */
function MetricRow({ metric }: { metric: SupportingMetric }) {
  const changeTone = getChangeTone(metric.change_pct, metric.metric);

  return (
    <InlineStack align="space-between" blockAlign="center">
      <Text as="span" variant="bodySm" tone="subdued">
        {metric.metric}
      </Text>
      <InlineStack gap="300" blockAlign="center">
        <Text as="span" variant="bodySm">
          {formatMetricValue(metric.previous, metric.metric)} → {formatMetricValue(metric.current, metric.metric)}
        </Text>
        <Badge tone={changeTone}>
          {formatChange(metric.change, metric.change_pct)}
        </Badge>
      </InlineStack>
    </InlineStack>
  );
}

export function InsightCard({
  insight,
  onDismiss,
  onMarkRead,
  onViewRecommendations,
  isLoading = false,
  showRecommendationsLink = true,
}: InsightCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const severityTone = getSeverityTone(insight.severity);
  const hasMetrics = insight.supporting_metrics && insight.supporting_metrics.length > 0;

  const handleDismiss = () => {
    if (onDismiss) {
      onDismiss(insight.insight_id);
    }
  };

  const handleMarkRead = () => {
    if (onMarkRead && !insight.is_read) {
      onMarkRead(insight.insight_id);
    }
  };

  return (
    <Card>
      <BlockStack gap="300">
        {/* Header */}
        <InlineStack align="space-between" blockAlign="start">
          <InlineStack gap="200" blockAlign="center">
            <Badge tone={severityTone}>
              {insight.severity.charAt(0).toUpperCase() + insight.severity.slice(1)}
            </Badge>
            <Badge tone="info">
              {getInsightTypeLabel(insight.insight_type)}
            </Badge>
            {insight.platform && (
              <Badge>
                {insight.platform.charAt(0).toUpperCase() + insight.platform.slice(1)}
              </Badge>
            )}
            {!insight.is_read && (
              <Badge tone="attention">New</Badge>
            )}
          </InlineStack>
          <InlineStack gap="100" blockAlign="center">
            <Icon source={ClockIcon} tone="subdued" />
            <Text as="span" variant="bodySm" tone="subdued">
              {formatRelativeTime(insight.generated_at)}
            </Text>
          </InlineStack>
        </InlineStack>

        {/* Summary */}
        <Text as="h3" variant="headingSm">
          {insight.summary}
        </Text>

        {/* Why it matters */}
        {insight.why_it_matters && (
          <Box paddingBlockStart="100">
            <InlineStack gap="100" blockAlign="start">
              <Icon source={AlertCircleIcon} tone="subdued" />
              <Text as="p" variant="bodySm" tone="subdued">
                {insight.why_it_matters}
              </Text>
            </InlineStack>
          </Box>
        )}

        {/* Supporting Metrics (Collapsible) */}
        {hasMetrics && (
          <>
            <Button
              variant="plain"
              onClick={() => setIsExpanded(!isExpanded)}
              icon={isExpanded ? ChevronUpIcon : ChevronDownIcon}
              disclosure={isExpanded ? 'up' : 'down'}
            >
              {isExpanded ? 'Hide metrics' : `View ${insight.supporting_metrics.length} metrics`}
            </Button>
            <Collapsible
              open={isExpanded}
              id={`metrics-${insight.insight_id}`}
              transition={{ duration: '200ms', timingFunction: 'ease-in-out' }}
            >
              <Box paddingBlockStart="200">
                <BlockStack gap="200">
                  {insight.supporting_metrics.map((metric, idx) => (
                    <MetricRow key={idx} metric={metric} />
                  ))}
                </BlockStack>
              </Box>
            </Collapsible>
          </>
        )}

        {/* Timeframe and Confidence */}
        <InlineStack gap="400">
          <Text as="span" variant="bodySm" tone="subdued">
            Timeframe: {insight.timeframe}
          </Text>
          <Text as="span" variant="bodySm" tone="subdued">
            Confidence: {Math.round(insight.confidence_score * 100)}%
          </Text>
        </InlineStack>

        <Divider />

        {/* Actions */}
        <InlineStack align="space-between">
          <InlineStack gap="200">
            {showRecommendationsLink && onViewRecommendations && (
              <Button
                variant="plain"
                onClick={() => onViewRecommendations(insight.insight_id)}
              >
                View recommendations
              </Button>
            )}
          </InlineStack>
          <InlineStack gap="200">
            {!insight.is_read && onMarkRead && (
              <Tooltip content="Mark as read">
                <Button
                  variant="plain"
                  icon={CheckIcon}
                  onClick={handleMarkRead}
                  loading={isLoading}
                  accessibilityLabel="Mark as read"
                />
              </Tooltip>
            )}
            {onDismiss && (
              <Tooltip content="Dismiss this insight">
                <Button
                  variant="plain"
                  icon={XIcon}
                  onClick={handleDismiss}
                  loading={isLoading}
                  accessibilityLabel="Dismiss insight"
                />
              </Tooltip>
            )}
          </InlineStack>
        </InlineStack>
      </BlockStack>
    </Card>
  );
}

export default InsightCard;
