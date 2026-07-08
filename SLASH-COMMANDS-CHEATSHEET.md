# Claude Code Slash Commands — Naomi's Cheat-Sheet

Organized by what you're doing. These are the ones that actually matter for E4E /
Sabi / your build workflow — not the whole list (most of the rest are role packs you
can ignore until you need them).

---

## 🔎 Research (your single most useful one)

| Command | What it does |
|---|---|
| **`/deep-research`** | Fans out many web searches, fetches sources, **adversarially fact-checks** the claims, and writes a **cited report**. Use it for telephony options, grant landscapes, pedagogy, competitor scans — anything you'd otherwise spend an afternoon Googling. Tip: give it a *specific* question (budget, region, use-case) and it goes deeper. |

> ⚠️ Reminder from your own project rules: before new research, check `research-agents/`
> first — you already have 625+ files. Use `/deep-research` for genuinely *new* topics.

---

## 💻 Shipping code (your dev loop)

| Command | What it does |
|---|---|
| **`/run`** | Actually launches the app so you can see a change working (not just tests). |
| **`/verify`** | Runs the app end-to-end and observes behavior to confirm a fix really works. |
| **`/code-review`** | Reviews your current diff for real bugs + cleanup. Add `--fix` to apply, `--comment` to post on a PR. `ultra` = deep multi-agent cloud review of the branch. |
| **`/security-review`** | Security-focused pass over the diff. |
| **`/simplify`** | Cleans up changed code for reuse/simplicity/efficiency (no bug hunting). |
| **`/loop`** | Run a command on a repeat interval (e.g. poll a deploy). |
| **`/schedule`** | Cron-style scheduled cloud agents + one-off reminders. |

---

## ▲ Vercel (push to prod — your standing preference)

| Command | What it does |
|---|---|
| **`/vercel:deploy`** | Deploy current project. Pass `prod` for production, default is preview. |
| **`/vercel:status`** | Recent deployments, linked project, env overview. |
| **`/vercel:env`** | Manage env vars: list, pull, add, remove, diff. |
| **`/vercel:bootstrap`** | Set up a repo's Vercel-linked resources in the right order. |
| **`/vercel:nextjs`** | App Router expert guidance (routing, server components, caching). |
| **`/vercel:ai-sdk`** | AI SDK help — chat, streaming, tool calling, agents. Relevant to Sabi-style features. |

(There are ~25 `vercel:*` skills total — auth, storage, firewall, functions, etc.
Reach for the specific one when you hit that exact problem.)

---

## 📄 Pitch decks, grants & documents

| Command / Skill | What it does |
|---|---|
| **`anthropic-skills:pptx`** | Generates real PowerPoint decks — pitch decks, hackathon slides. |
| **`anthropic-skills:docx`** | Word docs — grant applications, proposals, contracts. |
| **`anthropic-skills:xlsx`** | Excel — cost models, budgets, per-student math. |
| **`anthropic-skills:pdf`** | Create/manipulate PDFs. |
| **`anthropic-skills:canvas-design`** | Visual/graphic design output. |
| **`/pdf-viewer:open` / `:annotate` / `:fill-form` / `:sign`** | Open your research PDFs in an interactive viewer to highlight, annotate, fill forms, or drop a signature. |

---

## 🧠 Thinking partner & planning

| Command | What it does |
|---|---|
| **`/product-management:brainstorm`** | Sharp sparring partner for a product idea, problem space, or strategic call. Good for "should Sabi do X" debates. |
| **`product-management:write-spec`** | Turn a vague idea into a structured PRD/spec. |
| **`product-management:competitive-brief`** | Competitor analysis (Bakame, Rori, etc.). |

---

## 🗂️ Role bundles (open only when the task fits)

Each of these is a *pack* of task-specific skills. You don't need to learn them — just
know they exist when you're in that mode:

- **`engineering:`** — architecture, system-design, debug, testing-strategy, incident-response, tech-debt
- **`data:`** — analyze, build-dashboard, create-viz, statistical-analysis, sql-queries → **useful for DataFest**
- **`design:`** — user-research, design-critique, accessibility-review, ux-copy → curriculum app UX
- **`marketing:`** — campaign-plan, content-creation, email-sequence → outreach to MTN/Airtel/partners
- **`legal:`** — review-contract, triage-nda, risk-assessment → entity structure, Sonia's contract, IP
- **`operations:`** / **`finance:`** / **`human-resources:`** / **`sales:`** — there if you ever need them

---

## 🎙️ Voice (what we're using right now)

| Command | What it does |
|---|---|
| **`/voicemode:converse`** | Start a voice conversation (this). |
| **`/voicemode:status`** | Check Whisper/Kokoro services. |
| **`/voicemode:install`** | Reinstall voice services if they break. |

---

## ⚙️ Config & housekeeping

| Command | What it does |
|---|---|
| **`/update-config`** | Change Claude Code settings, permissions, hooks ("from now on, whenever X…"). |
| **`/fewer-permission-prompts`** | Auto-allowlist your common safe commands so you get fewer prompts. |
| **`/init`** | Generate/refresh a project's CLAUDE.md. |

---

### My top 5 for you, honestly

1. **`/deep-research`** — replaces hours of manual research, with citations.
2. **`/run`** + **`/verify`** — stop guessing whether a change works; see it.
3. **`/vercel:deploy prod`** — your ship button.
4. **`anthropic-skills:pptx` / `docx`** — pitch decks & grant apps without fighting formatting.
5. **`/product-management:brainstorm`** — a real thinking partner for strategy calls.

*To run any of these, just type the command (with the leading slash) or ask me to use it.*
