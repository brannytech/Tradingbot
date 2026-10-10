import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './tests', testMatch: 'e2e.spec.mjs', workers: 1,
  reporter: [['list'],['json',{outputFile:'reports/playwright.json'}]],
  use: { baseURL: 'http://127.0.0.1:8767', screenshot: 'only-on-failure' },
  projects: [{name:'desktop',use:{...devices['Desktop Chrome']}},{name:'mobile',use:{...devices['iPhone 13'],defaultBrowserType:'chromium'}}],
  webServer: { command: 'python scripts/e2e_server.py',url:'http://127.0.0.1:8767/health',reuseExistingServer:false,timeout:60000 }
});
