import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Schweizer SaaS - Navy als Primary, sauberer Off-White-BG
        background: {
          DEFAULT: "#FAFAF9",
          card: "#FFFFFF",
        },
        foreground: {
          DEFAULT: "#0A0A0A",
          muted: "#737373",
          subtle: "#A3A3A3",
        },
        border: {
          DEFAULT: "#E5E5E5",
          strong: "#D4D4D4",
        },
        primary: {
          DEFAULT: "#1E293B",  // Slate 800 - Navy
          fg: "#FFFFFF",
          hover: "#0F172A",
        },
        accent: {
          DEFAULT: "#0EA5E9",  // Sky 500 - frisches Akzent-Blau
          fg: "#FFFFFF",
        },
        success: "#10B981",
        warning: "#F59E0B",
        danger: "#EF4444",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "Menlo", "monospace"],
      },
      borderRadius: {
        lg: "12px",
        md: "8px",
        sm: "6px",
      },
    },
  },
  plugins: [],
};
export default config;
