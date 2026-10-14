/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        'bg-alt': 'var(--bg-alt)',
        surface: 'var(--surface)',
        'surface-raised': 'var(--surface-raised)',
        text: 'var(--text)',
        'text-muted': 'var(--text-muted)',
        'text-on-accent': 'var(--text-on-accent)',
        accent: 'var(--accent)',
        'accent-hover': 'var(--accent-hover)',
        link: 'var(--link)',
        border: 'var(--border)',
        'focus-ring': 'var(--focus-ring)',
        'hero-bg': 'var(--hero-bg)',
        'hero-text': 'var(--hero-text)',
        'footer-bg': 'var(--footer-bg)',
        'footer-text': 'var(--footer-text)',
        status: {
          safe: 'var(--status-safe)',
          'safe-bg': 'var(--status-safe-bg)',
          review: 'var(--status-review)',
          'review-bg': 'var(--status-review-bg)',
          blocked: 'var(--status-blocked)',
          'blocked-bg': 'var(--status-blocked-bg)',
          failed: 'var(--status-failed)',
          'failed-bg': 'var(--status-failed-bg)',
          processing: 'var(--status-processing)',
          'processing-bg': 'var(--status-processing-bg)',
        },
      },
      fontFamily: {
        heading: ['var(--font-heading)', 'sans-serif'],
        body: ['var(--font-body)', 'sans-serif'],
        mono: ['var(--font-mono)', 'monospace'],
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
      },
      boxShadow: {
        card: 'var(--shadow-card)',
      },
      maxWidth: {
        container: 'var(--container-max)',
      },
    },
  },
  plugins: [],
}
