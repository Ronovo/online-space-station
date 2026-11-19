import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['tests/js/**/*.test.js'],
    setupFiles: ['coverage-index/tools/vitest-tests-setup.mjs'],
    reporters: ['default', 'coverage-index/tools/vitest-tests-reporter.mjs'],
    coverage: {
      reportOnFailure: true,
      provider: 'istanbul',
      include: ['space_online/webapp/static/**/*.js'],
      reporter: ['text', 'html', 'json-summary'],
      reportsDirectory: 'coverage/js',
      thresholds: { 100: true },
    },
  },
});
