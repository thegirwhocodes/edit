# 05 — Evaluation and Reliability

*How we tell whether Ed.it is getting better or worse, and how we keep it from wrecking a user's timeline.*

Fifth doc in the Ed.it series. 01 covered frameworks, 02 the agent loop, 03 tools and MCP, 04 multi-agent coordination. This one covers the part that decides whether any of that works in a creator's hands: evaluation, observability, and guardrails. None of the interesting agent patterns matter if you can't tell whether a prompt change made the product better or worse. Eval is not a "later" concern for agents — it is what lets you iterate at all.

---

## 1. Why evaluating agents is hard

A deterministic function is easy — same input, same output, one assertion covers it. An agent is not that. Given the same prompt it can sample a different first token and take a different tool path, get a different response from Gemini because the model shifted under it, get a different tool result because the file on disk changed or the Resolve project drifted, or loop for 4 turns one day and 22 the next on the same brief.

"Correctness" is multi-step and trajectory-dependent. A brief like *"make a 30-second reel from this sermon, add captions, use the warm LUT"* has a dozen valid trajectories. Some are cheap and good, some expensive and good, some look good but silently dropped the captions. `agent(prompt) == expected_video_bytes` is nonsense — there is no canonical byte sequence.

Unit tests are still necessary, but they only cover parsers, tool wrappers, and prompt templates. They do not cover "did the agent produce a video the creator would actually post." For that you need layered evals.

---

## 2. The three layers of evaluation

A pyramid. Unit at the base (cheap, many), trajectory in the middle, outcome at the top (expensive, few).

**Unit.** Each tool, parser, and prompt template tested in isolation. `cut_clip(input, 0, 5.2)` produces a 5.2-second file; the JSON response parser survives a trailing comma; the system prompt template renders with an empty tool list. Pytest, deterministic, sub-second. Good looks like: every tool has a happy-path and failure-path test, green on every PR.

**Trajectory.** The sequence of tool calls and arguments the agent actually produced. "Did it pick the right tools in the right order?" You capture the full trace (prompts, tool calls, tool results, final answer) and either compare to a reference trajectory or assert invariants: did it call `detect_silence` before `cut_clip`? Did it ever call `write_file` outside the project dir? Did it hit Gemini before consent? Good looks like: traces saved as structured JSON, invariants run as assertions over each trace.

**Outcome.** Did the user's task actually get done? The only layer the creator cares about. Did the render succeed, is duration within tolerance, are captions present when asked, does the LUT look right, does the music match. LLM-as-judge and human review live here. Good looks like: a scored rubric per dimension, with a human calibration set the judge is measured against.

You need all three. Unit stops broken tools shipping. Trajectory catches the agent doing the right thing the wrong way. Outcome tracks "is this product good."

---

## 3. Eval data strategies

You cannot evaluate what you have no tasks for. Three sources, ascending cost and quality.

**Synthetic tasks.** A strong model generates briefs: *"cut a 45-second highlight from a 20-minute podcast,"* *"make a cinematic B-roll montage."* Cheap, scalable, covers the obvious space. Weakness: it's what the model thinks creators ask for, not what creators actually ask for. Bootstrap to 50-100 tasks, no further.

**Real user sessions replayed.** Highest-signal, because it is the distribution you serve. Capture full traces in production, anonymize, replay the initial brief against new agent versions. Privacy is the hard part — sermon footage and personal video need consent at capture time and redaction before landing in an eval set. Bake this into the Ed.it ToS from day one; retrofitting consent is painful.

**Hand-written golden sets.** The team writes 20-50 briefs with expected outcomes. Slow and expensive, but the gold standard because you know exactly what "good" means. For Ed.it v1 this is the most important artifact.

Bootstrap with zero users: 20 hand-written golden tasks, pad with 30 synthetic, instrument so the first 100 real sessions are captured, swap synthetic for replayed real sessions as they arrive.

---

## 4. LLM-as-judge

A judge model scores agent output against a rubric. Cheap, scalable, the only way to grade subjective outcomes like "does this edit match the brief."

**When it works.** Coarse-grained judgments with clear rubrics — "is this JSON valid," "does this caption match the audio," "is this explanation grounded in the provided snippet." Frontier models (GPT-4 class, Claude Opus class, Gemini 2.5 Pro class) correlate 0.7-0.9 with human raters on these.

**When it doesn't.** Fine-grained aesthetic calls ("is this pacing cinematic"), anything needing taste the model lacks, anything adversarial where the agent under test can influence the judge. Judges have known biases: position bias in pairwise comparisons, length bias, self-preference for their own family.

**Validate the judge.** The step everyone skips. Before trusting a judge on 200 tasks, hand-rate 30 and check correlation. 60% agreement means noise, not a judge. 85% means you can trust it for regression detection but not for absolute quality claims.

**Judge-of-judges.** Who grades the grader? You hit a human floor eventually. Budget a weekly hour of team time to spot-check.

**Concrete rubric for Ed.it.** The outcome question is *"did this render match the prompt?"* A shippable rubric:

