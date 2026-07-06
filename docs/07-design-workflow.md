# Design preview & feedback workflow (for Phases 2 and 4)

How to see the frontend while Claude builds it, make design decisions, and feed those
decisions back precisely. Researched 2026-07-06. Two distinct jobs are involved:

1. **The preview loop** — mechanics for rendering the work-in-progress in VS Code or a
   browser, for both the human and Claude itself.
2. **Design-quality layers** — skills/files that make Claude's output worth previewing
   and give feedback a shared vocabulary.

## 1. The preview loop

| Method | Role |
|---|---|
| **Dev server + hot reload** (Vite/Next/Astro `dev`) in a browser tab, or VS Code's Simple Browser / Live Preview extension side-by-side | The ground truth. Claude edits; the page updates in ~100ms. Baseline for all work. |
| **Playwright — CLI/script or MCP** (see § Playwright below) | Closes the loop from *Claude's* side: Claude screenshots its own render, sees layout breakage, and fixes it before the human looks. The biggest single upgrade — without it Claude designs blind. |
| **Annotated screenshots pasted into Claude Code** | The human side of the loop. Screenshot, mark up (circles/arrows), paste into the chat in VS Code. Highest-bandwidth feedback channel available. |
| **Claude in Chrome extension** | Claude drives the real browser session instead of headless — same loop, watchable. |
| **Claude Design (claude.ai/design) + DesignSync** | Component-library review: type scale, buttons, poster cards, format badges as preview cards in one browser pane. System-level review before/alongside page-level review. |

## 2. Design-quality layers — the six candidate tools

### Taste/vocabulary skills (pick ONE as the base layer)

