/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: "#1f5eff",
        ink: "#1b2430",
        muted: "#5d7189",
        line: "#dfe3e8",
        panel: "#f8f9fb",
        go: "#1e7e34",
        risk: "#c0392b",
      },
      fontFamily: {
        sans: ['"Noto Sans"', "Segoe UI", "system-ui", "sans-serif"],
        mono: ['"Noto Sans Mono"', "Consolas", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
