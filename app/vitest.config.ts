import { defineConfig } from 'vitest/config'

// Node-env unit tests for the renderer's pure modules (lib/api, lib/jobs, lib/selection).
// No jsdom: these modules use only fetch (mocked) and plain data, so node keeps the
// suite fast and dependency-light.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/renderer/src/**/*.test.ts'],
    globals: true
  }
})
