/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "media",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        panel: "var(--panel)",
        ink: "var(--text)",
        muted: "var(--muted)",
        line: "var(--border)",
        accent: "var(--accent)",
        accentSoft: "var(--accent-soft)",
        danger: "var(--danger)",
      },
    },
  },
  plugins: [],
};
