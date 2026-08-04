import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("Studio development server", () => {
  it("proxies API uploads to the local backend before the worker handles them", () => {
    const config = readFileSync(
      new URL("../vite.config.ts", import.meta.url),
      "utf8",
    );

    expect(config).toContain('"/api"');
    expect(config).toContain("NICOKARA_DEV_API_ORIGIN");
    expect(config).toContain("http://127.0.0.1:8100");
    expect(config.indexOf('"/api"')).toBeLessThan(
      config.indexOf("cloudflare({"),
    );
  });

  it("keeps Studio ports separate from the Cloud development stack", () => {
    const compose = readFileSync(
      new URL("../../docker-compose.yml", import.meta.url),
      "utf8",
    );
    const exampleEnvironment = readFileSync(
      new URL("../../.env.example", import.meta.url),
      "utf8",
    );

    expect(compose).toContain('"8100:8000"');
    expect(compose).toContain('"3200:3000"');
    expect(compose).toContain("http://localhost:8100/api/v1");
    expect(exampleEnvironment).toContain(
      "NICOKARA_MAX_UPLOADS_PER_HOUR=0",
    );
    expect(exampleEnvironment).toContain(
      "NEXT_PUBLIC_API_URL=http://localhost:8100/api/v1",
    );
  });
});
