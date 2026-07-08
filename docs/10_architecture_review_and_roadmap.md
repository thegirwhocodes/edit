# ADR-001 — Ed.it: Architecture Review, Honest Verdict & Build-It-By-Assembling-The-Parts Roadmap

**Status:** Proposed
**Date:** 2026-06-18
**Author:** Architecture review (deep pass over every Ed.it conversation, the codebase, recent real usage, and the 2026 market)
**Deciders:** Naomi

---

## 0. The question you asked

> *"Do deep research into every intention, question, conversation I've ever had about this editing agent — is it set up for success? Is it structured properly? How can it become what I want it to become? Do other such tools exist? How do we build it — maybe assemble the separate parts that exist and bring them all together?"*

Short answers, up front:

1. **Is it structured properly?** Yes — the *agent harness* is genuinely well-built and faithful to the research. This is the hard, boring part most people get wrong, and you got it right.
2. **Is it set up for success?** Half. The skeleton is excellent; **the muscles aren't attached yet.** Ed.it today is a color-grade + crop + transcode wrapper. The one feature you asked for *first and most* — Submagic word-by-word captions — is described everywhere in the prompts but **exists nowhere in the code.**
3. **How does it become what you want?** Stop adding harness. Pick **one** mode and make it genuinely great end-to-end by *wiring in parts that already exist* (WhisperX, libass, scene detection, loudness). Then add the "alive" layer (real proactivity). Details in §6–§8.
4. **Do other tools exist?** Many — but they're almost all cloud GUIs. A **local-first, agent-native, taste-learning** editor is real whitespace. See §5.
5. **How do we build by assembling parts?** Every capability is downloadable. The value is the *seams*. Integration map in §7.

---

## 1. The north star (what you actually said you wanted)

Synthesized from the build session (3ca6f6d6), the original DaVinci session (4db243fe), and the agent-research session (6abf9016). Your own words:

- **"I want a SUPER Intelligent AI Agent that can edit your videos for you."**
- **"I want it to feel like your video editing friend — it's like fully an agent, and I want it to be intuitive."**
- **"When you open it, it can say 'I noticed you did xyz / created this folder, Naomi — would you like to turn it into a video?'"** (proactive, context-aware).
- From March, the founding ask: **"find a way to do it yourself please"** and, about Submagic captions, **"I want it like this — exactly — figure out how to make it like that."**
- Local-first because **"people don't have to upload stuff and we don't have to pay for server storage"** (privacy + cost).
- Faith/worship-aware: **"this is a Christian guitar song I wrote from scratch — I want users to feel it... I don't want the captions to take away from the music."**

**The north star in one line:** *A proactive, local, taste-learning editing collaborator that turns raw clips into finished, on-brand social video — and feels like a friend who already knows your style.*

Three non-negotiable pillars fall out of that:

| Pillar | What it means | Status today |
|---|---|---|
| **Agent-native** | You describe the edit in words; it executes end-to-end | ✅ harness is here |
| **Real editing depth** | Captions, cuts, reframe, grade, ducking — actually applied | ❌ mostly missing |
| **Alive & personal** | Proactive greetings, learns taste, remembers | ⚠️ scaffolded, inert |

---

## 2. What was built (and it's good)

Ed.it is a Python package (`src/edit/`) wrapping the **Claude Agent SDK** with an in-process MCP tool server, a FastAPI + SSE web UI, an Electron shell, SQLite memory, a traces DB, and cost/budget controls.

**What's genuinely strong — keep all of it:**