- **Impeccable** ([pbakaus/impeccable](https://github.com/pbakaus/impeccable), ~35k★) —
  a design language for agent + human: commands/verbs like `bolder`, `quieter`,
  `typeset`, `colorize`, `audit`, `critique`, backed by 45 deterministic slop-detector
  rules plus LLM critique checks, with brand/product modes. Its differentiator is
  exactly our need: **feedback becomes executable** ("make the CTA quieter, typeset the
  film titles" instead of paragraphs of vibes). Free, installs as a skill, applies
  automatically.
- **Taste Skill** ([leonxlnx/taste-skill](https://github.com/leonxlnx/taste-skill),
  `design-taste-frontend`, ~56k★) — anti-generic-AI-look ruleset with tunable baseline
  metrics (design variance, motion intensity, visual density) and hard overrides for
  LLM habits (centered heroes, purple gradients, emoji spam). Overlaps Impeccable
  heavily — running both risks contradictions. Impeccable wins on feedback vocabulary;
  Taste wins on tunable metrics. A [merged synthesis](https://github.com/h3nryprod01/design-taste)
  of both plus Anthropic's frontend-design skill also exists.

### Design-system sources (pick one path)

- **DESIGN.md / awesome-design-md**
  ([VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md)) —
  55+ ready-made `DESIGN.md` files reverse-engineered from real brands (Stripe, Linear,
  Notion, Vercel…): color palettes, type scales, spacing, component styling, responsive
  rules in plain markdown. Drop one in the repo root; agents build to it. Zero effort
  and instant consistency; the trade-off is starting from someone else's brand language —
  treat it as a starting point to mutate, not an identity.
- **SkillUI** ([skillui.vercel.app](https://skillui.vercel.app/)) — CLI that crawls any
  URL/repo/folder and packages its complete design system (tokens, typography,
  components, animations, screenshots; "ultra" mode adds a real browser capturing scroll
  journeys/interactions) into a `.skill` bundle Claude Code auto-loads. The right tool if
  an existing site — a repertory cinema, a film festival, A24 — already nails the
  aesthetic we want.
- **design-extract** ([Manavarya09/design-extract](https://github.com/Manavarya09/design-extract),
  ~3.4k★) — the heavyweight extractor: DTCG-standard tokens
  (primitive/semantic/composite), an MCP server, emitters for Tailwind v4 / shadcn /
  Figma variables / mobile platforms, CSS health audit, WCAG remediation, and
  `/grade`/`/battle`/`/remix` commands. More machinery than this project needs
  day-to-day, but its WCAG audit maps directly onto the Phase 4 accessibility pass.

## 3. Playwright: CLI/script vs MCP server

Both give Claude eyes; they differ in statefulness and cost.

**Playwright CLI / one-off scripts** (`npx playwright screenshot`, or a 10-line script
Claude writes and runs via Bash):
- Lighter: no server process, no extra tool schemas in context, nothing to configure.
- **Stateless**: every invocation launches a fresh browser, loads the page cold, and
  exits. Fine when "look at the page" is one step.
- Multi-step interactions (open page → pick a date → open the film modal → hover a
  poster → screenshot *that*) require Claude to script the whole sequence in advance,
  run it, and re-script on every correction — a slower, guess-ahead loop.

**Playwright MCP** (`@playwright/mcp`, Microsoft's official server):
- **Stateful**: one live browser session across many tool calls. Claude navigates,
  clicks, waits, *reacts to what it sees*, then screenshots — an interactive loop
  instead of a pre-scripted one.
- Exposes **accessibility-tree snapshots** — Claude reads page structure as cheap
  structured text instead of interpreting pixels, which is both more token-efficient
  and more reliable for "is the nav actually a nav" questions.
- Surfaces **console errors and network activity** — much of design debugging (fonts
  not loading, hydration errors, broken poster URLs) is invisible in a screenshot.
- Cost: a running server process and a large tool surface in context.

**Policy for this project:** start with CLI/script screenshots — for the core loop
("re-render page, screenshot, compare") stateless is genuinely enough, and it's what the
built-in verify/run skills already do. Adopt the MCP server when the work becomes
interactive: date-picker/calendar flows, hover/focus states, the Phase 3 auth and admin
UI, or whenever a design bug needs console/network visibility to diagnose.

## 4. Recommended workflow (in order)

1. **Design contract first**: pick a `DESIGN.md` from awesome-design-md (or
   SkillUI-extract a site we admire), then spend one session mutating it into this
   project's own brand. Highest-leverage step — all later previews iterate against a
   stable target instead of re-rolling the aesthetic each session.
2. **Install Impeccable** as the taste layer and shared feedback vocabulary.
3. **Build against a hot-reloading dev server**, browser beside VS Code.
4. **Claude self-checks every visual change** via Playwright screenshots (CLI first,
   MCP when interactive — see § 3).
5. **Human feedback = annotated screenshots + Impeccable verbs** ("poster grid bolder,
   this section quieter, audit the film-detail page").
6. Once components exist, **push the component library to Claude Design via DesignSync**
   for system-level review (type scale, cards, 35mm/70mm badges) in one browser pane.

## Sources

[Impeccable repo](https://github.com/pbakaus/impeccable) · [impeccable.style](https://impeccable.style/) ·
[Impeccable review](https://emelia.io/hub/impeccable-design-skill-review) ·
[Taste Skill repo](https://github.com/leonxlnx/taste-skill) · [tasteskill.dev](https://www.tasteskill.dev/) ·
[Taste skill guide](https://knightli.com/en/2026/06/06/taste-skill-ai-frontend-design/) ·
[awesome-design-md](https://github.com/VoltAgent/awesome-design-md) ·
[awesome-claude-design](https://github.com/VoltAgent/awesome-claude-design) ·
[SkillUI](https://skillui.vercel.app/) · [design-extract](https://github.com/Manavarya09/design-extract) ·
[extract-design-system](https://github.com/arvindrk/extract-design-system) ·
[merged design-taste](https://github.com/h3nryprod01/design-taste) ·
[Playwright MCP + Claude Code (builder.io)](https://www.builder.io/blog/playwright-mcp-server-claude-code) ·
[Playwright MCP vs Claude in Chrome](https://lalatenduswain.medium.com/playwright-mcp-vs-claude-in-chrome-which-browser-testing-tool-should-you-use-in-2026-e502bee0067a) ·
[Anthropic frontend-design skill](https://github.com/anthropics/claude-code/blob/main/plugins/frontend-design/skills/frontend-design/SKILL.md)
