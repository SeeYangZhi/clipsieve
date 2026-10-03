import type { Post } from "@/lib/types";

const base = {
  collected_at: "2026-10-03T10:00:00Z",
  media: [],
  metrics: { comments: 10, likes: 100, views: 1000 },
};

export const fixturePosts: Post[] = [
  {
    ...base,
    comments: [{ likes: 12, text: "relatable!" }],
    creator_display: "Mei",
    creator_hash: "a1",
    id: "local:fx-001",
    kind: "video",
    lang: "en",
    platform: "local",
    raw_ref: "raw/local__fx-001.json",
    text: {
      caption:
        "Stop scrolling. I moved from Singapore to Shanghai with two suitcases.",
      hashtags: ["shanghai", "expat"],
      title: "First week in Shanghai",
    },
    url: "file:///fx/001.mp4",
  },
  {
    ...base,
    comments: [
      { likes: 40, text: "太真实了" },
      { likes: 8, text: "求租房攻略" },
    ],
    creator_display: "阿杰",
    creator_hash: "a2",
    id: "local:fx-002",
    kind: "video",
    lang: "zh",
    platform: "local",
    raw_ref: "raw/local__fx-002.json",
    text: {
      caption: "从新加坡搬到上海的第一周，租房踩了三个坑。",
      hashtags: ["上海生活", "新加坡人"],
      title: "新加坡人在上海的第一周",
    },
    url: "file:///fx/002.mp4",
  },
  {
    ...base,
    comments: [],
    creator_hash: "a3",
    id: "local:fx-003",
    kind: "video",
    lang: "zh",
    platform: "local",
    raw_ref: "raw/local__fx-003.json",
    text: {
      caption: "上海地铁早高峰 vlog｜一个新加坡人的日常",
      hashtags: ["vlog"],
    },
    url: "file:///fx/003.mp4",
  },
  {
    ...base,
    comments: [{ likes: 3, text: "saving this" }],
    creator_hash: "a4",
    id: "local:fx-004",
    kind: "image_note",
    lang: "en",
    platform: "local",
    raw_ref: "raw/local__fx-004.json",
    text: {
      caption: "7 things I wish I knew before signing.",
      hashtags: ["shanghai", "checklist"],
      title: "Shanghai apartment hunting checklist",
    },
    url: "file:///fx/004",
  },
  {
    ...base,
    comments: [{ likes: 5, text: "有用" }],
    creator_hash: "a5",
    id: "local:fx-005",
    kind: "image_note",
    lang: "zh",
    platform: "local",
    raw_ref: "raw/local__fx-005.json",
    text: {
      caption: "新加坡护照办卡需要的材料清单。",
      hashtags: ["上海", "攻略"],
      title: "在上海办银行卡全攻略",
    },
    url: "file:///fx/005",
  },
];
