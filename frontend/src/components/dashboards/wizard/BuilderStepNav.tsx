/**
 * Builder Step Nav Component
 *
 * Visual step indicator showing progress through the wizard:
 * 1. Select Widgets → 2. Customize Layout → 3. Preview & Save
 *
 * Phase 3 - Dashboard Builder Wizard UI
 */

import { InlineStack, Badge, Text } from '@shopify/polaris';
import type { BuilderStep } from '../../../types/customDashboards';

interface BuilderStepNavProps {
  currentStep: BuilderStep;
  completedSteps: Set<BuilderStep>;
  onChangeStep: (step: BuilderStep) => void;
  canProceedToCustomize: boolean;
  canProceedToPreview: boolean;
}

const STEPS: Array<{ step: BuilderStep; label: string; number: number }> = [
  { step: 'select', label: 'Select Widgets', number: 1 },
  { step: 'customize', label: 'Customize Layout', number: 2 },
  { step: 'preview', label: 'Preview & Save', number: 3 },
];

export function BuilderStepNav({
  currentStep,
  completedSteps,
  onChangeStep,
  canProceedToCustomize,
  canProceedToPreview,
}: BuilderStepNavProps) {
  const isStepClickable = (step: BuilderStep): boolean => {
    // Always allow going back to select
    if (step === 'select') return true;

    // Current or completed steps are always clickable
    if (step === currentStep || completedSteps.has(step)) return true;

    // Can only proceed to customize if validation passes AND we're on select step
    if (step === 'customize') {
      return canProceedToCustomize && currentStep === 'select';
    }

    // Can only proceed to preview if validation passes AND we're on customize step AND customize is completed
    if (step === 'preview') {
      return canProceedToPreview && currentStep === 'customize' && completedSteps.has('customize');
    }

    return false;
  };

  const getBadgeTone = (step: BuilderStep): 'success' | 'info' | undefined => {
    if (completedSteps.has(step)) return 'success';
    if (step === currentStep) return 'info';
    return undefined;
  };

  return (
    <InlineStack gap="400" align="center">
      {STEPS.map((stepInfo, index) => {
        const isClickable = isStepClickable(stepInfo.step);
        const badgeTone = getBadgeTone(stepInfo.step);
        const isActive = stepInfo.step === currentStep;

        const content = (
          <InlineStack gap="200" blockAlign="center">
            <Badge tone={badgeTone}>{String(stepInfo.number)}</Badge>
            <Text
              as="span"
              variant="bodyMd"
              fontWeight={isActive ? 'semibold' : 'regular'}
            >
              {stepInfo.label}
            </Text>
          </InlineStack>
        );

        return (
          <InlineStack key={stepInfo.step} gap="200" align="center">
            {isClickable ? (
              <div onClick={() => onChangeStep(stepInfo.step)} style={{ cursor: 'pointer' }}>
                {content}
              </div>
            ) : (
              <div style={{ opacity: 0.5 }}>
                {content}
              </div>
            )}

            {/* Connector between steps */}
            {index < STEPS.length - 1 && (
              <Text as="span" tone="subdued">
                →
              </Text>
            )}
          </InlineStack>
        );
      })}
    </InlineStack>
  );
}