```python
# edit/eval/judge_rubric.py
JUDGE_SYSTEM = """You are evaluating a video edit against a creator's brief.
Score each dimension 0-5. Be strict. 5 means a professional editor would
ship this as-is; 3 means it technically satisfies the brief but has clear
flaws; 0 means the dimension is absent or broken.

Return JSON only, no prose."""

RUBRIC = {
    "pacing": "Cuts feel intentional; no dead air; no rushed transitions.",
    "captions": "Captions present if the brief asked; accurate to audio; "
                "readable on mobile; no overlap with faces or lower thirds.",
    "color_lut": "The requested look (warm, cinematic, flat, etc.) is "
                 "applied consistently; no clipping; skin tones plausible.",
    "music": "Music matches the brief's mood; ducks under speech; no "
             "abrupt cuts at the end.",
    "brief_fidelity": "The final render answers the brief. Duration within "
                      "10% of requested length; all named elements present.",
}

JUDGE_USER_TEMPLATE = """BRIEF:
{brief}

RENDER METADATA:
- duration: {duration_s}s
- has_captions: {has_captions}
- lut_applied: {lut_name}
- music_track: {music_track}

RENDER TRANSCRIPT (auto-generated from output):
{transcript}

KEYFRAME DESCRIPTIONS (Gemini over sampled frames):
{keyframes}

Score each dimension of the rubric and justify in one sentence.
Return: {{"pacing": {{"score": int, "reason": str}}, ...}}"""
```

The judge does not watch the video directly — it grades a structured summary (transcript, keyframes described by Gemini, metadata). Cheaper, more deterministic, easier to debug than video-in-the-prompt judging. Validate against 30 human-rated edits before trusting aggregate scores.

---

## 5. Behavioral eval frameworks

The landscape as of early 2026:

- **Braintrust.** Hosted; strong SDK for offline eval runs and experiment comparison; good tracing UI. Pick this if you want the fastest path to "compare two prompt versions side by side."
- **LangSmith.** Tight LangChain integration, decent for anyone else; traces, datasets, eval runs. Best if you are already in LangChain.
- **Langfuse.** Open source, self-hostable, OpenTelemetry-native; decent UI, growing eval features.
- **OpenAI Evals.** The original model-eval framework; code-first, GitHub-based; fine for model comparison, clunky for agent trajectories.
- **Inspect (UK AISI).** Open source, Python-native, designed for capability evals and red-teaming; excellent for structured rubric evals and safety testing. Heavier than Braintrust but more rigorous.
- **Ragas.** RAG-specific metrics (faithfulness, context precision); useful if you add retrieval to Ed.it, not for core editing eval.

**Pick for Ed.it.** Self-hosted Langfuse for traces and online telemetry, Inspect for offline golden-set evals. Ed.it is a desktop app, single-user, local-first. Langfuse runs in a Docker container next to the app; Inspect is a Python CLI in CI. No vendor lock-in, no sending creator footage to a third-party dashboard. If the team later wants hosted, Braintrust has a similar dataset format and is the easiest migration.

---

## 6. Offline vs. online eval

Different questions.

**Offline.** Run the agent against a fixed dataset before shipping. Answers: "does this change improve scores on my golden set?" Fast, deterministic, cheap. Weakness: the dataset is stale the moment creators start doing things you didn't anticipate.

**Online.** Instrument every real session and monitor scores, costs, and failures in production. Answers: "are real creators having a better or worse experience this week?" Catches the long tail. Weakness: slow signal and noisy.

Ed.it needs both. Offline gates merges on PRs that touch prompts or tools. Online traces flow into Langfuse for every real edit, with weekly review of regressions, cost outliers, and failed renders.

---

## 7. Regression testing

The classic trap: you tweak the system prompt to fix one failing case, it fixes that case, and silently breaks five you didn't look at.

Mitigation is mechanical:

1. Every prompt lives in a versioned file (`prompts/editor_v0_4_1.md`), not inline in code.
2. PRs that change a prompt trigger the nightly eval suite.
3. The CI job fails if golden-set pass rate drops or any judge dimension regresses more than 0.3 points on average.
4. The PR description auto-includes a per-task score diff. Reviewer sees "task 7 went from 4.2 to 2.8" at a glance.

Once you have users, add **A/B testing**: route 10% of sessions to the candidate prompt, compare aggregate scores and cost after a few hundred sessions, ship the winner. Langfuse and Braintrust both handle experiment assignment. Matters less for a single-user desktop app at first, essential once Ed.it has beta creators.

---

## 8. Guardrails

Checks that run around the agent — on inputs before the model sees them, and on outputs before they reach the user or a side-effecting tool.

**Input.** PII detection (Presidio, Llama Guard). Profanity / policy check on the brief. Injection detection for prompts that include file contents from disk (e.g., a video file with malicious XMP metadata).

**Output.** Hallucination detection on factual claims in captions. Format validation (tool call JSON valid, final answer in schema). Cost and length caps.

**Libraries.** OpenAI Agents SDK's `Guardrail` primitive is simplest — a function that raises if the check fails, wired into the loop. NVIDIA NeMo Guardrails is heavier, rule-based, YAML-configured, good for declarative policies. Llama Guard is Meta's local safety classifier, free. For Ed.it: Agents SDK primitive for structural checks, Llama Guard for content moderation, Presidio for PII.

