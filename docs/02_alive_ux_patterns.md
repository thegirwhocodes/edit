# Research 2 — What Makes AI Feel Alive (UX Patterns)

How to make Ed.it feel like a collaborator, not a tool. Patterns pulled from Sana AI, Granola, Rewind, Cursor, Pi, Midjourney, etc.

## 1. Sana AI — What It Actually Is

Sana (sana.ai, Swedish) pivoted from enterprise learning into **Sana Agents** — unified workspace assistant competing with Glean and ChatGPT Enterprise. What makes it feel alive isn't magic, it's three concrete design moves:

- **One box, many destinations.** Core UX is a single chat input that routes to "agents" (Meetings, Search, Writer, Data Analyst, Coder). Unlike ChatGPT, doesn't make you pick a mode — infers intent from your text and picks the tool, showing the pick as a revocable chip. **Ed.it pattern:** one chat box, auto-detect "edit this" / "find this clip" / "show me ideas" / "change captions," surface the chosen action as a chip.
- **Workspace-wide context memory.** Sana indexes Slack, Notion, Drive, Gmail, calendar, meeting recordings into a semantic + symbolic "Context Engine." When you ask a question, it shows *why* it knows ("Because you met with Sarah Tuesday about X"). The "alive" feeling = **visible reasoning over personal data**, not just answers. **Ed.it pattern:** every edit suggestion shows receipts — "Because this clip has a laugh at 0:14, and you usually cut to B-roll on laughs."
- **Agents that run while you're away.** Sana's Agent Builder lets you create persistent workers (e.g., "every Monday summarize last week's calls"). Product feels proactive because work happens without you initiating. **Ed.it pattern:** background daemon that, when you dump clips into `~/Movies/Ed.it Inbox/`, runs a Gemini pass overnight and greets you with "I watched 4 clips from Saturday — 2 worth editing, want to see?"

Sana's onboarding connects integrations *before* you ever chat — wants context before conversation. Ed.it equivalent: first-run scans `~/Movies`, DCIM, Downloads for .MOV/.MP4, asks "is this you?" on three sample frames, builds a taste profile from your last 20 IG posts (if user pastes handle).

## 2. Other "Alive" Products — What They Each Do Right

- **Granola.** Sits on top of your meeting. Doesn't transcribe live — takes your sparse notes + audio + post-meeting generates a structured doc in *your voice*. Magic: **you were doing something anyway, and it just got smarter.** Ed.it equivalent: user is editing anyway. While they trim, Ed.it silently runs Whisper/Gemini on untrimmed portions so when they ask "what did I say about grace?" it already knows.
- **Rewind.** Continuous background screen + audio capture, local-only, indexed with CLIP+Whisper. "Ask your past." Alive = **you never had to save it, yet it's there.** Ed.it equivalent: every clip auto-indexed the moment it lands in a watched folder. "That clip where I was laughing on the couch" just works.
- **Perplexity Comet / Arc's Max.** Browser-level awareness — AI knows every tab, can act across them. Pattern: **"command bar above everything"** (cmd-T summons AI with page context auto-attached). Ed.it equivalent: global hotkey from anywhere on macOS opens Ed.it chat with whatever clip is in Finder selection auto-attached.
- **Cursor / Claude Code.** Feels smart because of **visible tool use** + **streaming reasoning**. You watch it read files, run commands, fail, retry. Trust from transparency. Ed.it equivalent: when rendering, don't show a generic bar — show "Cutting at 0:14… applying Warm LUT… burning captions… [log scroll]." Every action narrated.
- **Lindy / Gumloop.** Trigger-based agents. Pattern: **natural-language triggers** ("when a new email from X comes in…"). Ed.it equivalent: "when I drop a clip tagged #worship, apply the worship preset automatically."
- **Pi (Inflection).** RIP. What made it warm: **short sentences, natural pauses, curiosity-first replies** ("oh interesting — tell me more"), refusal to dump info. Asked questions back. Remembered *emotional* facts ("you mentioned your mom was sick last week, how is she?"). Ed.it equivalent: don't just remember style prefs — remember *context* ("this is your first video back after finals week, want to start gentle?").
- **Replika.** The lesson (not the vibe): **consistent persona + low-stakes daily check-ins.** A once-a-day "good morning" beats a hyperactive push system.

## 3. Proactive Behavior — Implementation Patterns

