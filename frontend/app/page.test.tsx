import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import Home from "./page";

describe("Studio home page", () => {
  it("links to the project on GitHub instead of listing contact details", () => {
    const html = renderToStaticMarkup(<Home />);

    expect(html).toContain('href="https://github.com/Aperove/nicokara-studio"');
    expect(html).toContain("在 GitHub 上查看本项目");
    expect(html).not.toContain("qq：");
  });
});
