/**
 * TemplateCard Component
 *
 * Displays a single report template in the TemplateGallery grid.
 * Shows:
 * - Template name and description
 * - Category badge
 * - Required datasets list
 * - "Use Template" action button
 *
 * Phase 3 - Dashboard Builder UI
 */

import {
  Card,
  BlockStack,
  InlineStack,
  Text,
  Badge,
  Button,
  Box,
} from '@shopify/polaris';
import type { ReportTemplate } from '../../types/customDashboards';
import { getTemplateCategoryLabel } from '../../types/customDashboards';

interface TemplateCardProps {
  template: ReportTemplate;
  onUse: (id: string) => void;
}

function getCategoryTone(category: string): 'info' | 'success' | 'attention' | 'warning' | undefined {
  switch (category) {
    case 'sales':
      return 'success';
    case 'marketing':
      return 'info';
    case 'customer':
      return 'attention';
    case 'product':
      return 'warning';
    case 'operations':
      return undefined;
    default:
      return undefined;
  }
}

export function TemplateCard({ template, onUse }: TemplateCardProps) {
  return (
    <Card padding="400">
      <BlockStack gap="300">
        {/* Category badge */}
        <InlineStack align="start">
          <Badge tone={getCategoryTone(template.category)}>
            {getTemplateCategoryLabel(template.category)}
          </Badge>
        </InlineStack>

        {/* Name and description */}
        <BlockStack gap="100">
          <Text as="h3" variant="headingSm">
            {template.name}
          </Text>
          <Text as="p" variant="bodySm" tone="subdued">
            {template.description}
          </Text>
        </BlockStack>

        {/* Required datasets */}
        {template.required_datasets.length > 0 && (
          <BlockStack gap="100">
            <Text as="p" variant="bodySm" fontWeight="semibold">
              Required datasets:
            </Text>
            <Text as="p" variant="bodySm" tone="subdued">
              {template.required_datasets.join(', ')}
            </Text>
          </BlockStack>
        )}

        {/* Reports count */}
        <Text as="p" variant="bodySm" tone="subdued">
          {template.reports_json.length} report{template.reports_json.length !== 1 ? 's' : ''}
        </Text>

        {/* Action */}
        <Box paddingBlockStart="100">
          <Button
            variant="primary"
            onClick={() => onUse(template.id)}
            fullWidth
          >
            Use template
          </Button>
        </Box>
      </BlockStack>
    </Card>
  );
}
