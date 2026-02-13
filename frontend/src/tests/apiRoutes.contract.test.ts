import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.resolve(__dirname, '..');

function read(relativePath: string): string {
  return fs.readFileSync(path.join(repoRoot, relativePath), 'utf8');
}

describe('frontend API route contract', () => {
  it('does not reference deprecated dataset preview v1 endpoint', () => {
    const files = [
      'services/datasetsApi.ts',
      'services/reportDataApi.ts',
      'services/widgetCatalogApi.ts',
      'tests/reportDataApi.integration.test.ts',
      'tests/useWidgetCatalog.integration.test.ts',
      'tests/widgetCatalogBackend.integration.test.ts',
    ];

    for (const file of files) {
      const content = read(file);
      expect(content.includes('/api/v1/datasets/preview'), `${file} contains deprecated endpoint`).toBe(false);
    }
  });

  it('centralizes canonical templates and preview routes in API_ROUTES', () => {
    const apiRoutes = read('services/apiRoutes.ts');
    expect(apiRoutes).toContain("templates: '/api/v1/templates'");
    expect(apiRoutes).toContain("datasetsPreview: '/api/datasets/preview'");

    const datasetsApi = read('services/datasetsApi.ts');
    const reportDataApi = read('services/reportDataApi.ts');
    const templatesApi = read('services/templatesApi.ts');

    expect(datasetsApi).toContain('API_ROUTES.datasetsPreview');
    expect(reportDataApi).toContain('API_ROUTES.datasetsPreview');
    expect(templatesApi).toContain('API_ROUTES.templates');
  });
});