- **Clean agent loop** (`agent.py`): one SDK client, curated tool list, Sonnet 4.5, `max_turns`, thinking budget, hard cost ceiling. Textbook.
- **Disciplined tool design** (`tools/*.py`): every tool is a verb-named wrapper over a *tested* FFmpeg/Gemini call, never raw shell, with structured `{code, message, hint}` errors and an `ok`/`safe_path` sandbox. This is exactly what the research (`docs/06`) prescribes.
- **Prompt-cache-aware system prompt** (`prompts.py`): static head + dynamic memory tail, so the bulk cache-hits. Real cost engineering.
- **Memory schema** (`memory.py`): `user_profile`, `preferences` with a proper **supersedes chain**, `projects`, `events`, `memory_items` + **FTS5** mirror with sync triggers. Room left for `sqlite-vec`. Well thought out.
- **Traces + budget** (`traces.py`, `server.py`): per-turn cost/tokens/tool-calls/outputs logged; soft daily cap + hard session cap. Most side projects never get here.
- **Tests** (16): ffmpeg tools, render tools, memory round-trips.
- **Docs** (`docs/00–09`): the research that justifies every choice. Rare and valuable.

**Verdict on the harness: A-.** It is structured properly. Do not rebuild it.

---

## 3. The gap — vision vs. binary

Here is the uncomfortable, important part. The *prompts and modes describe a rich editor; the tools deliver a thin one.*

### 3.1 The capabilities that exist
- `probe_video`, `trim_clip`, `concat_clips`, `extract_audio`, `transcode` — solid FFmpeg primitives.
- `make_contact_sheet` — frame grid.
- `render_social_clip` / `render_variations` — **9:16 crop + a color filter + optional 6-second bottom title.** The "modes" (`talking_head`, `worship`, `lifestyle`, `hair_vlog`) are **just FFmpeg `eq`/`colorbalance`/`unsharp` strings.** The "variations" (Safe/Stretch/Wild) differ only by **crop tightness and contrast.**
- `describe_video` — Gemini watches a clip and returns text.
- 4 memory tools.

### 3.2 The capabilities the vision requires but the code lacks
- **❌ Word-by-word captions (Submagic style).** Your #1 ask since March. The `talking_head` mode literally says *"caption-forward… active-word yellow highlight"* — but **no transcription and no caption rendering exist.** `extract_audio` produces a 16 kHz WAV "for Whisper" — but **there is no Whisper.** `pyproject.toml` has no `whisperx`, no caption library. The captions are vaporware in the prompt.
- **❌ Content-aware cutting.** No silence/filler trimming, no scene detection, no "cut to the hook." `describe_video` *could* inform cuts, but nothing consumes its output to actually cut.
- **❌ Auto-reframe / speaker tracking.** Crop is a static center-crop, not subject-aware.
- **❌ Real LUTs / grade.** `docs` and memory reference `.cube` LUT presets; the code uses approximate `eq` math instead.
- **❌ Music ducking, speed ramps, transitions.** All in the vision, none in the code.
- **❌ Proactivity.** The "greeting" is a **static client-side `Good morning, Naomi` string** (`index.html:332`). No file watching, no "I noticed you added clips," no context.
- **❌ Memory that actually fills.** The schema is great but **inert** — recent real sessions wrote nothing to it. Taste-learning can't happen if memory stays empty.

### 3.3 What actually happens when you use it (evidence)
- **`ec976ddd` (2026-06-08, "upgrade the video as you best see fit"):** Ed.it called `transcode` to upscale 1080→1440p, hit **"No space left on device"**, retried smaller, and finished. It did **not** use `render_variations`, did **not** pick a creator mode, did **not** add captions, did **not** call Gemini, did **not** write memory. "Upgrade" collapsed to "upscale resolution." This is the single most telling artifact: *the agent does the shallow literal thing because the deep things aren't tools yet.*
- **`de48c285` (2026-06-09, "so where is it?"):** Project-root confusion — the uploaded file landed in one root while the agent was sandboxed to another, and it had to ask you to move the file. A real plumbing bug.

**Verdict on capability depth: C.** The agent is smart; its hands are mostly empty.

---

## 4. Bugs & rough edges found in this review