**File watching on macOS:** FSEvents via `fswatch` or Swift `DispatchSource.makeFileSystemObjectSource` — far cheaper than polling. Cross-platform in Electron: `chokidar` (wraps FSEvents/ReadDirectoryChangesW/inotify). Python backend: `watchdog` standard — set `Observer` on `~/Movies/Ed.it Inbox/` with debounce (don't fire until 3s of no new writes — clips finish copying).

**Daemon pattern on Mac:** ship a `launchd` `.plist` in `~/Library/LaunchAgents/com.edit.watcher.plist` with `RunAtLoad=true` + `KeepAlive=true`. Daemon is thin Python process watching folders + enqueuing jobs into local SQLite-backed queue. Electron app reads queue and pulls results when open. How Rewind, Raycast, Granola all work — lightweight daemon + rich UI app that talks to it.

**Context inference cheap wins:**
- **Time of day:** `datetime.now().hour` → "Good morning/afternoon/evening." Bonus: if last-active <2 hours ago, skip greeting entirely (nothing feels more robotic than "Good morning!" at 3pm after lunch).
- **Calendar:** read macOS Calendar via `EventKit` (Swift) or AppleScript bridge. "You have worship team at 7pm — want this ready by 6?"
- **Recent activity:** track last 10 edits in JSON log. "You've been doing worship edits this week — continue that style?"
- **System state:** low battery → don't suggest renders. Wi-Fi vs hotspot → defer Gemini uploads.

**Soft suggestions vs interruptions:** rule from Granola/Linear: **suggestions live in a dedicated zone**, never interrupt active work. Pattern: persistent left-sidebar "Ed.it noticed" panel with 1–3 ambient cards. Never a toast, never a modal. Card has "apply" / "not now" / "never suggest this again." The "never" option is the trust-builder — proves the AI listens.

## 4. Personalization That Feels Genuine

**Hybrid memory** (what Sana, ChatGPT, Claude Projects all converge on):
- **Symbolic layer (SQLite/JSON):** structured facts. `user.preferred_lut = "Naomi_Worship_Warm"`, `user.caption_style = "submagic"`, `user.avg_cut_length_seconds = 3.2`. Fast, explainable, editable in UI.
- **Vector layer (Chroma / LanceDB / sqlite-vec):** embeddings of past conversations, decisions, feedback. "Find times the user rejected a suggestion like this."
- **Episodic log:** raw chronological transcript with timestamps. Ground truth for re-deriving everything.

**Memory writes — when, what, how much.** ChatGPT's rule (the right one): write memory **only when the user says something durable about themselves or expresses a preference.** Signals: "I prefer…", "always…", "never…", "I'm a…", explicit "remember that." Don't write every message. <1 memory per 10 user turns. **Implicit writes:** when user rejects a suggestion 3 times in a row, write `user.dislikes("jump cuts on worship")`. When they accept same variation across 3 renders, write `user.prefers("variation B shape")`.

**Style learning concretely for Ed.it:**
1. Every render, save **style fingerprint JSON**: `{avg_cut_duration, caption_style, lut_id, music_ducking_db, zoom_freq, color_temperature}`.
2. Every user edit after render = correction signal. If they lengthen a cut, nudge `avg_cut_duration += 0.1s` for that content mode.
3. Aggregate into taste vector per content mode (talking_head / worship / lifestyle). This is the "style profile" Claude reads when planning next edit.
4. Surface it: "Your taste" page showing "You tend to: warm grade (94%), 2.8s cuts, Submagic captions, 85% music duck." **Editable** — Naomi drags slider to shift her own profile. Makes memory *hers*, not a black box.

## 5. Greetings and Warmth

**Opening pattern (Pi-inspired):** `{time_greeting}, {first_name}. {context_hook if present else silent}.`
- First session of day: "Good morning, Naomi. I watched the 3 clips you filmed last night — want to start with the sunset one?"
- Same-day return: no greeting, just "Welcome back. Where were we?"
- Specific: "Hey Naomi — it's been 4 days. I noticed you filmed Saturday at church. Want me to rough-cut it?"

**Randomization without random:** keep a bank of 5–8 variations *per context* (first-of-day, returning, after-render, stuck). Rotate but weight by recency (don't repeat within 3). Never generate greetings at inference time — they'll feel off.

**Tone rules (Anthropic's public guidance for Claude is a template):** playful when user is casual ("lol"), direct when terse, warm but never saccharine. Never "Absolutely!" "Certainly!" "I'd be happy to!" — tool-tells. Match user's punctuation energy (lowercase → lowercase). For faith-adjacent context, treat with reverence — don't crack jokes on worship clips, do on lifestyle.

## 6. Multi-Version + Taste Pattern

Why Midjourney's 4-grid and Suno's 2-track feel smart: **commitment aversion removed from the user and placed on the AI.** Instead of "here's my best guess, is it right?" it's "here are 3 takes, which feels like you?" User becomes a **curator**, which feels more empowering than being a critic.

**Concrete Ed.it pattern:**
- Every render produces **3 variations** by default: `(A) Safe` (current style baseline), `(B) Stretch` (pushes one dimension — faster cuts, or more negative space), `(C) Wild` (different content mode's feel applied).
- UI: three thumbnails side-by-side, scrub-preview on hover, single click to pick.
- **The pick is the strongest training signal** — when Naomi picks B three times in a row, baseline shifts toward B: `user.taste_vector += 0.15 * (picked_variation - baseline)`.
- Show *why* each was different: "A: your usual 2.8s cuts. B: I shortened to 2.2s for energy. C: tried worship pacing on a talking-head clip — risky."
- Never let variations be too similar. Enforce minimum distance in style-fingerprint space.

**"Best" is never auto-picked.** Midjourney doesn't highlight a winner. Suno doesn't. The act of choosing is the product. If you must pre-rank, rank by *distance from user's baseline* (A closest, C furthest) so user understands the axis of variation.

## 7. Concrete Ed.it Build Order

1. launchd daemon watching `~/Movies/Ed.it Inbox/` with chokidar debounce.
2. SQLite + vector store hybrid memory, seeded from first-run onboarding (3 taste questions + analyze 5 existing edits).
3. Chat UI with time-aware greeting bank and context chips.
4. 3-variation renders as default, never 1.
5. "Ed.it noticed" ambient sidebar, never toasts.
6. Visible reasoning everywhere — every suggestion shows receipts.

## Key Relevant Files in Project
- `/Users/naomiivie/Social Media/ai_video_pipeline.py` (Gemini + Whisper core — already the brain)
- `/Users/naomiivie/Social Media/davinci-resolve-mcp/` (optional pro-user path)
- `/Users/naomiivie/Social Media/presets/*.cube` (3 LUTs = 3 style profiles seeded out of the box)
