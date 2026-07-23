/** @type {import('tailwindcss').Config} */
// Book 6 design tokens. Neutral slate/ink base, a single deep-blue brand
// primary, semantic status colours used sparingly, and a dedicated provenance
// palette (measured / estimated / modelled) that is visibly distinct — the
// visual enforcement of the Trust Doctrine (Book 6 §3.1, §7).
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Brand primary — deep blue (Book 6 §3.1).
        brand: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          400: "#60a5fa",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8",
          800: "#1e3a8a",
          900: "#172554",
        },
        // Semantic status — used sparingly.
        success: { fg: "#166534", bg: "#dcfce7", ring: "#22c55e" },
        attention: { fg: "#92400e", bg: "#fef3c7", ring: "#f59e0b" },
        critical: { fg: "#991b1b", bg: "#fee2e2", ring: "#ef4444" },
        // Provenance palette — three distinct treatments (Book 6 §7). Each is
        // paired with a text label + icon in the component, so meaning never
        // rests on colour alone (WCAG AA, §11 / UX-07).
        measured: { fg: "#0f172a", bg: "#f1f5f9", ring: "#cbd5e1" },
        estimated: { fg: "#9a3412", bg: "#ffedd5", ring: "#fb923c" },
        modelled: { fg: "#6b21a8", bg: "#f3e8ff", ring: "#c084fc" },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      borderRadius: {
        card: "0.875rem",
      },
      boxShadow: {
        // Restrained elevation for cards (§3.1).
        card: "0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.08)",
      },
    },
  },
  plugins: [],
};