| # | Issue | Where | Fix |
|---|---|---|---|
| 1 | "Upgrade" → bare upscale, ignores the whole creative flow | observed in `ec976ddd` | Strengthen prompt + add real tools (captions/cuts) so "upgrade" *means* something |
| 2 | No pre-flight disk-space check before render | `render.py`, `ffmpeg.py` | Check free space vs. estimated output; fail early with a clear hint |
| 3 | Project-root / upload path confusion | `server.py` upload vs. agent cwd | One canonical `EDIT_PROJECT_ROOT`; upload + agent must share it |
| 4 | Captions promised in prompt, absent in tools | `prompts.py` vs `tools/` | Either build captions (recommended) or stop promising them |
| 5 | Memory never written in practice | end-to-end | Make `render_variations`' pick-callback actually call `memory_write`; add a light "remember this?" nudge |
| 6 | Greeting is static, not contextual | `index.html` | Drive greeting from project state (new files? last render?) — see §8 |
| 7 | `make_contact_sheet` frame stride hard-codes 30 fps × 2 | `render.py:390` | Derive stride from `probe_video` fps |
| 8 | libx264 = GPL; Electron ships closed | packaging | For personal use, fine. To distribute, build LGPL/dynamic-link or accept GPL (see §9) |

---

## 5. Does this exist already? The 2026 landscape

**The market splits three ways:** (a) cloud auto-clippers with a GUI, (b) generative tools, (c) a thin, *just-emerging* band of true agentic editors. Almost everything is cloud-upload.

**Auto-clippers (GUI + AI bolted on, all cloud):** Opus Clip, Submagic, Captions/Mirage, Klap, Vizard, Gling, AutoPod. The crowded middle. Loudest complaint everywhere: **"the AI picks the wrong moment and I fix it by hand"** — a *taste/control* gap, not a feature-count gap.

**Agentic editors (describe → it edits) — the new band, still all cloud:**
- **Descript "Underlord"** — sidebar chat agent on edit-by-text; can run Claude Sonnet 4.5.
- **Eddie AI** — conversational "assistant editor," pro rough cuts.
- **Mosaic** (YC W25), **Cardboard** ("Cursor for video editing") — NL → editable timeline, export to Premiere/Resolve.
- **Runway Chat Mode / Aleph** — NL in-context editing, but generation-first.
- **Adobe Firefly Assistant** — cross-app agent, beta; Premiere itself is still task-tools-in-timeline.

**The MCP→NLE pattern is real and proven** (validates your architecture): `samuelgursky/davinci-resolve-mcp` (~1.3k★, 342 tools), Premiere/Adobe MCP servers, `KyaniteLabs/mcp-video` (119 typed tools with preflight validation).

**Whitespace (no single competitor combines these):**
1. **Local-first / private** — only heavy-pro (DaVinci) or hobbyist tools run on-device. The June-2025 **CapCut rights backlash** ("perpetual, irrevocable license… including deleted drafts") makes *"your footage never leaves your machine"* a live, resonant pitch. The **Sora 2 shutdown (Apr 2026, ~$1M/day inference burn)** is your economics thesis in one data point: local compute has no per-minute credit meter.
2. **Agent-native** — the conversational editors are all cloud.
3. **Taste/personalization** — attacks the #1 complaint directly.

**Faith niche:** already crowded but **all cloud** — Pulpit AI, Sermon Shots, Choppity, Pastors.ai. The closest to your combined wedge is **The Pulpit App** (faith clips + *browser-local* data). General clippers (Opus has a church page) "optimize for viral hooks and miss quieter sermon moments" — exactly the worship-aware selection gap you named in March.

**Conclusion:** You are not late and not redundant. *Local + agent-native + taste-learning + worship-aware* is genuinely unoccupied. The risk isn't competition; it's **depth** — shipping real editing, not another wrapper.

---

## 6. Recommendation (the one decision that matters)

> **Stop widening the harness. Go deep on ONE mode, end-to-end, by assembling parts that already exist — and make memory actually write.**

