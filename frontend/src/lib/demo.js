// Product UI scope (DEMO-FR-40). Default on via frontend/.env and Docker build.
// Set VITE_DEMO_MODE=0 to restore full v1 navigation during development.
export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE !== '0';

const HIDDEN_IN_DEMO = new Set([
  '/analytics',
  '/reports',
  '/investigations',
  '/assistant',
]);

export function isHiddenInDemo(to) {
  return DEMO_MODE && HIDDEN_IN_DEMO.has(to);
}
