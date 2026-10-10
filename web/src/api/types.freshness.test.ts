import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// spec §8: the UI's API types are generated from the server's OpenAPI schema and must not go stale
test("src/api/types.ts matches docs/api/openapi.json", () => {
  const out = join(mkdtempSync(join(tmpdir(), "dw-types-")), "types.ts");
  execFileSync(process.execPath, ["node_modules/openapi-typescript/bin/cli.js", "../docs/api/openapi.json", "-o", out], {
    stdio: "pipe",
  });
  const fresh = readFileSync(out, "utf8");
  const committed = readFileSync("src/api/types.ts", "utf8");
  expect(committed, "run: npm run gen:api").toBe(fresh);
}, 30_000); // spawns node: slower than the 5 s default on Windows