Concretely: make **`talking_head` genuinely great** — because (a) it's your highest-volume content (40% per your own mix), (b) it needs the feature you've wanted longest (Submagic captions), and (c) it's the most demoable. A clip in, a captioned, tightened, properly-loud, on-brand vertical out — *that* is the moment Ed.it stops being a wrapper and becomes the friend.

Everything below serves that.

---

## 7. How to build it by assembling the parts (integration map)

**The thesis from the research is exact:** every capability is downloadable; the moat is the seams. A bare LLM emitting FFmpeg is ~65% correct and invents codecs; wrapped in retrieval + validation + a bounded self-critique loop it hits ~88% (ELLMPEG, MMSys 2026). You already own the best seams (agent loop, memory, traces). You're missing the *parts* and the *verification gate*.

### 7.1 The parts to wire (recommended picks)

| Capability | Part to assemble | License / cost | New Ed.it tool |
|---|---|---|---|
| Word-level transcription | **faster-whisper → WhisperX** (forced alignment) | BSD, local, $0 | `transcribe_clip` |
| On-device option | **WhisperKit** (CoreML, Apple Silicon) | MIT, local | (backend swap) |
| Word-by-word captions | **ASS/libass via FFmpeg** (`\k`/`\t` karaoke tags) — deterministic | LGPL | `add_captions` |
| Premium caption look | **Remotion** (`@remotion/captions`) when ASS isn't enough | paid >3 devs | (later) |
| Silence/filler trim | **auto-editor** | Unlicense, local | `tighten_clip` |
| Scene/highlight detect | **PySceneDetect** (+ **TransNetV2** for dissolves) | MIT, local | `find_moments` |
| "Find the hook" scoring | **Gemini 2.5 Flash native video** (~$0.32/hr) + rubric | cheap API | extend `describe_video` |
| Auto-reframe to 9:16 | face-detect (BlazeFace) + **TalkNet** active-speaker → smoothed crop (build it; AutoFlip is dead) | MIT, local | `reframe_vertical` |
| Loudness normalize | **FFmpeg two-pass `loudnorm` → −14 LUFS** | LGPL | bake into render |
| Real grade | ship `.cube` **LUTs via `lut3d`** instead of `eq` math | — | upgrade modes |

### 7.2 The seam you're missing: a quality gate

The research is blunt that this is where reliability lives. After any render, run **deterministic checks** before declaring success:
- caption sync + reading-speed + overflow (no clipped words),
- loudness at −14 LUFS (EBU R128),
- optional **VLM frame QA** (send a frame back to Gemini: "is the subject in frame, captions readable, aspect correct?").

Wrap the agent's edit as a **validated structured edit-spec (timeline/EDL JSON) → deterministic executor → preflight `ffprobe` gate → render**, with a **bounded ≤3-iteration** self-critique (past 3 it over-corrects). This is the single highest-leverage architectural addition.

### 7.3 What you already have that others must build
Agent loop ✅, memory with supersedes ✅, traces/cost ✅, local-first ✅, sandbox ✅. So the build is *additive*, not a rewrite — you are bolting capability tools and one verification gate onto a sound chassis.

---

## 8. The "alive" layer (deliver the feeling, cheaply)

The vision's emotional core — *"it feels like a friend who noticed"* — is currently a static greeting. Make it real with a tiny amount of code:

1. **Project-state greeting.** On UI load, the server reports: new files in `inbox/` since last visit, last render + its mode, the open project. Greeting becomes *"Welcome back — 3 new clips in your worship folder since Tuesday. Want me to rough-cut them?"* This is 90% of the "alive" feeling for 5% of the work, and needs **no daemon**.
2. **Optional file watcher** (`launchd` on macOS) later, for true ambient proactivity. Defer — the on-load version is enough to start.
3. **Make memory write.** Wire the variations pick → `memory_write`. Add one nudge: after a render, if the user reacts ("love it" / "too fast"), capture a `preference_set`. Taste-learning is the moat; it starts the day memory stops being empty.

---

## 9. Decisions to make (mini-ADRs)

