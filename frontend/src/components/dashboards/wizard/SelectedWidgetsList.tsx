import { BlockStack, Button, InlineStack, Text } from '@shopify/polaris';
import { XIcon } from '@shopify/polaris-icons';
import type { Report } from '../../../types/customDashboards';

interface SelectedWidgetsListProps {
  selectedWidgets: Report[];
  onRemoveWidget?: (reportId: string) => void;
  onContinueToLayout?: () => void;
}

export function SelectedWidgetsList({
  selectedWidgets,
  onRemoveWidget,
  onContinueToLayout,
}: SelectedWidgetsListProps) {
  if (selectedWidgets.length === 0) {
    return null;
  }

  return (
    <BlockStack gap="300">
      <Text as="p" variant="headingSm" fontWeight="semibold">
        Selected widgets
      </Text>

      <BlockStack gap="200">
        {selectedWidgets.map((widget, index) => {
          const widgetName = widget.name?.trim() || 'Untitled widget';

          return (
            <InlineStack key={`${widget.id}-${index}`} align="space-between" blockAlign="center">
              <Text as="span" variant="bodySm" truncate tone="subdued">
                {widgetName}
              </Text>
              {onRemoveWidget && (
                <Button
                  icon={XIcon}
                  size="slim"
                  variant="plain"
                  onClick={() => onRemoveWidget(widget.id)}
                  accessibilityLabel={`Remove ${widgetName}`}
                />
              )}
            </InlineStack>
          );
        })}
      </BlockStack>

      {onContinueToLayout && (
        <Button variant="primary" fullWidth onClick={onContinueToLayout}>
          Continue to Layout →
        </Button>
      )}
    </BlockStack>
  );
}
