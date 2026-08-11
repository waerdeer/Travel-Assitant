/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#F9F8F6',
        surface: '#FFFFFF',
        foreground: '#1A1C19',
        muted: '#8A8C89',
        border: '#E8E6E1',
        accent: '#D4CDC4'
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
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
