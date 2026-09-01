---
kind: frontend_style
name: Tailwind CSS v4 + Dark Slate Theme with Shared UI Primitives
category: frontend_style
scope:
    - '**'
source_files:
    - frontend/package.json
    - frontend/vite.config.ts
    - frontend/src/index.css
    - frontend/src/components/ui.tsx
    - frontend/src/App.tsx
---

## What system/approach is used

The frontend styling system is built on **Tailwind CSS v4** (via `@tailwindcss/vite` plugin) integrated into a Vite/React application. Styling is applied exclusively through Tailwind utility classes in JSX (`className=`) and via `@apply` directives inside CSS files. There is no CSS-in-JS library, styled-components, or SCSS preprocessor — only plain `.css` for global rules and Tailwind utilities everywhere else.

The visual theme is a **dark-mode-only** palette centered on the `slate` color scale (`slate-950`, `slate-900`, `slate-800`, `slate-600`, `slate-500`, `slate-300`, `slate-200`) with accent colors drawn from `sky`, `violet`, `emerald`, `red`, `orange`, and `yellow`. The entire app forces dark mode by setting `color-scheme: dark` on `:root` and applying `bg-slate-950 text-slate-200 antialiased` to `body`.

## Key files and packages

- `frontend/package.json` — declares dependencies: `react 18`, `zustand`, `@tanstack/react-query`, `@tanstack/react-table`, `echarts`/`echarts-for-react`; dev deps include `tailwindcss 4`, `@tailwindcss/vite 4`, `vite 6`, `@vitejs/plugin-react`.
- `frontend/src/index.css` — single global stylesheet that imports Tailwind (`@import "tailwindcss"`), sets dark color scheme, base typography, and custom scrollbar styles using `@apply`.
- `frontend/vite.config.ts` — registers the Tailwind plugin and proxies `/api` calls to the backend at `http://127.0.0.1:8000`.
- `frontend/src/components/ui.tsx` — shared primitive components (`Card`, `SevBadge`, `Delta`, `Kpi`, `Table`, `Empty`, `Spinner`) that encapsulate reusable Tailwind class compositions and severity/accent color mappings.
- View components under `frontend/src/views/` (`AreaExplorer.tsx`, `PowerExplorer.tsx`, `TimingExplorer.tsx`, `Compare.tsx`, `DesignSpace.tsx`, `RunExplorer.tsx`, `Scorecard.tsx`) compose these primitives with inline Tailwind classes.
- `frontend/src/App.tsx` — layout shell (header, sidebar navigation, main content area, optional right-hand AI chat panel) built entirely with Tailwind utilities.

## Architecture and conventions

- **Utility-first throughout**: Every visual style is expressed as Tailwind utility classes directly in JSX; there are no component-scoped CSS modules or BEM-style class names.
- **Global reset via one CSS file**: All cross-cutting styles live in `index.css` — dark mode, base font stack (`ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`), full-height root, and custom webkit scrollbar styling.
- **Shared UI primitives**: Visual building blocks are extracted into `components/ui.tsx` rather than duplicated across views. This includes:
  - `Card` — rounded bordered container with optional title bar and padding.
  - `SevBadge` — severity label whose background/text/border colors are driven by a `SEV_STYLE` map (`critical` → red, `high` → orange, `medium` → yellow, `low` → sky, `info` → slate).
  - `Delta` — percentage change display with green/red coloring based on sign and magnitude threshold (`Math.abs(pct) < 0.05` falls back to neutral).
  - `Kpi` — metric card with label, value, unit, delta, target, and an `overBudget` variant that switches to a red-tinted border/background.
  - `Table`, `Empty`, `Spinner` — generic table wrapper, placeholder, and loading indicator.
- **Consistent spacing & borders**: Views consistently use `border-slate-800` for dividers, `bg-slate-900/60` for semi-transparent panels, `rounded-lg` for cards, and `px-4 py-2` / `p-4` for internal padding.
- **Typography**: Headings use `text-sm font-semibold` with `uppercase tracking-wide` for labels; numeric values use `font-mono`; body text uses the system font stack.
- **Responsive behavior**: Uses Tailwind's responsive prefixes (e.g., `hidden md:inline` in the header) and flexible layouts (`flex`, `min-h-0 flex-1`, `w-[400px] shrink-0`) rather than media queries in CSS.
- **Charts**: ECharts is rendered via `echarts-for-react` inside a dedicated `EChart.tsx` component; chart theming is handled through ECharts options rather than Tailwind.

## Conventions and constraints

- **Dark mode only**: The app enforces a dark color scheme globally; no light-mode variants or toggles exist.
- **No design-token variables beyond CSS custom properties**: Colors are referenced directly as Tailwind tokens (e.g., `bg-slate-950`, `text-emerald-400`) rather than CSS `--*` variables or a centralized theme config file.
- **Severity levels are fixed**: The `SEV_STYLE` map defines exactly five severity categories (`critical`, `high`, `medium`, `low`, `info`); unknown severities fall back to `info`.
- **Delta thresholds**: Percentage deltas below ±0.05% are treated as neutral (`text-slate-400`); larger positive/negative deltas use `text-emerald-400` / `text-red-400` respectively.
- **Over-budget highlighting**: KPI cards accept an `overBudget` prop that switches the border to `border-red-500/50` and background to `bg-red-500/5`.
- **Build-time enforcement**: The build script runs `tsc --noEmit && vite build`, so TypeScript type-checking is enforced before bundling, but there is no separate lint/Prettier step visible in `package.json` scripts.