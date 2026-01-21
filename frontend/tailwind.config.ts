import type { Config } from "tailwindcss"

const config: Config = {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        "bg-primary": "#000000",
        "bg-secondary": "#0A0A0A",
        "bg-tertiary": "#141414",
      },
      fontFamily: {
        sans: ["Manrope", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Space Grotesk", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      backdropBlur: {
        xs: "2px",
      },
      animation: {
        "fade-in": "fadeIn 0.5s ease-out",
        "slide-up": "slideUp 0.5s ease-out",
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "orb-drift": "orbDrift 26s ease-in-out infinite",
        "orb-drift-slow": "orbDrift 34s ease-in-out infinite",
        "glow-breathe": "glowBreathe 6s ease-in-out infinite",
        "sheen-slide": "sheenSlide 8s ease-in-out infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(20px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        orbDrift: {
          "0%": { transform: "translate3d(0, 0, 0) scale(1)" },
          "50%": { transform: "translate3d(10px, -16px, 0) scale(1.06)" },
          "100%": { transform: "translate3d(0, 0, 0) scale(1)" },
        },
        glowBreathe: {
          "0%": { boxShadow: "0 0 0 rgba(0,0,0,0)" },
          "50%": { boxShadow: "0 0 40px rgba(0, 217, 255, 0.35)" },
          "100%": { boxShadow: "0 0 0 rgba(0,0,0,0)" },
        },
        sheenSlide: {
          "0%": { transform: "translateX(-30%)" },
          "50%": { transform: "translateX(10%)" },
          "100%": { transform: "translateX(-30%)" },
        },
      },
    },
  },
  plugins: [],
}
export default config
