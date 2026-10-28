# Design tokens, layout, accessibility

## Tokens (`src/index.css`)
Intel/OEP palette: Classic Blue primary (light), Energy Blue (dark), OKLCH
variables for light and `.dark`. Use semantic classes (`bg-card`, `text-muted-foreground`,
`border`, `text-primary`). Status colours come from the `status-info|success|error|neutral`
utilities, consumed as `bg-(--status-bg) border-(--status-border) text-(--status-fg)`;
always pair colour with text (never colour alone). Font: Montserrat Variable
(self-hosted via `@fontsource-variable/montserrat`; no CDN). Radius from `--radius`.

## Layout
Header / three-column main / footer. Columns: Services 280 px, Chat flexible,
Autonomy 350 px (≥1024 px); 220/flex/300 at 768–1023 px; below 768 px Chat then Autonomy
stack and Services opens in a left Sheet from the header button.

## Theme
`ThemeProvider` toggles `.dark` on `<html>`, persists `localStorage["qsr-theme"]`,
defaults to `prefers-color-scheme`. `index.html` sets it before first paint.

## Accessibility
- Landmarks: `header`, `main`, labelled `aside`/`section`, `footer`; skip link to chat.
- Chat log is `role="log"`, status text is `role="status"`, errors `role="alert"`.
- Every control has an accessible name; icon-only buttons need `aria-label`.
- Visible `:focus-visible` ring; full keyboard operation; respect `prefers-reduced-motion`.
- Text contrast AA; touch targets comfortable on phones.
- Provide loading (skeleton), empty, error and success states for each panel.
