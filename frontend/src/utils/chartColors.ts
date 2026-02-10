/**
 * Chart color palette utility for dashboard chart rendering.
 *
 * Provides a consistent color scheme aligned with Shopify's design language
 * for use across all chart types (line, bar, area, pie, etc.).
 */

const CHART_PALETTE = [
  '#2E72D2', // Shopify blue
  '#00A47C', // Green
  '#FFC453', // Yellow
  '#E3516E', // Red
  '#9C6ADE', // Purple
  '#47C1BF', // Teal
  '#F49342', // Orange
  '#50B83C', // Light green
];

/**
 * Returns a color from the palette by index, cycling through if index exceeds palette length.
 *
 * @param index - The zero-based index of the data series or slice.
 * @param scheme - Optional color scheme name (reserved for future themed palettes).
 * @returns A hex color string from the palette.
 */
export function getColor(index: number, scheme?: string): string {
  void scheme; // Reserved for future color scheme support
  return CHART_PALETTE[index % CHART_PALETTE.length];
}

export { CHART_PALETTE };
