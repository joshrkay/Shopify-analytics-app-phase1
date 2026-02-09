/**
 * ChangelogEntry Component
 *
 * Displays a single changelog entry with version, title, summary, and actions.
 * Supports both compact (for banners) and full (for detail view) modes.
 *
 * Story 9.7 - In-App Changelog & Release Notes
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
  Link,
  Box,
} from '@shopify/polaris';
import {
  ChevronDownIcon,
  ChevronUpIcon,
  ExternalIcon,
} from '@shopify/polaris-icons';
import type { ChangelogEntry as ChangelogEntryType } from '../../types/changelog';
import {
  getReleaseTypeLabel,
  getReleaseTypeTone,
  formatChangelogDate,
  getFeatureAreaLabel,
} from '../../types/changelog';

interface ChangelogEntryProps {
  entry: ChangelogEntryType;
  onMarkRead?: (entryId: string) => void;
  isCompact?: boolean;
  isLoading?: boolean;
}

export function ChangelogEntry({
  entry,
  onMarkRead,
  isCompact = false,
  isLoading = false,
}: ChangelogEntryProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const handleToggleExpand = () => {
    setIsExpanded(!isExpanded);
    // Mark as read when expanding
    if (!isExpanded && !entry.is_read && onMarkRead) {
      onMarkRead(entry.id);
    }
  };

  const releaseTypeTone = getReleaseTypeTone(entry.release_type);

  // Compact mode for banners
  if (isCompact) {
    return (
      <Box paddingBlockEnd="200">
        <InlineStack gap="200" align="start" blockAlign="center">
          <Badge tone={releaseTypeTone}>
            {getReleaseTypeLabel(entry.release_type)}
          </Badge>
          <Text as="span" variant="bodyMd" fontWeight="semibold">
            {entry.title}
          </Text>
          {!entry.is_read && (
            <Badge tone="attention">New</Badge>
          )}
        </InlineStack>
        <Box paddingBlockStart="100">
          <Text as="p" variant="bodySm" tone="subdued">
            {entry.summary}
          </Text>
        </Box>
      </Box>
    );
  }

  // Full mode for detail view
  return (
    <Card>
      <BlockStack gap="300">
        {/* Header */}
        <InlineStack align="space-between" blockAlign="center">
          <InlineStack gap="200" blockAlign="center">
            <Badge tone={releaseTypeTone}>
              {getReleaseTypeLabel(entry.release_type)}
            </Badge>
            <Text as="span" variant="bodyMd" fontWeight="semibold">
              v{entry.version}
            </Text>
            {!entry.is_read && (
              <Badge tone="attention">New</Badge>
            )}
          </InlineStack>
          <Text as="span" variant="bodySm" tone="subdued">
            {formatChangelogDate(entry.published_at)}
          </Text>
        </InlineStack>

        {/* Title */}
        <Text as="h3" variant="headingMd">
          {entry.title}
        </Text>

        {/* Summary */}
        <Text as="p" variant="bodyMd">
          {entry.summary}
        </Text>

        {/* Feature areas */}
        {entry.feature_areas.length > 0 && (
          <InlineStack gap="100">
            {entry.feature_areas.map((area) => (
              <Badge key={area} tone="info">
                {getFeatureAreaLabel(area)}
              </Badge>
            ))}
          </InlineStack>
        )}

        {/* Content toggle (if content exists) */}
        {entry.content && (
          <>
            <Button
              variant="plain"
              onClick={handleToggleExpand}
              icon={isExpanded ? ChevronUpIcon : ChevronDownIcon}
              loading={isLoading}
            >
              {isExpanded ? 'Show less' : 'Read more'}
            </Button>

            <Collapsible
              open={isExpanded}
              id={`changelog-content-${entry.id}`}
              transition={{ duration: '200ms', timingFunction: 'ease-in-out' }}
            >
              <Box
                paddingBlockStart="300"
                paddingBlockEnd="300"
                paddingInlineStart="400"
                borderBlockStartWidth="025"
                borderColor="border"
              >
                <Text as="p" variant="bodyMd">
                  {/* Render content as paragraphs (simple markdown-like) */}
                  {entry.content.split('\n\n').map((paragraph, idx) => (
                    <Box key={idx} paddingBlockEnd="200">
                      <Text as="p" variant="bodyMd">
                        {paragraph}
                      </Text>
                    </Box>
                  ))}
                </Text>
              </Box>
            </Collapsible>
          </>
        )}

        {/* Documentation link */}
        {entry.documentation_url && (
          <InlineStack>
            <Link url={entry.documentation_url} target="_blank">
              <InlineStack gap="100" blockAlign="center">
                <Text as="span" variant="bodySm">
                  View documentation
                </Text>
                <ExternalIcon />
              </InlineStack>
            </Link>
          </InlineStack>
        )}
      </BlockStack>
    </Card>
  );
}

export default ChangelogEntry;
