import { afterEach, describe, expect, it, vi } from "vitest";
import { type ApiError, api, eventsUrl, mediaUrl } from "./api";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn(async () => ({
    json: async () => body,
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 404 ? "Not Found" : "OK",
  }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("posts a run body to /api/runs", async () => {
    const fn = mockFetch(200, { id: "r1", stage: "planning" });
    const run = await api.createRun({
      brief: "新加坡人搬到上海",
      platforms: ["local"],
      quantities: { local: 5 },
      rubric_pack: "creator-hooks-v1",
    });
    expect(run.id).toBe("r1");
    const [url, init] = fn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/runs");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body)).brief).toBe("新加坡人搬到上海");
  });

  it("throws ApiError with the server detail", async () => {
    mockFetch(404, { detail: "run not found" });
    await expect(api.getReport("nope")).rejects.toMatchObject<
      Partial<ApiError>
    >({
      detail: "run not found",
      status: 404,
    });
  });

  it("encodes post ids in media urls", () => {
    expect(mediaUrl("r1", "local:fx-001", "thumb.jpg")).toBe(
      "/api/runs/r1/media/local%3Afx-001/thumb.jpg"
    );
  });

  it("builds the events url with after", () => {
    expect(eventsUrl("r1", 42)).toBe("/api/runs/r1/events?after=42");
  });

  it("passes paging to getPosts", async () => {
    const fn = mockFetch(200, { items: [], total: 0 });
    await api.getPosts("r1", 100, 50);
    expect((fn.mock.calls[0] as unknown as [string])[0]).toBe(
      "/api/runs/r1/posts?offset=100&limit=50"
    );
  });
});
