import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

const dataDir = mkdtempSync(join(tmpdir(), "clipsieve-e2e-"));

export default defineConfig({
  expect: { timeout: 15_000 },
  retries: process.env.CI ? 1 : 0,
  testDir: "./e2e",
  timeout: 90_000,
  use: { baseURL: "http://localhost:3000", trace: "retain-on-failure" },
  webServer: [
    {
      command: "uv run uvicorn clipsieve.app:app --port 8000",
      cwd: "../backend",
      // fake mode defaults CLIPSIEVE_FIXTURE_DIR to backend/tests/fixtures; no other env needed
      env: {
        CLIPSIEVE_DATA_DIR: dataDir,
        CLIPSIEVE_EXPLAIN_BACKEND: "fake",
        TYPESAFE_API_KEY: "",
      },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      url: "http://localhost:8000/api/rubrics",
    },
    {
      command: "bun run dev",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      url: "http://localhost:3000",
    },
  ],
});