| Decision | Options | Recommendation |
|---|---|---|
| **Caption engine** | A) ASS/libass (deterministic, fast, FFmpeg-native) · B) Remotion (premium, heavy, license >3 devs) | **A now, B later** for a "premium" look toggle |
| **Transcription** | A) WhisperX local (BSD) · B) WhisperKit on-device · C) cloud (Deepgram/AssemblyAI) | **A** (local-first thesis); **B** if you want zero-API on Apple Silicon |
| **Edit execution** | A) agent emits FFmpeg directly · B) agent emits validated EDL/JSON → deterministic executor | **B** — determinism + caching + a real QA gate |
| **Scope of v-next** | A) all four modes shallow · B) one mode (talking_head) deep | **B** — depth over breadth |
| **Distribution** | personal use · share with others | Personal now (signing already wired). To share: LGPL FFmpeg build, then notarize. Decide *before* you invite anyone |
| **Product wedge** | generic creator tool · faith/worship-first · local-first privacy | **Local + worship-aware taste**, marketed on privacy. It's the unoccupied corner |

---

## 10. Roadmap — the next milestones

M1–M6 shipped (harness, Resolve opt-in, Electron, memory, variations, cost/traces). Proposed next:

- **M7 — Captions that match the dream (highest priority).** `transcribe_clip` (WhisperX) + `add_captions` (ASS/libass word-by-word, yellow active word). Wire into `talking_head`. *This closes the oldest, deepest gap.*
- **M8 — Content-aware editing.** `tighten_clip` (auto-editor silence trim) + `find_moments` (PySceneDetect + Gemini hook scoring). "Cut this down" becomes real.
- **M9 — Quality gate.** Validated edit-spec → `ffprobe` preflight → −14 LUFS loudnorm → caption-overflow check → optional VLM frame QA. Bounded self-critique.
- **M10 — Alive layer.** Project-state greeting + memory actually writing on variation picks. Optional file watcher.
- **M11 — Reframe + real LUTs.** Subject-aware 9:16 crop; ship `.cube` LUTs via `lut3d`.
- **M12 — Worship mode, truly music-first.** Phrase captions that breathe, ducking, warm LUT — the mode you most want to *feel* right.

**Sequencing logic:** M7 makes it impressive; M8 makes it useful; M9 makes it trustworthy; M10 makes it *yours*. Do them in order. Resist starting M11/M12 until one mode is great.

---

## 11. Consequences

**Easier after this:**
- "Upgrade this" finally produces a captioned, tightened, on-brand clip instead of an upscale.
- Memory starts learning your taste, so variations converge on *you* over time.
- A real demo exists — the thing you'd actually show someone.

**Harder / to watch:**
- More local dependencies (Whisper models, ffmpeg with libass) → packaging weight in Electron. Mitigate by bundling models lazily / on first run.
- The quality gate adds latency and cost (extra Gemini frame checks) — bound it, make it optional per render.
- GPL/libx264 if you ever distribute — resolve the build flags before inviting users.

**To revisit:**
- Multi-agent (subagents for parallel variation rendering) — the research says single-agent for v1; revisit only if variation latency hurts.
- `sqlite-vec` semantic memory — add when keyword FTS5 recall starts missing things; not before.
- Instagram Graph API posting — still a v2+ item; manual upload is fine until the editor itself is great.

---

## 12. One-paragraph answer to "is it set up for success?"

Yes, *structurally* — the agent loop, tool discipline, memory schema, traces, caching, and local-first stance are right, and they match what the best teams are doing in 2026. But Ed.it is a superb chassis with most of the engine still in the crate. It will become what you described — *a proactive, local, taste-learning editing friend* — the moment you stop polishing the chassis and start bolting in the parts that already exist: Whisper for words, libass for captions, auto-editor for cuts, loudnorm for sound, a verification gate for trust, and a memory that actually writes. None of that is research anymore. It's assembly. Go deep on `talking_head`, ship M7, and Ed.it crosses the line from wrapper to product.
