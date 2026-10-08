/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'] },
      colors: {
        paper: '#F7F5F1',
        panel: '#FFFFFF',
        line: '#E4E0D8',
        ink: { DEFAULT: '#26292E', soft: '#4A4F57', mute: '#7C818A' },
        accent: { DEFAULT: '#3F6A8F', soft: '#E7EEF4', dark: '#2F5373' },
        ok: '#3E7D5A', warn: '#B07A2A', bad: '#A64B45',
      },
      boxShadow: { card: '0 1px 2px rgba(38,41,46,0.05)' },
    },
  },
  plugins: [],
}
