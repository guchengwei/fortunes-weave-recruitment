import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

test("build rejects protected and overlapping output destinations without modifying source", () => {
  const sourceBefore = readFileSync("src/app.js");
  const protectedResult = spawnSync("python3", [
    "scripts/build.py", "--out-dir", "src", "--offline-dir", "artifacts/offline",
  ], { encoding: "utf8" });
  assert.notEqual(protectedResult.status, 0);
  assert.match(protectedResult.stderr, /protected repository content/);
  assert.deepEqual(readFileSync("src/app.js"), sourceBefore);

  const overlapResult = spawnSync("python3", [
    "scripts/build.py", "--out-dir", "dist", "--offline-dir", "dist",
  ], { encoding: "utf8" });
  assert.notEqual(overlapResult.status, 0);
  assert.match(overlapResult.stderr, /must not overlap/);
  assert.deepEqual(readFileSync("src/app.js"), sourceBefore);
});


test("content navigation stays local and preserves queries and character anchors", () => {
  const result = spawnSync("python3", ["-c", `
import importlib.util, json
spec = importlib.util.spec_from_file_location("build", "scripts/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
base = build.BASE_URL
print(json.dumps([
    build.local_navigation('<a href="' + base + 'routes/cai.html">Guide</a>', 'index.html'),
    build.local_navigation('<a href="' + base + '?route=cai#allocation">Back</a>', 'routes/cai.html'),
    build.local_navigation('<a href="' + base + 'ja.html#character-cai">Cai</a>', 'ja/routes/cai.html'),
    build.local_navigation('<a href="' + base + 'routes/cai.html">Guide</a>', 'index.html', True),
]))
`], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), [
    '<a href="routes/cai.html">Guide</a>',
    '<a href="../index.html?route=cai#allocation">Back</a>',
    '<a href="../../ja.html#character-cai">Cai</a>',
    '<a href="#original">Guide</a>',
  ]);
});
