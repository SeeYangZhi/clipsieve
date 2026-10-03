import { describe, expect, it } from "vitest";
import { detectLocale, t, tOr } from "./i18n";
import { en } from "./i18n/en";
import { zh } from "./i18n/zh";

describe("t", () => {
  it("returns the zh string when present", () => {
    expect(t("brief.submit", "zh")).toBe("开始研究");
  });
  it("falls back to en when zh lacks a key", () => {
    expect(t("__only_en_test__", "zh")).toBe("__only_en_test__");
  });
  it("interpolates variables", () => {
    expect(t("grid.progress", "en", { done: 3, total: 10 })).toBe("3 / 10");
  });
  it("leaves unknown placeholders visible", () => {
    expect(t("grid.progress", "en", { done: 3 })).toBe("3 / {total}");
  });
  it("tOr returns fallback for an unknown key", () => {
    expect(tOr("label.not_a_label", "not_a_label", "en")).toBe("not_a_label");
  });
});

describe("dictionaries", () => {
  it("zh has every en key", () => {
    const missing = Object.keys(en).filter((k) => !(k in zh));
    expect(missing).toEqual([]);
  });
  it("en has every zh key", () => {
    const missing = Object.keys(zh).filter((k) => !(k in en));
    expect(missing).toEqual([]);
  });
});

describe("detectLocale", () => {
  it("maps zh-CN to zh and everything else to en", () => {
    expect(detectLocale("zh-CN")).toBe("zh");
    expect(detectLocale("zh-Hans-SG")).toBe("zh");
    expect(detectLocale("en-SG")).toBe("en");
    expect(detectLocale(undefined)).toBe("en");
  });
});
