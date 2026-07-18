/**
 * Packaging integration test. Runs `npm pack` for real and installs the
 * resulting tarball into a fresh temporary directory, then invokes the
 * actual installed bin symlinks — not `node dist/....js` directly, and
 * not the exported `main()` function in-process.
 *
 * This exists because both of these were real, confirmed bugs that
 * every other test in this suite missed entirely:
 *
 *   1. `npm pack` without a `prepack` hook silently produced a tarball
 *      with no compiled code in it — 2 files, framework.json and
 *      package.json, no error.
 *   2. The naive `import.meta.url === file://${process.argv[1]}`
 *      main-module check is broken specifically for npm's bin
 *      symlinks: process.argv[1] reflects the invocation path (through
 *      the symlink), import.meta.url reflects the resolved real file.
 *      They never matched, so the CLI silently did nothing — no error,
 *      no output, exit code 0 — when run as the actual installed
 *      `ai-product-pulse` command.
 *
 * Every other test in this repo calls exported functions directly or
 * spawns `node dist/....js` by path, so none of them could have caught
 * either bug. This is slow (a real npm install) and intentionally kept
 * to a single focused test file for that reason.
 */
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const PACKAGE_ROOT = fileURLToPath(new URL("..", import.meta.url));

let tmpDir: string;
let tarballPath: string;
let installDir: string;

beforeAll(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "ai-product-pulse-pack-test-"));

  // Real `npm pack` — exercises the prepack hook exactly as `npm publish` would.
  const packOutput = execFileSync("npm", ["pack", "--pack-destination", tmpDir], {
    cwd: PACKAGE_ROOT,
    encoding: "utf-8",
  });
  const tarballName = packOutput.trim().split("\n").pop();
  if (!tarballName) throw new Error("npm pack produced no output");
  tarballPath = join(tmpDir, tarballName);

  installDir = join(tmpDir, "install-target");
  mkdirSync(installDir, { recursive: true });
  execFileSync("npm", ["init", "-y"], { cwd: installDir, stdio: "ignore" });
  execFileSync("npm", ["install", tarballPath], { cwd: installDir, stdio: "ignore" });
}, 120_000);

afterAll(() => {
  rmSync(tmpDir, { recursive: true, force: true });
});

describe("npm pack contents", () => {
  it("includes compiled dist output, not just data files", () => {
    // The confirmed failure mode: without a prepack hook, this tarball
    // contained exactly 2 files (framework.json, package.json) and no
    // code at all, with no error from npm pack itself.
    const listing = execFileSync("tar", ["-tzf", tarballPath], { encoding: "utf-8" });
    expect(listing).toMatch(/dist\/adapters\/inbound\/cli\.js/);
    expect(listing).toMatch(/dist\/adapters\/inbound\/mcpServer\.js/);
    expect(listing).toMatch(/dist\/index\.js/);
  });

  it("includes framework.json", () => {
    const listing = execFileSync("tar", ["-tzf", tarballPath], { encoding: "utf-8" });
    expect(listing).toMatch(/framework\.json/);
  });
});

describe("real install", () => {
  it("bundles framework.json inside the installed package", () => {
    const installedFrameworkJson = join(installDir, "node_modules", "ai-product-pulse", "framework.json");
    expect(existsSync(installedFrameworkJson)).toBe(true);
  });

  it("creates executable bin symlinks", () => {
    const binDir = join(installDir, "node_modules", ".bin");
    const entries = readdirSync(binDir);
    expect(entries).toContain("ai-product-pulse");
    expect(entries).toContain("ai-product-pulse-mcp");
  });
});

describe("real bin symlink invocation — the case every other test in this repo misses", () => {
  it("ai-product-pulse triage produces real output through the installed symlink", () => {
    const binPath = join(installDir, "node_modules", ".bin", "ai-product-pulse");
    const input = JSON.stringify({
      subject_name: "Packaging Test",
      layers: [
        { layer_id: "model_performance", score: 3, evidence_summary: "x", indicators: [] },
        { layer_id: "product_behaviour", score: 3, evidence_summary: "x", indicators: [] },
        { layer_id: "business_outcome", score: 3, evidence_summary: "x", indicators: [] },
      ],
    });

    // Run from a directory nested well below the install root, with
    // nothing else nearby — the same condition that exposed the bug.
    const runDir = join(installDir, "nested", "deep", "directory");
    mkdirSync(runDir, { recursive: true });

    const stdout = execFileSync(binPath, ["triage"], { input, cwd: runDir, encoding: "utf-8" });
    const report = JSON.parse(stdout) as { subject_name: string; overall_score: number };
    expect(report.subject_name).toBe("Packaging Test");
    expect(report.overall_score).toBe(3);
  });

  it("ai-product-pulse-mcp responds to a real handshake through the installed symlink", async () => {
    const binPath = join(installDir, "node_modules", ".bin", "ai-product-pulse-mcp");
    const { spawn } = await import("node:child_process");

    const serverInfo = await new Promise<{ name: string; version: string }>((resolve, reject) => {
      const proc = spawn(binPath, []);
      const initRequest = {
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test", version: "0.0.1" } },
      };
      proc.stdin.write(JSON.stringify(initRequest) + "\n");

      let buffer = "";
      const timeout = setTimeout(() => {
        reject(new Error("timed out waiting for MCP handshake response"));
      }, 5000);
      proc.stdout.on("data", (chunk: Buffer) => {
        buffer += chunk.toString();
        if (buffer.includes("\n")) {
          clearTimeout(timeout);
          const response = JSON.parse(buffer.split("\n")[0] ?? "") as {
            result: { serverInfo: { name: string; version: string } };
          };
          proc.kill();
          resolve(response.result.serverInfo);
        }
      });
      proc.stderr.on("data", (chunk: Buffer) => {
        clearTimeout(timeout);
        reject(new Error(`stderr: ${chunk.toString()}`));
      });
    });

    expect(serverInfo.name).toBe("ai-product-pulse");
  });
});
