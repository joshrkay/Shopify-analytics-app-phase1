/**
 * Wizard Steps Component
 *
 * Visual step indicator for the 6-step connect source wizard.
 * Shows current progress with active/completed/future styling.
 *
 * Follows the same pattern as ConnectionSteps.tsx.
 *
 * Phase 3 — Subphase 3.4: Connection Wizard
 */

import { InlineStack, Badge, Text } from '@shopify/polaris';
import type { WizardStep, WizardStepMeta } from '../../types/sourceConnection';

interface WizardStepsProps {
  currentStep: WizardStep;
}

const WIZARD_STEPS: WizardStepMeta[] = [
  { key: 'intro', label: 'Intro', order: 1 },
  { key: 'oauth', label: 'Authorize', order: 2 },
  { key: 'accounts', label: 'Accounts', order: 3 },
  { key: 'syncConfig', label: 'Configure', order: 4 },
  { key: 'syncing', label: 'Syncing', order: 5 },
  { key: 'success', label: 'Done', order: 6 },
];

export function WizardSteps({ currentStep }: WizardStepsProps) {
  const currentOrder = WIZARD_STEPS.find((s) => s.key === currentStep)?.order ?? 1;

  return (
    <InlineStack gap="300" align="center" wrap={false}>
      {WIZARD_STEPS.map((step, index) => {
        const isActive = step.key === currentStep;
        const isCompleted = step.order < currentOrder;
        const isFuture = step.order > currentOrder;

        return (
          <InlineStack key={step.key} gap="200" blockAlign="center" wrap={false}>
            {index > 0 && (
              <Text as="span" tone="subdued">
                →
              </Text>
            )}
            <InlineStack gap="100" blockAlign="center">
              <Badge tone={isActive ? 'info' : isCompleted ? 'success' : undefined}>
                {String(step.order)}
              </Badge>
              <Text
                as="span"
                variant="bodySm"
                fontWeight={isActive ? 'semibold' : 'regular'}
                tone={isFuture ? 'subdued' : undefined}
              >
                {step.label}
              </Text>
            </InlineStack>
          </InlineStack>
        );
      })}
    </InlineStack>
  );
}
