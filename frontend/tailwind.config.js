/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          950: '#0a0e17',
          900: '#0f1522',
          800: '#161e2e',
          700: '#1f2937',
          600: '#2b3548',
        },
        normal: '#22c55e',
        info: '#3b82f6',
        warning: '#f59e0b',
        critical: '#ef4444',
      },
    },
  },
  plugins: [],
};
