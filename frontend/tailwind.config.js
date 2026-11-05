/** @type {import('tailwindcss').Config} */
// Colors resolve to the CSS tokens in src/index.css so Tailwind utilities and
// the component classes stay in one palette (white theme).
const token = (name) => `rgb(var(--${name}-rgb) / <alpha-value>)`;

export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        page: token('bg'),
        panel: token('panel'),
        raised: token('raised'),
        line: token('line'),
        'line-strong': token('line-strong'),
        ink: token('ink'),
        'ink-2': token('ink-2'),
        muted: token('muted'),
        accent: token('accent'),
        normal: token('ok'),
        info: token('info'),
        warning: token('warn'),
        critical: token('crit'),
      },
      fontFamily: {
        display: ['Archivo', 'IBM Plex Sans', 'system-ui', 'sans-serif'],
        sans: ['IBM Plex Sans', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['IBM Plex Mono', 'ui-monospace', 'Cascadia Mono', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
};
