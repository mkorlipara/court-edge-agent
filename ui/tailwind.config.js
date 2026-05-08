/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-inter)", "Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        background: "#0d0d0f",
        surface: "#131318",
        "surface-2": "#1a1a22",
        border: "#252530",
        foreground: "#f0f0f5",
        muted: "#6b6b7e",
        green: "#00ff87",
        "green-dim": "#00c968",
        red: "#ff4d4d",
        "red-orange": "#ff6b35",
        yellow: "#ffd700",
      },
    },
  },
  plugins: [],
};
