/**
 * Connection Steps Component
 *
 * Visual step indicator for the connection wizard.
 * Shows current progress through the 5-step connection flow.
 *
 * Phase 3 — Subphase 3.5: Connection Wizard UI
 */

import { InlineStack, Badge, Text } from '@shopify/polaris';
import type { ConnectionStep } from '../../types/sourceConnection';

interface ConnectionStepsProps {
  currentStep: ConnectionStep;
}

const STEPS: Array<{ key: ConnectionStep; label: string; order: number }> = [
  { key: 'select', label: 'Select Platform', order: 1 },
  { key: 'configure', label: 'Configure', order: 2 },
  { key: 'authenticate', label: 'Authenticate', order: 3 },
  { key: 'test', label: 'Test Connection', order: 4 },
  { key: 'complete', label: 'Complete', order: 5 },
];

/**
 * Step indicator for connection wizard.
 *
 * Shows numbered badges with labels for each step.
 * Highlights current step, dims completed steps, grays out future steps.
 */
export function ConnectionSteps({ currentStep }: ConnectionStepsProps) {
  const currentOrder = STEPS.find((s) => s.key === currentStep)?.order ?? 1;

  return (
    <InlineStack gap="300" align="center" wrap={false}>
      {STEPS.map((step, index) => {
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
