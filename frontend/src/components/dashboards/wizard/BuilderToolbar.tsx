/**
 * Builder Toolbar Component
 *
 * Bottom navigation toolbar for the wizard with Back/Next/Save buttons.
 *
 * Phase 3 - Dashboard Builder Wizard UI
 */

import { Box, InlineStack, Button } from '@shopify/polaris';
import type { BuilderStep } from '../../../types/customDashboards';

interface BuilderToolbarProps {
  currentStep: BuilderStep;
  onBack: () => void;
  onNext: () => void;
  onSave: () => void;
  onCancel: () => void;
  canGoBack: boolean;
  canProceed: boolean;
  canSave: boolean;
  isSaving: boolean;
}

export function BuilderToolbar({
  currentStep,
  onBack,
  onNext,
  onSave,
  onCancel,
  canGoBack,
  canProceed,
  canSave,
  isSaving,
}: BuilderToolbarProps) {
  const isPreviewStep = currentStep === 'preview';

  return (
    <Box background="bg-surface" padding="400">
      <InlineStack align="space-between">
        {/* Cancel button */}
        <Button variant="plain" onClick={onCancel}>
          Cancel
        </Button>

        {/* Navigation buttons */}
        <InlineStack gap="200">
          {/* Back button */}
          <Button onClick={onBack} disabled={!canGoBack}>
            Back
          </Button>

          {/* Next or Save button */}
          {isPreviewStep ? (
            <Button
              variant="primary"
              onClick={onSave}
              disabled={!canSave || isSaving}
              loading={isSaving}
            >
              Save Dashboard
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={onNext}
              disabled={!canProceed}
            >
              Next
            </Button>
          )}
        </InlineStack>
      </InlineStack>
    </Box>
  );
}
