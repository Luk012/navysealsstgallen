# ChainIQ Interface Design System

## Intent

**Who:** Procurement officers and supply chain managers. Mid-workday, multiple active requests. Needs to trust AI, not just see it.

**What they do:** Submit plain-text requests → watch agents work → review ranked suppliers → approve constraint trade-offs.

**Feel:** Dense like a control room, legible like good paperwork. Purposeful tool, not soft SaaS.

---

## Typography

- **Font:** Noto Sans (variable `--font-sans`, already wired in `layout.tsx`)
- **Weights:** `font-normal` (400) for body, `font-medium` (500) for headings, labels, emphasis
- **No other weights.** Never bold, never light.
- **Scale:** `text-xs` (10–12px) for meta/labels, `text-sm` (14px) for body, `text-base` (16px) for page titles
- **Labels above sections:** `text-xs font-medium uppercase tracking-wide text-neutral-500`

---

## Colors

Base: TailwindCSS neutral palette only. Green accent from CSS vars.

| Role | Token |
|---|---|
| Page background | `bg-white` |
| Sidebar / secondary surface | `bg-neutral-50` |
| Card / panel surface | `bg-white` with `border border-neutral-200` |
| Muted surface | `bg-neutral-50` |
| Primary text | `text-neutral-900` |
| Secondary text | `text-neutral-600` |
| Muted / meta text | `text-neutral-400` / `text-neutral-500` |
| Border | `border-neutral-200` (default), `border-neutral-100` (dividers inside panels) |
| Primary action | `bg-neutral-900 text-white` — NOT the green primary for buttons |
| Green accent | `var(--color-primary)` — used ONLY for: complete status icons, score bars, active pipeline nodes |
| Amber (needs input) | `bg-amber-50 border-amber-200 text-amber-700` |
| Destructive | `bg-red-50 border-red-200 text-red-700` |

**Rule:** Green is sparse. It signals "done" and "primary". Neutral-900 is the main action color.

---

## Radius

- **`rounded-lg`** (8px) — default for all interactive elements: buttons, inputs, table cells, badges
- **`rounded-xl`** (12px) — panels, cards, dialogs, overview stat blocks
- Never use `rounded-full` except for avatars/user icons
- Never use `rounded-2xl` or larger

---

## Spacing

- Base unit: 4px (Tailwind default)
- Section gaps: `gap-5` / `py-5` / `px-6`
- Compact row padding: `px-3 py-2.5` (tables), `px-4 py-3` (list items)
- Inner content spacing: `space-y-4` between major blocks, `space-y-2` within

---

## Icons

- **Library:** `@hugeicons/core-free-icons` + `@hugeicons/react`
- **Usage:** `<HugeiconsIcon icon={IconName} size={N} color="..." />`
- **Sizes:** 12px (inline), 13–14px (meta), 15–16px (nav/actions), 20px (hero/empty states)
- **Color:** Always explicit — never inherit. Use `"currentColor"` only in nav active states.

### Established icon mappings
| Concept | Icon |
|---|---|
| Dashboard/home | `Home01Icon` |
| Tasks | `Task01Icon` |
| Suppliers | `Package01Icon` |
| Policy / checklist | `CheckListIcon` |
| Audit log | `LegalDocument01Icon` |
| Settings | `Settings01Icon` |
| Search | `Search01Icon` |
| Add / new | `Add01Icon` |
| Complete | `CheckmarkCircle01Icon` |
| Clock / pending | `Clock01Icon` |
| Alert / error | `AlertCircleIcon` |
| Arrow / navigate | `ArrowRight01Icon` |
| Stage 1 — Intake | `FileAddIcon` |
| Stage 2 — Reasoning | `Brain01Icon` |
| Stage 3 — Master Mind | `Robot01Icon` |
| Stage 4 — Suppliers | `DeliveryTruck01Icon` |
| Commit / version | `GitCommitIcon` |
| Budget / money | `Money01Icon` |
| Compliance / shield | `Shield01Icon` |
| Cancel / reject | `Cancel01Icon` |
| More options | `MoreVerticalIcon` |
| Organisation | `Building01Icon` |
| User | `User02Icon` |
| Filter | `FilterHorizontalIcon` |

---

## Layout

3-column shell for the Tasks view:

```
Sidebar (200px fixed) | Task list (300px fixed) | Detail panel (flex-1)
```

- Sidebar: `bg-neutral-50 border-r border-neutral-200`
- Columns separated by `border-r border-neutral-200`
- No top nav bar — sidebar handles all navigation
- `h-screen overflow-hidden` on root, inner columns scroll independently

---

## Components

### Status badges
```tsx
// Complete
<span className="rounded-lg bg-neutral-900 px-2.5 py-1 text-xs font-medium text-white">Complete</span>

// Running
<span className="rounded-lg bg-neutral-100 px-2.5 py-1 text-xs font-medium text-neutral-600">Stage N · Running</span>

// Needs input
<span className="rounded-lg bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-800 border border-amber-200">Needs input</span>
```

### Primary button
```tsx
<button className="flex items-center gap-1.5 rounded-lg bg-neutral-900 px-4 py-2 text-xs font-medium text-white hover:bg-neutral-700">
```

### Ghost / secondary button
```tsx
<button className="rounded-lg border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-50">
```

### Section label
```tsx
<p className="text-xs font-medium uppercase tracking-wide text-neutral-500">Label</p>
```

### Data table
```tsx
// Header row
<tr className="border-b border-neutral-200 bg-neutral-50">
  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Column</th>
```

### Mini pipeline indicator (task list cards)
4 x `h-1 flex-1 rounded-full` bars:
- complete → `bg-neutral-900`
- running → `bg-neutral-400 animate-pulse`
- needs_input → `bg-amber-400`
- pending → `bg-neutral-200`

### Commit log entry
Left dot timeline with `border-l` connector. Dot: `size-6 rounded-full border border-neutral-200 bg-white`.
Content card shows: `field.path`, old→new with arrow, reasoning, Master Mind rationale, timestamp in `font-mono text-[10px] text-neutral-300`.

### System recommendation block (Stage 4A)
```tsx
<div className="rounded-lg border border-neutral-900 bg-neutral-900 p-3">
  // Dark card with Robot icon + green label + white body text
```

### Branch B constraint panel
Amber alert header, then per-constraint cards with accept/reject toggle buttons, then free-text feedback + re-run.

---

## Animation

- Running stage nodes: `animate-pulse` on the icon container
- Loading spinner: `animate-spin rounded-full border-2 border-neutral-200 border-t-neutral-800 size-4`
- Score bars / confidence bars: static width via inline style, no animation
- New task submission: optimistic UI, 1.8s delay then close

---

## Tone

- Labels are lowercase ("needs input", not "NEEDS INPUT") except section headers
- Numbers first: "3 commits · 1 iteration" not "1 iteration with 3 commits"
- The system recommends, never decides — copy must reflect this
- "Re-run matching" not "Submit" for constraint relaxation
