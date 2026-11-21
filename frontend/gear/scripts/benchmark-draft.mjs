// Read a private benchmark payload from stdin and emit the browser's wire request.
import { readFileSync } from "node:fs";
import { createServer } from "vite";

const server = await createServer({
  configFile: false,
  logLevel: "silent",
  server: { middlewareMode: true, hmr: false },
});
try {
  const { draft, context } = JSON.parse(readFileSync(0, "utf8"));
  const { normalize } = await server.ssrLoadModule("/src/state/scenario.ts");
  const { optimizationRequest } = await server.ssrLoadModule(
    "/src/api/optimizationRequest.ts",
  );
  const scenario = normalize(draft, context.snapshotId, true, context);
  process.stdout.write(JSON.stringify(optimizationRequest(scenario)));
} finally {
  await server.close();
}
