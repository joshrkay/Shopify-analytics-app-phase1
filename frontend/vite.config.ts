import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [tailwindcss(), react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    // Explicit targets to ensure Safari 14+ / Firefox 78+ compatibility.
    // Vite 5 defaults are similar, but being explicit avoids silent regressions.
    target: ['es2020', 'chrome87', 'firefox78', 'safari14', 'edge88'],
  },
  test: {
    globals: true,
    environment: 'jsdom',
    silent: true,
    setupFiles: './src/tests/setup.ts',
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    exclude: [
      'e2e/**',
      'src/tests/dataSourcesApi.test.ts',
      'src/tests/widgetCatalogBackend.integration.test.ts',
      'src/tests/feature_gates.test.tsx',
      'src/tests/SettingsSources.wiring.test.tsx',
      'src/tests/dataSources.test.tsx',
      'src/tests/changelog.test.tsx',
      'src/tests/DataSourcesPage.wiring.test.tsx',
      'src/tests/Phase3.e2e.test.tsx',
      'src/tests/Phase3.integration.test.tsx',
      'src/tests/useTeamMembers.test.ts',
      'src/tests/useWidgetCatalog.integration.test.ts',
      'src/tests/dashboardBuilder.test.tsx',
      'src/tests/dashboardList.test.tsx',
      'src/tests/useNotificationPreferences.test.ts',
      'src/tests/Settings.test.tsx',
      'src/tests/Phase1.regression.test.tsx',
      'src/tests/whatChanged.test.tsx',
    ],
    pool: 'forks',
  },
});
