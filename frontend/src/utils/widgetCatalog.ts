/**
 * Widget Catalog Utilities
 *
 * Extracts individual report configs from ReportTemplates as WidgetCatalogItems
 * for use in the dashboard builder wizard.
 *
 * Phase 3 - Dashboard Builder Wizard State Management
 */

import type { ReportTemplate, WidgetCatalogItem, WidgetSize } from '../types/customDashboards';
import { mapChartTypeToWidgetCategory } from '../types/customDashboards';
import { listTemplates } from '../services/templatesApi';

/**
 * Extracts individual reports from a template as catalog items
 *
 * Each report in the template's reports_json array becomes a selectable
 * widget in the wizard gallery.
 *
 * @param template - The ReportTemplate to extract widgets from
 * @returns Array of WidgetCatalogItems
 */
export function extractWidgetCatalogItems(
  template: ReportTemplate,
): WidgetCatalogItem[] {
  return template.reports_json.map((report: any, index: number) => {
    const chartType = report.chart_type;
    const defaultSize: WidgetSize = chartType === 'kpi'
      ? 'small'
      : chartType === 'table'
        ? 'full'
        : 'medium';

    const name = report.name || `Widget ${index + 1}`;

    return {
      id: `${template.id}-report-${index}`,
      templateId: template.id,
      name,
      title: name,
      description: report.description || template.description,
      category: chartType,
      businessCategory: mapChartTypeToWidgetCategory(chartType),
      chart_type: chartType,
      thumbnail_url: template.thumbnail_url ?? undefined,
      default_config: report.config_json,
      required_dataset: report.dataset_name,
      defaultSize,
    };
  });
}

/**
 * Fetches all templates and extracts all widget catalog items
 *
 * This is the main entry point for populating the widget gallery in the wizard.
 * It fetches all active templates and flattens their reports into a single
 * catalog of selectable widgets.
 *
 * @returns Promise resolving to array of all available WidgetCatalogItems
 */
export async function fetchWidgetCatalog(): Promise<WidgetCatalogItem[]> {
  const response = await listTemplates();
  return response.templates.flatMap(extractWidgetCatalogItems);
}
