// Demo build flag (DEMO-FR-40). Set at build time with VITE_DEMO_MODE=1.
// In demo mode we hide v1-only surfaces that are not part of the first cloud
// demo, per PRD Phase 1a §2.3 (Analytics, Reports, Investigations, AI
// Assistant, Uploads).
export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === '1';

const HIDDEN_IN_DEMO = new Set([
  '/analytics',
  '/reports',
  '/investigations',
  '/assistant',
]);

export function isHiddenInDemo(to) {
  return DEMO_MODE && HIDDEN_IN_DEMO.has(to);
}
