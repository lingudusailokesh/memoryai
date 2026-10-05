const v = (n) => `rgb(var(--${n}) / <alpha-value>)`;
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["Instrument Sans", "system-ui", "sans-serif"] },
      colors: {
        bg: v("bg"), card: v("card"), side: v("side"), line: v("line"),
        ink: v("ink"), mute: v("mute"), accent: v("accent"), "accent-ink": v("accent-ink"),
      },
    },
  },
};
