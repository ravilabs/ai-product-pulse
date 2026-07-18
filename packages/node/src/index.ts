/**
 * AI Product Pulse — deterministic triage for AI product features.
 *
 * Public entry point for library consumers. The CLI (bin: ai-product-pulse)
 * and MCP server (bin: ai-product-pulse-mcp) are the primary intended
 * interfaces — see README.md — but this module is here for anyone
 * integrating the scoring logic directly into their own TypeScript code.
 *
 * No separate VERSION export here: package.json's version field is
 * already the real npm convention for this, unlike Python where
 * __version__ in __init__.py serves an actual purpose. Adding a
 * parallel constant would just be a fifth place to keep in sync with
 * no corresponding benefit.
 */
export * from "./domain/entities.js";
export { framework, loadFramework } from "./domain/loader.js";
export {
  applyRiskThresholds,
  computeMaturityLevel,
  computeOverallScore,
  evaluateVerdicts,
} from "./domain/scoringEngine.js";
export * from "./usecases/index.js";
