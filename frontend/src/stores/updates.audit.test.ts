import { describe, expect, it } from "vitest";
import { effectiveVersion } from "@/stores/updates";

const hotpatch = (frontend_version: string | null, app_version = "9.9.9") => ({
  app_version,
  frontend_version,
  previous_version: null,
  channel: "nightly" as const,
});

describe("effectiveVersion (audit)", () => {
  it("counts an applied backend overlay so a backend-only nightly is not re-offered", () => {
    expect(
      effectiveVersion(hotpatch("9.9.9_001"), null, {
        overlay_version: "9.9.9_002",
        previous_version: null,
        overlay_active: true,
      }),
    ).toBe("9.9.9_002");
  });

  it("never reports an older frontend patch over a newer backend version", () => {
    expect(effectiveVersion(hotpatch("9.9.9_001", "9.9.9_004"))).toBe("9.9.9_004");
  });
});
