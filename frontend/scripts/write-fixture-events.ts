import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { buildFixtureEvents } from "../src/lib/__fixtures__/run-events";

const out = fileURLToPath(
  new URL("../src/lib/__fixtures__/run-events.json", import.meta.url)
);
writeFileSync(out, `${JSON.stringify(buildFixtureEvents(), null, 2)}\n`);
// Biome collapses short arrays; format so the committed file passes `ultracite check`.
execFileSync("bunx", ["biome", "format", "--write", out], {
  stdio: ["ignore", "ignore", "inherit"],
});
console.log("wrote run-events.json");
