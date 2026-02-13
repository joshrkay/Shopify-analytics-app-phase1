/**
 * Wizard Top Toolbar Component
 *
 * Sticky top toolbar for the wizard with:
 * - Inline-editable dashboard name
 * - Widget count badge (consolidated location)
 * - Save as Template and Save Dashboard buttons (Step 3 only)
 *
 * Phase 2.5 - Top Toolbar & Save as Template
 */

import { InlineStack, TextField, Badge, Button, Box } from '@shopify/polaris';
import type { BuilderStep } from '../../../types/customDashboards';

interface WizardTopToolbarProps {
  dashboardName: string;
  onDashboardNameChange: (value: string) => void;
  widgetCount: number;
  currentStep: BuilderStep;
  onSaveAsTemplate?: () => void;
  onSaveDashboard: () => void;
  canSave: boolean;
  isSaving: boolean;
}

export function WizardTopToolbar({
  dashboardName,
  onDashboardNameChange,
  widgetCount,
  currentStep,
  onSaveAsTemplate,
  onSaveDashboard,
  canSave,
  isSaving,
}: WizardTopToolbarProps) {
  const isPreviewStep = currentStep === 'preview';

  return (
    <div style={{ position: 'sticky', top: 0, zIndex: 400 }}>
    <Box
      background="bg-surface"
      padding="400"
      borderBlockEndWidth="025"
      borderColor="border"
    >
      <InlineStack align="space-between" blockAlign="center">
        {/* Left section: Dashboard name + widget count */}
        <InlineStack gap="400" blockAlign="center">
          <TextField
            label=""
            labelHidden
            value={dashboardName}
            onChange={onDashboardNameChange}
            placeholder="Untitled Dashboard"
            autoComplete="off"
            connectedLeft={
              <div style={{ padding: '0 var(--p-space-300)' }}>
                <Badge tone="info">{`${widgetCount} widgets selected`}</Badge>
              </div>
            }
          />
        </InlineStack>

        {/* Right section: Action buttons (Step 3 only) */}
        {isPreviewStep && (
          <InlineStack gap="200">
            {onSaveAsTemplate && (
              <Button
                variant="secondary"
                onClick={onSaveAsTemplate}
                disabled={isSaving}
              >
                Save as Template
              </Button>
            )}
            <Button
              variant="primary"
              onClick={onSaveDashboard}
              disabled={!canSave || isSaving}
              loading={isSaving}
            >
              Save Dashboard
            </Button>
          </InlineStack>
        )}
      </InlineStack>
    </Box>
    </div>
  );
}
