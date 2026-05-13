/**
 * Tailwind 4 ships its own PostCSS plugin; that's the only one we need.
 * (No more autoprefixer — Tailwind 4 handles vendor prefixes internally.)
 */
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;
