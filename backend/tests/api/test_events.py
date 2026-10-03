import json

from clipsieve.store.paths import RunPaths
from tests.api.conftest import wait_for_plan, wait_for_stage

BODY = {
    "brief": "新加坡人搬到上海的 vlog",
    "platforms": ["local"],
    "quantities": {"local": 5},
    "rubric_pack": "creator-hooks-v1",
}


async def read_sse(client, url, headers=None, raw=None):
    events = []
    async with client.stream("GET", url, headers=headers) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        cur = {}
        async for line in resp.aiter_lines():
            if raw is not None:
                raw.append(line)
            if line.startswith("id:"):
                cur["id"] = int(line[3:].strip())
            elif line.startswith("event:"):
                cur["event"] = line[6:].strip()
            elif line.startswith("data:"):
                cur["data"] = json.loads(line[5:].strip())
            elif line == "" and cur:
                events.append(cur)
                cur = {}
    return events


async def approved_run(client):
    run_id = (await client.post("/api/runs", json=BODY)).json()["id"]
    await wait_for_plan(client, run_id)
    await client.post(f"/api/runs/{run_id}/approve")
    return run_id


async def test_stream_from_start_ends_at_done(client):
    run_id = await approved_run(client)
    events = await read_sse(client, f"/api/runs/{run_id}/events")
    seqs = [e["id"] for e in events]
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))  # contiguous
    assert all(e["event"] == "run_event" for e in events)
    assert events[0]["data"]["type"] == "run_created"
    assert [e["data"]["type"] for e in events].count("run_created") == 1  # the Runner's only
    assert events[-1]["data"]["type"] == "done"


async def test_sse_after_returns_exact_tail(client):
    run_id = await approved_run(client)
    await wait_for_stage(client, run_id, "done")
    full = await read_sse(client, f"/api/runs/{run_id}/events")
    cut = full[len(full) // 2]["id"]
    tail = await read_sse(client, f"/api/runs/{run_id}/events?after={cut}")
    assert [e["id"] for e in tail] == [e["id"] for e in full if e["id"] > cut]
    assert tail[-1]["data"]["type"] == "done"
    assert await read_sse(client, f"/api/runs/{run_id}/events?after={full[-1]['id']}") == []


async def test_chinese_caption_roundtrip(client):
    run_id = await approved_run(client)
    events = await read_sse(client, f"/api/runs/{run_id}/events")
    collected = [e["data"] for e in events if e["data"]["type"] == "post_collected"]
    zh = [
        p
        for p in collected
        if any("一" <= ch <= "鿿" for ch in (p["payload"]["post"]["text"].get("caption") or ""))
    ]
    assert zh, "fixtures must include a Chinese caption"
    post_id = zh[0]["payload"]["post"]["id"]
    caption_sse = zh[0]["payload"]["post"]["text"]["caption"]
    page = (await client.get(f"/api/runs/{run_id}/posts?limit=100")).json()
    caption_api = next(
        i["post"]["text"]["caption"] for i in page["items"] if i["post"]["id"] == post_id
    )
    assert caption_api == caption_sse
    run_brief = (await client.get(f"/api/runs/{run_id}")).json()["run"]["brief"]["text"]
    assert run_brief == BODY["brief"]


# ---- contract details beyond the brief ------------------------------------------------------


async def test_finished_run_replays_jsonl_lines_byte_for_byte(client, ctx):
    """D.6 replay from seq 1, and RF4: each SSE data line is the events.jsonl line verbatim."""
    run_id = await approved_run(client)
    await wait_for_stage(client, run_id, "done")
    raw: list[str] = []
    events = await read_sse(client, f"/api/runs/{run_id}/events", raw=raw)
    assert events[0]["id"] == 1
    data_lines = [line[len("data: ") :] for line in raw if line.startswith("data: ")]
    jsonl = RunPaths(ctx.settings.clipsieve_data_dir, run_id).events_jsonl.read_bytes()
    assert [d.encode("utf-8") for d in data_lines] == jsonl.splitlines()
    assert "押一付三" in "".join(data_lines)  # CJK literal on the wire, not \u escapes


async def test_last_event_id_header_resumes_exactly(client):
    run_id = await approved_run(client)
    await wait_for_stage(client, run_id, "done")
    full = await read_sse(client, f"/api/runs/{run_id}/events")
    cut = full[3]["id"]
    tail = await read_sse(
        client, f"/api/runs/{run_id}/events?after=0", headers={"Last-Event-ID": str(cut)}
    )
    assert [e["id"] for e in tail] == [e["id"] for e in full if e["id"] > cut]


async def test_events_for_unknown_run_is_404(client):
    assert (await client.get("/api/runs/run_nope/events")).status_code == 404
