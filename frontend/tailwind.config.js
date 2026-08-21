/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans:    ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        display: ['Sora', 'Inter', 'system-ui', 'sans-serif'],
        mono:    ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      colors: {
        border: 'hsl(var(--border))',
        'border-strong': 'hsl(var(--border-strong))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        surface: {
          DEFAULT: 'hsl(var(--surface))',
          muted: 'hsl(var(--surface-muted))',
        },
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
          light: 'hsl(var(--primary-light))',
          glow: 'hsl(var(--primary-glow))',
        },
        gold: {
          DEFAULT: 'hsl(var(--gold))',
          foreground: 'hsl(var(--gold-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        // Brand accent (violet). Distinct from `accent`, which is a near-white
        // SURFACE tint used by ~305 hover/chip/muted-fill classes — redefining
        // that one turned every passive surface loud purple.
        brand: {
          DEFAULT: 'hsl(var(--brand))',
          foreground: 'hsl(var(--brand-foreground))',
          light: 'hsl(var(--brand-light))',
          outdoor: 'hsl(var(--brand-outdoor))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        success: { DEFAULT: 'hsl(var(--success))', foreground: 'hsl(var(--success-foreground))' },
        warning: { DEFAULT: 'hsl(var(--warning))', foreground: 'hsl(var(--warning-foreground))' },
        danger:  { DEFAULT: 'hsl(var(--danger))',  foreground: 'hsl(var(--danger-foreground))' },
        info:    { DEFAULT: 'hsl(var(--info))',    foreground: 'hsl(var(--info-foreground))' },
        teal:    { DEFAULT: 'hsl(var(--teal))',    foreground: 'hsl(var(--teal-foreground))' },
        slate:   { DEFAULT: 'hsl(var(--slate))',   foreground: 'hsl(var(--slate-foreground))' },
        neutral: { DEFAULT: 'hsl(var(--neutral))', foreground: 'hsl(var(--neutral-foreground))' },
      },
      borderRadius: {
        '2xl': '1rem',
        '3xl': '1.5rem',
        '4xl': '2rem',
      },
      boxShadow: {
        'glow-primary': '0 0 32px -6px hsl(var(--primary) / 0.4)',
        'glow-gold':    '0 0 32px -6px hsl(var(--gold) / 0.45)',
        'glow-success': '0 0 24px -6px hsl(var(--success) / 0.35)',
        'glow-danger':  '0 0 24px -6px hsl(var(--danger) / 0.35)',
        'soft':   '0 1px 2px hsl(var(--shadow-color) / 0.04), 0 1px 3px hsl(var(--shadow-color) / 0.06)',
        'medium': '0 4px 6px -2px hsl(var(--shadow-color) / 0.06), 0 10px 15px -3px hsl(var(--shadow-color) / 0.08)',
        'large':  '0 20px 48px -12px hsl(var(--shadow-color) / 0.2)',
      },
      transitionTimingFunction: {
        'spring': 'cubic-bezier(0.34, 1.56, 0.64, 1)',
        'out-soft': 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
      animation: {
        'fade-in': 'fadeIn 0.4s cubic-bezier(0.22, 1, 0.36, 1)',
        'slide-up': 'slideUp 0.5s cubic-bezier(0.22, 1, 0.36, 1)',
        'scale-in': 'scaleIn 0.25s cubic-bezier(0.34, 1.56, 0.64, 1)',
        'pulse-soft': 'pulseSoft 2.4s ease-in-out infinite',
        'float': 'float 6s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: { from: { opacity: '0' }, to: { opacity: '1' } },
        slideUp: {
          from: { opacity: '0', transform: 'translateY(16px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        scaleIn: {
          from: { opacity: '0', transform: 'scale(0.96)' },
          to:   { opacity: '1', transform: 'scale(1)' },
        },
        pulseSoft: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.6' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-12px)' },
        },
      },
    },
  },
  plugins: [],
}