**Block vs. warn vs. log.** Block when the action is irreversible or dangerous (filesystem write outside project dir, external upload without consent). Warn when recoverable but suspicious (unusually long render, 20+ tool calls). Log everything.

**Ed.it-specific risks.** Three that matter:

- *Shell commands touching files outside the project.* Every filesystem tool takes a `project_root` arg and rejects paths that resolve outside it. Block, not warn. Enforce at the tool-wrapper layer, not the prompt — the model will forget, the wrapper won't.
- *Uploading user footage to Gemini without consent.* On first Gemini call per project, prompt the user: "Ed.it will send frames from your clip to Google for analysis. Allow?" Persist per project. Without consent the Gemini tool is unavailable and the agent is told so in the system prompt.
- *Generating offensive captions.* Run captions through Llama Guard before burning them in. On flag, regenerate once with a "be conservative" directive; if still flagged, surface to user with the flagged span highlighted.

---

## 9. Cost and latency observability

You cannot ship an agent without per-session cost tracking. The 30-turn runaway isn't hypothetical — it's what happens the first time a creator gives an underspecified brief and the agent keeps sampling frames.

**Track per session.** Tokens in/out per model per turn. Dollar cost per turn, cumulative. Latency breakdown: LLM wait, tool wait, network, local compute (FFmpeg render time usually dominates). Tool call count per tool. Turn count.

**Stack.** OpenTelemetry for instrumentation (every tool call and LLM call becomes a span), Langfuse for the UI. Cost per session on a dashboard, sorted descending, weekly review. Any session above p99 gets manually inspected.

**Runaway detection.** Hard-cut at a step budget (30 turns) and cost budget ($3/session). On hit, the agent is told "budget exhausted, summarize what you did and hand back to the user." Friendlier than a silent crash and lets the user re-scope.

---

## 10. Failure recovery

Tools fail. Models fail. What does the agent do next.

**Failure taxonomy.** *Transient* (network blip, rate limit): retry with exponential backoff, cap 3 attempts. *Recoverable* (bad arguments, unsupported format): surface the error back as a tool result, the model rewrites and tries again — the 90% case. *Fatal* (Resolve crashed, disk full): escalate to user with a clear message and a next step.

**Loop detection.** Three identical `cut_clip(start=0, end=5)` calls in a row is a loop. Hash the (tool_name, args) tuple per turn; if the same hash appears twice consecutively, inject: "You just called this tool with these exact args. Something different is needed." If it continues, break out with a user-facing message.

**Escape hatches.** An explicit `ask_user` tool. The prompt should encourage it when confidence is low. A stuck agent asking "30-second or 60-second cut?" is strictly better than one guessing and rendering the wrong thing.

**Ed.it-specific failures.**
- *FFmpeg render failed.* Inspect stderr; common causes are codec mismatch (re-encode input) and missing filter (degrade to simpler). If neither works, surface the error.
- *Resolve crashed.* Detect via MCP heartbeat; don't retry (state is lost). Tell the user, offer FFmpeg-only mode.
- *Gemini hit quota.* Fall back to local models (WhisperX for audio, local VLM for frames) if available; otherwise tell the user and pause.

---

## 11. The reliability stack for Ed.it v1

Shortest checklist that would let me sleep at night shipping v1:

- **Unit tests on all tools.** Happy-path and failure-path for every wrapper. Green CI gate on every PR.
- **20-task golden set of edit briefs with expected outcomes.** Hand-written, in `edit/eval/golden/`. Each task has brief, input media, expected duration, expected elements (captions? LUT? music?).
- **LLM-judge rubric with 5 rated dimensions.** Pacing, captions, color/LUT, music, brief fidelity. Validated against 30 human-rated edits.
- **OTEL traces on every session.** Spans on every tool call and LLM call, exported to local Langfuse.
- **Step budget 30, cost budget $3/session, hard-cut.** Exceeded = graceful handoff.
- **Filesystem write guardrail.** Tools reject paths outside configured project root. Enforced in the wrapper, not the prompt.
- **Consent guardrail on Gemini uploads.** First call per project prompts the user, decision persisted.
- **Llama Guard on generated captions.** One regeneration retry, then surface to user.
- **Nightly eval on every prompt-branch PR.** Fails on pass-rate drop or per-dimension regression > 0.3. Per-task score diff auto-posted to PR.

Ship all nine. Everything else — A/B testing, online regression detection, fancier judges — is earned once the v1 stack is stable and real creators are generating real traces.

---

## Caveat

Library and framework details (Braintrust, LangSmith, Langfuse, Inspect, NeMo Guardrails, Llama Guard, Presidio) reflect training knowledge through January 2026; web access was not used to verify current versions or pricing. Before committing to any of these for Ed.it, check the current project state for breaking changes. The architectural patterns (three-layer eval, judge validation, offline/online split, guardrail taxonomy, step/cost budgets) are stable and should outlast any specific library choice.
