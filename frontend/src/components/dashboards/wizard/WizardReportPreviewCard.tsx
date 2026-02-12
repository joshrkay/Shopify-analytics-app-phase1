/**
 * Wizard Report Preview Card
 *
 * Displays a widget preview in the customize step grid with:
 * - Drag handle for repositioning
 * - Widget name, chart type, and size badge
 * - Hover-revealed actions: Settings, Maximize, Remove
 * - Touch device support
 * - Empty state with icon (no real data in customize step)
 *
 * Phase 2.4 - Enhanced with hover actions and size cycling
 */

import { useState } from 'react';
import { Card, BlockStack, InlineStack, Text, Button, Icon, Badge } from '@shopify/polaris';
import { SettingsIcon, MaximizeIcon, DeleteIcon } from '@shopify/polaris-icons';
import type { Report } from '../../../types/customDashboards';
import { getChartTypeLabel, COLUMNS_TO_SIZE } from '../../../types/customDashboards';
import { getChartIcon } from '../../../utils/chartIcons';
import { useDashboardBuilder } from '../../../contexts/DashboardBuilderContext';

interface WizardReportPreviewCardProps {
  widget: Report;
  onRemove: (reportId: string) => void;
}

export function WizardReportPreviewCard({ widget, onRemove }: WizardReportPreviewCardProps) {
  const [isHovered, setIsHovered] = useState(false);
  const { openWizardWidgetConfig, moveWizardWidget } = useDashboardBuilder();

  const ChartIcon = getChartIcon(widget.chart_type);

  // Get current size label
  const currentWidth = widget.position_json?.w || 6;
  const sizeLabel = COLUMNS_TO_SIZE[currentWidth as keyof typeof COLUMNS_TO_SIZE] || 'medium';

  // Handle maximize (cycle through sizes)
  const handleMaximize = () => {
    const widthMap = { 3: 6, 6: 9, 9: 12, 12: 3 }; // small → medium → large → full → small
    const newWidth = widthMap[currentWidth as keyof typeof widthMap] || 6;

    moveWizardWidget(widget.id, {
      ...widget.position_json,
      w: newWidth,
    });
  };

  // Handle settings
  const handleSettings = () => {
    openWizardWidgetConfig(widget.id);
  };

  // Touch device support
  const handleTouch = () => {
    setIsHovered(!isHovered);
  };

  return (
    <div
      style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onTouchStart={handleTouch}
    >
      <Card padding="300">
        <BlockStack gap="300">
          {/* Header with drag handle, name, and action buttons */}
          <InlineStack align="space-between" blockAlign="center">
            <InlineStack gap="200" blockAlign="center">
              <div
                className="wizard-report-drag-handle"
                style={{ cursor: 'grab', padding: '0 4px', fontSize: '16px', color: '#8c9196' }}
              >
                ::
              </div>
              <BlockStack gap="050">
                <Text as="h3" variant="headingSm" fontWeight="semibold">
                  {widget.name}
                </Text>
                <Text as="span" variant="bodySm" tone="subdued">
                  {getChartTypeLabel(widget.chart_type)}
                </Text>
              </BlockStack>
            </InlineStack>

            {/* Hover-revealed action buttons */}
            {isHovered && (
              <InlineStack gap="100">
                <Button
                  icon={SettingsIcon}
                  variant="plain"
                  size="slim"
                  onClick={handleSettings}
                  accessibilityLabel="Widget settings"
                />
                <Button
                  icon={MaximizeIcon}
                  variant="plain"
                  size="slim"
                  onClick={handleMaximize}
                  accessibilityLabel="Cycle widget size"
                />
                <Button
                  icon={DeleteIcon}
                  variant="plain"
                  tone="critical"
                  size="slim"
                  onClick={() => onRemove(widget.id)}
                  accessibilityLabel="Remove widget"
                />
              </InlineStack>
            )}
          </InlineStack>

          {/* Size badge (always visible) */}
          <Badge tone="info">{sizeLabel}</Badge>

          {/* Empty state with chart icon (no real data in customize step) */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: '120px',
              padding: '20px',
              backgroundColor: '#f6f6f7',
              borderRadius: '8px',
            }}
          >
            <div style={{ marginBottom: '8px' }}>
              <Icon source={ChartIcon} tone="subdued" />
            </div>
            <Text as="p" variant="bodySm" tone="subdued" alignment="center">
              {getChartTypeLabel(widget.chart_type)} preview
            </Text>
          </div>
        </BlockStack>
      </Card>
    </div>
  );
}
