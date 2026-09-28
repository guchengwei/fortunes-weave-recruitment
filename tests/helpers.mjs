import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
export const root = resolve(here, "..");

export function readModel() {
  const page = readFileSync(resolve(root, "dist/index.html"), "utf8");
  const match = page.match(/<script type="application\/json" id="planner-data">([\s\S]*?)<\/script>/);
  if (!match) throw new Error("planner data was not generated; run scripts/build.py first");
  return JSON.parse(match[1]);
}

export function readJson(path) {
  return JSON.parse(readFileSync(resolve(root, path), "utf8"));
}
