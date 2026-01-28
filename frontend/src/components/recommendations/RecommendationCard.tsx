/**
 * RecommendationCard Component
 *
 * Displays a single AI recommendation with priority, impact, and risk info.
 * Supports accept and dismiss functionality.
 *
 * Story 9.3 - Insight & Recommendation UX
 */

import {
  Card,
  BlockStack,
  InlineStack,
  Text,
  Badge,
  Button,
  Box,
  Divider,
  Icon,
  Tooltip,
  Banner,
} from '@shopify/polaris';
import {
  AlertTriangleIcon,
  CheckIcon,
  XIcon,
  InfoIcon,
} from '@shopify/polaris-icons';
import type { Recommendation } from '../../types/recommendations';
import {
  getRecommendationTypeLabel,
  getPriorityTone,
  getRiskTone,
} from '../../types/recommendations';

interface RecommendationCardProps {
  recommendation: Recommendation;
  onAccept?: (recommendationId: string) => void;
  onDismiss?: (recommendationId: string) => void;
  isLoading?: boolean;
  /**
   * Show compact view without some details.
   */
  compact?: boolean;
}

/**
 * Get impact label with proper capitalization.
 */
function getImpactLabel(impact: string): string {
  return impact.charAt(0).toUpperCase() + impact.slice(1);
}

/**
 * Get risk label with proper capitalization.
 */
function getRiskLabel(risk: string): string {
  return risk.charAt(0).toUpperCase() + risk.slice(1);
}

/**
 * Get priority label with proper capitalization.
 */
function getPriorityLabel(priority: string): string {
  return priority.charAt(0).toUpperCase() + priority.slice(1);
}

export function RecommendationCard({
  recommendation,
  onAccept,
  onDismiss,
  isLoading = false,
  compact = false,
}: RecommendationCardProps) {
  const handleAccept = () => {
    if (onAccept) {
      onAccept(recommendation.recommendation_id);
    }
  };

  const handleDismiss = () => {
    if (onDismiss) {
      onDismiss(recommendation.recommendation_id);
    }
  };

  const isActioned = recommendation.is_accepted || recommendation.is_dismissed;

  return (
    <Card>
      <BlockStack gap="300">
        {/* Header with badges */}
        <InlineStack align="space-between" blockAlign="start">
          <InlineStack gap="200" blockAlign="center">
            <Badge tone={getPriorityTone(recommendation.priority)}>
              {`${getPriorityLabel(recommendation.priority)} Priority`}
            </Badge>
            <Badge tone="info">
              {getRecommendationTypeLabel(recommendation.recommendation_type)}
            </Badge>
            {recommendation.is_accepted && (
              <Badge tone="success">Accepted</Badge>
            )}
            {recommendation.is_dismissed && (
              <Badge>Dismissed</Badge>
            )}
          </InlineStack>
        </InlineStack>

        {/* Recommendation text (uses conditional language) */}
        <Text as="h3" variant="headingSm">
          {recommendation.recommendation_text}
        </Text>

        {/* Rationale */}
        {recommendation.rationale && !compact && (
          <Box paddingBlockStart="100">
            <InlineStack gap="100" blockAlign="start">
              <Icon source={InfoIcon} tone="subdued" />
              <Text as="p" variant="bodySm" tone="subdued">
                {recommendation.rationale}
              </Text>
            </InlineStack>
          </Box>
        )}

        {/* Impact and Risk summary */}
        <InlineStack gap="400">
          <InlineStack gap="100" blockAlign="center">
            <Text as="span" variant="bodySm" tone="subdued">
              Expected Impact:
            </Text>
            <Badge
              tone={
                recommendation.estimated_impact === 'significant'
                  ? 'success'
                  : recommendation.estimated_impact === 'moderate'
                  ? 'warning'
                  : 'info'
              }
            >
              {getImpactLabel(recommendation.estimated_impact)}
            </Badge>
          </InlineStack>
          <InlineStack gap="100" blockAlign="center">
            <Text as="span" variant="bodySm" tone="subdued">
              Risk:
            </Text>
            <Badge tone={getRiskTone(recommendation.risk_level)}>
              {getRiskLabel(recommendation.risk_level)}
            </Badge>
          </InlineStack>
        </InlineStack>

        {/* Risk warning for high risk recommendations */}
        {recommendation.risk_level === 'high' && !compact && (
          <Banner tone="warning" icon={AlertTriangleIcon}>
            <Text as="p" variant="bodySm">
              This recommendation has a high risk level. Consider carefully before taking action.
            </Text>
          </Banner>
        )}

        {/* Affected entity */}
        {recommendation.affected_entity && !compact && (
          <Text as="p" variant="bodySm" tone="subdued">
            Affects: {recommendation.affected_entity}
            {recommendation.affected_entity_type && ` (${recommendation.affected_entity_type})`}
          </Text>
        )}

        {/* Confidence */}
        {!compact && (
          <Text as="span" variant="bodySm" tone="subdued">
            Confidence: {Math.round(recommendation.confidence_score * 100)}%
          </Text>
        )}

        {/* Actions */}
        {!isActioned && (onAccept || onDismiss) && (
          <>
            <Divider />
            <InlineStack align="end" gap="200">
              {onDismiss && (
                <Tooltip content="Dismiss this recommendation">
                  <Button
                    variant="plain"
                    icon={XIcon}
                    onClick={handleDismiss}
                    loading={isLoading}
                    accessibilityLabel="Dismiss recommendation"
                  >
                    Dismiss
                  </Button>
                </Tooltip>
              )}
              {onAccept && (
                <Tooltip content="Mark as accepted (advisory only)">
                  <Button
                    variant="primary"
                    icon={CheckIcon}
                    onClick={handleAccept}
                    loading={isLoading}
                  >
                    Accept
                  </Button>
                </Tooltip>
              )}
            </InlineStack>
          </>
        )}
      </BlockStack>
    </Card>
  );
}

export default RecommendationCard;
