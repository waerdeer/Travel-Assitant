/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#F9F8F6', // Sand/Linen
        surface: '#FFFFFF',
        foreground: '#1A1C19', // Off-black
        muted: '#8A8C89',      // Minimalist grey
        border: '#E8E6E1',     // Delicate lines
        accent: '#D4CDC4'      // Warm highlight
      },
      fontFamily: {
        sans: ['"Inter"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        serif: ['"Playfair Display"', 'ui-serif', 'Georgia', 'serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace']
      },
      letterSpacing: {
        widest: '.2em',
      }
    },
  },
  plugins: [],
}
