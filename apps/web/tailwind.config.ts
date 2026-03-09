import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "../../packages/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        border: "var(--line)",
        input: "var(--line)",
        background: "var(--bg)",
        foreground: "var(--text)",
        card: "var(--panel)",
        "card-foreground": "var(--text)",
        primary: {
          DEFAULT: "#111827",
          foreground: "#ffffff",
        },
        muted: {
          DEFAULT: "#f4f4f5",
          foreground: "#71717a",
        },
      },
      borderRadius: {
        lg: "16px",
        md: "12px",
        sm: "10px",
      },
    },
  },
  plugins: [],
};

export default config;
