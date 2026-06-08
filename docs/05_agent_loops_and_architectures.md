# 02 — Agent Loops and Architectures

*Companion to `01_agent_frameworks.md`. This doc is opinionated. Where two patterns conflict, I pick one and defend it.*

---

## 1. The fundamental agent loop

Strip away every framework and an agent is a `while` loop around an LLM call. That's it. Everything else — ReAct, Reflexion, Plan-and-Execute, Tree of Thoughts — is a *prompting strategy* or a *control-flow wrapper* layered on top of this loop.

```python
# Minimum viable agent loop (~20 lines)
def run_agent(user_goal, tools, max_steps=50, budget_usd=1.00):
    messages = [{"role": "user", "content": user_goal}]
    spent = 0.0
    for step in range(max_steps):
        response = llm.invoke(
            messages,
            tools=tools,           # JSON schemas the model can call
            thinking={"enabled": True, "budget_tokens": 4000},
        )
        spent += response.cost_usd
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            return response.text   # agent says it's done

        if response.stop_reason == "tool_use":
            results = [execute_tool(tc, tools) for tc in response.tool_calls]
            messages.append({"role": "user", "content": results})

        if spent > budget_usd:
            raise BudgetExceeded(spent)
    raise StepLimitExceeded(max_steps)
```

Perceive (`messages` history + latest tool results) → reason (LLM call, optionally with extended thinking) → act (`tool_use` blocks) → observe (tool results appended) → repeat. Everything in the rest of this document is either (a) a smarter `llm.invoke(...)` prompt, (b) a smarter `execute_tool(...)`, or (c) a smarter stop condition.

---

## 2. ReAct (Yao et al., 2022)

The [ReAct paper](https://arxiv.org/abs/2210.03629) is the canonical "make an LLM use tools" pattern. It interleaved three kinds of tokens in a single completion:

```
Thought: I need to find the current CEO of Apple.
Action: search[current CEO of Apple]
Observation: Tim Cook is the CEO of Apple as of 2024.
Thought: That answers the question.
Action: finish[Tim Cook]
```

**Why it beat chain-of-thought-alone:** vanilla CoT hallucinates facts because the model never pauses to *verify*. Tool-calling-alone (no `Thought`) ran out of context on anything multi-hop because the model couldn't plan. ReAct's contribution was interleaving: the model is forced to narrate *why* each tool call is happening, and that narration doubles as scratchpad for the next step. It lifted HotpotQA and Fever accuracy meaningfully over CoT + Act baselines.

**Where it's still the default:** any open-source model that wasn't trained on structured tool use (most Llama finetunes, older Mistrals, early Qwen). LangChain's original `create_react_agent` is still this pattern with regex parsing of `Action:` / `Observation:` strings.

**Where it isn't anymore:** Claude, GPT-4/5, Gemini 2+. These models have native `tool_use` content blocks. You don't prompt `Action: search[...]`; you give them a JSON schema and they emit a structured `tool_use` block. The harness parses it. ReAct's narration has been absorbed into the model's internal thinking (extended thinking for Claude, reasoning tokens for o-series/GPT-5). Prompting `Thought:/Action:/Observation:` on a frontier model today is a regression — you're fighting the post-training.

**Pick:** if you're on Claude/GPT/Gemini, use native tool use. If you're self-hosting a base-ish model, ReAct-style prompting is still correct.

---

## 3. Reflexion / Self-reflection

[Reflexion (Shinn et al., 2023)](https://arxiv.org/abs/2303.11366) adds a second loop *around* the ReAct loop: after a trajectory fails (or scores below threshold), the agent writes a verbal self-critique into an "episodic memory," then retries the task with that critique prepended.

```python
for attempt in range(max_attempts):
    trajectory = run_react_agent(goal, memory=reflections)
    score = evaluator(trajectory, goal)
    if score >= threshold:
        return trajectory.final_answer
    reflection = llm.invoke(
        f"Goal: {goal}\nTrajectory: {trajectory}\nScore: {score}\n"
        f"Write 2-3 sentences on what went wrong and what to try differently."
    )
    reflections.append(reflection)
```

**When it actually helps:** tasks with a cheap, objective evaluator. Code generation with unit tests (HumanEval, MBPP) is the poster child — you can `pytest` the output. Also works for constrained reasoning benchmarks (AlfWorld, WebShop) where the environment gives a reward.

**When it's performative:** open-ended writing tasks, subjective quality ("is this thumbnail good?"), or any case where the "evaluator" is just another LLM call with no ground truth. The model writes a confident self-critique that doesn't actually correlate with quality, and the "improved" retry is lateral movement, not improvement. The [self-refine literature](https://arxiv.org/abs/2303.17651) has replication issues for exactly this reason.

**Pick:** only add Reflexion if you have a real evaluator — test suite, rendered video + CLIP similarity score, user thumbs-up/down dataset. For Ed.it: a render succeeding is a signal; "was this edit good" is not one an LLM can judge against itself reliably.

---

## 4. Plan-and-Execute / Plan-Solve

Pattern: a **planner** LLM call produces a list of steps up front; an **executor** (or loop of executors) runs each step without re-planning. Named in the [Plan-and-Solve paper (Wang et al., 2023)](https://arxiv.org/abs/2305.04091) and popularized by LangGraph's `plan-and-execute` template.

```python
plan = planner_llm.invoke(f"Break this goal into ordered steps: {goal}")
#  → ["Step 1: Load video", "Step 2: Detect silences", "Step 3: ..."]
state = {}
for step in plan.steps:
    state = executor_agent.run(step, context=state)
return synthesize(state)
```

**Why separate them:** planning is a one-shot reasoning task that benefits from the biggest model you can afford and extended thinking. Execution is repetitive tool-calling that benefits from a cheaper, faster model. Running Opus-class for 50 sequential tool calls when 45 of them are `ffmpeg -i input.mp4 ...` is a waste.

**When the planner should be bigger than the executor:** every time the plan has more than ~5 steps or the cost of a wrong plan is high (re-rendering a 4K timeline). Ed.it's video edit pipeline qualifies. Use Opus/GPT-5 as the planner, Haiku/Sonnet or gpt-4.1-mini as the executor.

**Frameworks using this pattern:** LangGraph (explicit `planner` + `executor` nodes), CrewAI (hierarchical crews), AutoGen GroupChat with a designated planner agent. The Claude Agent SDK doesn't enforce it but its subagent feature is exactly this — you `Task`-launch a planner subagent that returns a plan, then execute.

**Downside:** plans get stale. If step 3 reveals the video is 4K not 1080p, the pre-planned step 7 ("upscale to 4K") is now wrong. Mitigation: **re-planning checkpoints** — after every N executed steps, re-run the planner with updated context. LangGraph calls this `plan_step_checkpointing`. Don't skip it; pure plan-and-execute without re-planning fails on anything dynamic.

---

## 5. Tree of Thoughts / search

[Tree of Thoughts (Yao et al., 2023)](https://arxiv.org/abs/2305.10601) generalizes CoT from a linear chain to a tree: at each reasoning step, the model proposes *k* candidate next-thoughts, a value function scores them, and search (BFS/DFS/beam) picks which branches to expand. Paired with [Language Agent Tree Search (LATS)](https://arxiv.org/abs/2310.04406), which does full MCTS over agent trajectories.

**Hype check.** ToT and LATS win on Game of 24, crosswords, and toy puzzle benchmarks. I have seen no production deployment of ToT-style explicit search in a shipped LLM product. The reason is economic: expanding a tree with branching factor 3 and depth 5 is 243 leaf evaluations. At Opus pricing with extended thinking, that's $5-15 per query. Nobody is paying that for a user-facing feature when a single well-prompted Opus call with 16k thinking tokens gets you 90% of the benefit at 1% of the cost.

**Where search actually ships:** (a) inside model training (RLHF reward models, best-of-N sampling during eval), (b) code agents that compile-and-test candidate solutions in parallel — Cursor's "composer" and [SWE-agent](https://arxiv.org/abs/2405.15793) do lightweight branching, (c) self-consistency voting (cheap special case of search: sample N, majority-vote the answer).

**Pick:** don't build ToT into Ed.it. If you need branching, do best-of-3 rendering with a CLIP/aesthetic score and pick the winner. That's the industrial-strength version of search.

---

## 6. Multi-turn tool use with the modern harness

The big shift from 2023 to 2025: **explicit ReAct prompting died, replaced by harness-managed tool loops with interleaved thinking.** The Claude Agent SDK and OpenAI Agents SDK both work this way.

What the harness does for you that you used to write yourself:

- **Parse structured tool calls** from the response. No regex on `Action:`/`Observation:`. `tool_use` is a first-class content block.
- **Stream partial JSON.** Tool-call arguments arrive token-by-token. The harness buffers and parses incrementally so you can show "Claude is typing `ffmpeg -ss 00:01:23 ...`" in your UI before the call fires.
- **Handle retries on malformed tool calls.** If the model emits invalid JSON for a tool argument, the harness sends an error message back automatically and the model self-corrects. You don't write that retry loop.
- **Manage interleaved thinking + tool use** (Claude 3.7+, Claude 4, Claude Opus 4.7). The model thinks (extended thinking block), calls a tool, *thinks again after seeing the result*, calls another tool. Previously, thinking blocks were single-shot at the start of a turn. Interleaved thinking means the model reasons *between* tool calls in the same turn, which is the biggest quality jump for multi-step agents since ReAct itself.
- **Streaming interrupts.** User cancels mid-generation, the harness aborts cleanly, returns partial state, and the next turn picks up.
- **Prompt caching on the system prompt + tool definitions.** Long tool schemas (Ed.it will have 20+) get cached; subsequent turns in the same session hit the cache and cost ~10% of the first turn.

Concretely for Claude:

```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

async with ClaudeSDKClient(
    options=ClaudeAgentOptions(
        system_prompt="You are Ed.it, a video editing agent.",
        allowed_tools=["ffmpeg", "resolve_mcp", "gemini_analyze", "Bash"],
        max_turns=40,
        extra_args={"thinking": {"type": "enabled", "budget_tokens": 8000}},
    )
) as client:
    await client.query("Cut this podcast down to a 60-second reel")
    async for msg in client.receive_response():
        render_to_ui(msg)
```

You write ~10 lines. The SDK handles everything in the bullet list above.

**Anti-pattern:** writing your own ReAct regex parser in 2026. You are reinventing a bicycle that now has gears.

---

## 7. Long-horizon agents

Ed.it editing a 45-minute podcast into 8 clips is a **long-horizon task**: dozens of tool calls, hundreds of thousands of tokens of tool output (Gemini scene descriptions, Whisper transcripts, ffprobe dumps), potentially hours of wall-clock time. Four context strategies, in order of when to reach for them:

**1. Do nothing (context < 100k).** Claude's 200k context is genuinely usable. For a 20-step edit, just pile everything into messages. Don't over-engineer.

**2. Compaction (context 100k-800k).** Summarize older turns into a running "session summary" block, drop the raw turns. Anthropic's managed agent infrastructure does this automatically; in the SDK you can set up a compaction hook. The [Claude Code](https://docs.anthropic.com/en/docs/claude-code) `/compact` command is the reference implementation. **When to compact:** when old context is informational (we already processed that video segment) but not load-bearing (the current decision depends on it).

**3. Offload to files (any context size).** The [agentic context engineering pattern](https://www.anthropic.com/engineering/claude-code-best-practices): don't keep state in the message history, write it to disk. Gemini's scene analysis → `/tmp/scene_analysis.json`. Claude reads the file when needed via a `Read` tool call. This is how Claude Code handles repos that are 10x the context window. The model doesn't need *everything* in context; it needs the ability to *find* everything.

**4. Delegate to a subagent with fresh context.** When a subtask needs 50k tokens of intermediate reasoning that the parent doesn't need to see — e.g. "find the 5 best moments in this 2-hour video" — launch a subagent. It runs its own agent loop in a fresh context window, returns just the result (a JSON list of timestamps). The parent context stays clean. This is the Task tool in Claude Code. **When to use a subagent over compaction:** when the intermediate state is *throwaway*. Compaction preserves a summary; subagents discard everything except the return value. For Ed.it, "analyze each of 50 clips for B-roll opportunities" is a subagent job.

**Pick a hierarchy, not a single strategy.** Ed.it should use all four: raw messages for the current user turn, compaction hooks at 150k, file offloading for video analysis dumps, subagents for per-clip analysis.

---

## 8. Stop conditions

How does the agent know it's done?

- **Natural `end_turn`.** The model stops emitting `tool_use` blocks. This is the default and correct 80% of the time.
- **Explicit `complete(summary)` tool.** Register a sentinel tool the model calls when finished. Gives you structured output (the `summary` argument) and a clean stop signal. Recommended for user-facing agents — it forces the model to commit to "I'm done, here's what I did."
- **Step budget (`max_turns`).** Hard ceiling. Cheap insurance against infinite loops. Set it to 2-3x your expected worst case, not 10x.
- **Cost budget.** Track `usage.input_tokens + output_tokens` cumulatively, multiply by model pricing, abort if exceeded. Non-negotiable for any agent a user can trigger — without it, a runaway loop is an unbounded AWS bill.
- **`stopWhen` predicates** (AI SDK / LangGraph): a callable that inspects state after each step. `stopWhen=lambda s: s.render_complete and s.score > 0.8`. Most flexible stop.
- **Judge-based stop.** A separate LLM call asks "did the agent answer the user's goal?" Useful for QA in eval, too expensive for production per-turn. Use it in CI, not runtime.

**Opinion:** always use three together — `end_turn` naturally, `max_turns` as a safety, cost budget as the hard stop. The explicit `complete()` tool is nice-to-have and worth it for user-visible agents.

---

## 9. Common failure modes and fixes

**Infinite tool-call loops.** Agent calls `ffprobe`, gets same result, calls `ffprobe` again, forever. *Fix:* deduplicate. If the last 3 tool calls have identical `(name, arguments)`, inject a system message: "You have called this tool 3 times with the same arguments. Try a different approach or call `complete()`."

**Tool-call hallucination.** Model calls `cut_scene(start=..., end=...)` when the actual tool is `trim_clip(in_time=..., out_time=...)`. On frontier models this is rare with structured tool use, but happens on open-source models and on the first call before schemas are cached. *Fix:* strict JSON schema validation in the harness; return `tool_error` with the actual schema, let the model retry. The Agent SDK does this automatically.

**Forever-asking clarifying questions.** Agent asks "which clip?" → user says "the first one" → agent asks "the first by timeline order or upload order?" → etc. *Fix:* cap clarification turns at 2, then force the agent into a tool-execution turn with "Make your best guess and proceed; user can correct after." This is a system-prompt fix, not a harness fix.

**Confidently wrong output.** Agent cheerfully reports "I've edited your video into a 60-second reel" when the ffmpeg call failed silently and no file was written. *Fix:* every action tool returns a verifiable artifact (file path, file size, exit code, rendered frame hash), and the system prompt mandates "before reporting success, verify the output file exists and has nonzero size." Pair with a judge step on final delivery: "Does the claimed artifact match the file on disk?"

**Context rot / anchoring.** 30 turns in, agent is still referencing a decision from turn 2 that's no longer relevant. *Fix:* compaction with a "current state" block at the top — the model should see a fresh situation summary, not spelunk through 30 turns.

**Permission thrash.** Agent asks to run a bash command, user approves, agent asks for the next bash command, user approves... forever. *Fix:* pre-approved tool allowlist, and a "never ask again for tools matching this pattern" UX.

---

## 10. Concrete implementation skeleton for Ed.it

```python
# Ed.it agent loop — Electron (UI) ↔ Python (orchestrator) ↔ Claude Agent SDK
# Run inside the Python orchestrator, invoked per user edit request.

async def edit_video(user_goal: str, input_video: Path):
    # --- Stage 1: perception (subagent, fresh context) ---
    # Gemini 2.5 is better at native video understanding than Claude.
    # Subagent keeps 50k tokens of scene descriptions out of the main loop.
    analysis = await launch_subagent(
        model="gemini-2.5-pro",
        task=f"Analyze {input_video}: scenes, transcript, quality flags, "
             f"best moments, faces, silences. Return structured JSON.",
        output_file="/tmp/edit/analysis.json",
    )

    # --- Stage 2: planning (big model, extended thinking, one shot) ---
    async with ClaudeSDKClient(ClaudeAgentOptions(
        system_prompt=EDIT_PLANNER_PROMPT,
        allowed_tools=["Read", "complete"],   # planner only reads + commits plan
        max_turns=3,
        extra_args={"thinking": {"type": "enabled", "budget_tokens": 16000}},
        model="claude-opus-4-7",
    )) as planner:
        await planner.query(
            f"Goal: {user_goal}\nAnalysis: /tmp/edit/analysis.json\n"
            f"Produce an ordered edit plan as JSON (cuts, transitions, audio, color)."
        )
        plan = await planner.await_complete()   # blocks until complete(plan) tool

    # --- Stage 3: execution (cheaper model, full tool access, long loop) ---
    async with ClaudeSDKClient(ClaudeAgentOptions(
        system_prompt=EDIT_EXECUTOR_PROMPT,
        allowed_tools=["ffmpeg", "resolve_mcp", "Read", "Write", "Bash", "complete"],
        max_turns=40,
        extra_args={"thinking": {"type": "enabled", "budget_tokens": 4000}},
        model="claude-sonnet-4-5",
        hooks={"PreCompact": compact_old_tool_outputs},
    )) as executor:
        await executor.query(f"Execute this edit plan:\n{plan}")
        async for msg in executor.receive_response():
            stream_progress_to_electron(msg)
        result = await executor.await_complete()

    # --- Stage 4: score & optional replan (judge subagent) ---
    score = await launch_subagent(
        model="gemini-2.5-pro",
        task=f"Score the rendered clip at {result.output_path} against goal "
             f"'{user_goal}'. Return {{score: 0-1, issues: [...]}}",
    )
    if score.score < 0.7 and score.has_fixable_issues:
        # Re-plan with feedback, bounded retry
        return await edit_video(
            user_goal=f"{user_goal}\nPrevious attempt issues: {score.issues}",
            input_video=input_video,
        )  # recursion depth should be capped at 2 in the caller
    return result
```

Three loops, three models, three budgets. Gemini perceives. Opus plans. Sonnet executes. A judge subagent decides whether to re-plan. Each loop has its own `max_turns` and cost ceiling; each subagent runs in fresh context so the parent never drowns in intermediate state.

---

## Closing opinions

- Native tool use on frontier models has made ReAct-style prompting obsolete. Don't write `Thought:/Action:` parsers in 2026.
- Plan-and-execute with a big planner and small executor is the right default for multi-step creative agents. Skip it only when steps are < 5.
- Reflexion only works with a real evaluator. Video "quality" is not one.
- Tree of Thoughts is a paper, not a production pattern. Use best-of-N if you need branching.
- Harness > hand-rolled loop. The Claude Agent SDK handles interleaved thinking, streaming, prompt caching, and retries. Use it.
- Long-horizon means files + subagents + compaction, together. Pick a hierarchy, not one strategy.
- Always run three stop conditions (natural, step budget, cost budget). Add `complete()` for user-facing agents.

---

*Note on sources: web access was not used for this document. Claims are drawn from training knowledge through January 2026, including the ReAct (Yao et al., 2022), Reflexion (Shinn et al., 2023), Plan-and-Solve (Wang et al., 2023), Tree of Thoughts (Yao et al., 2023), LATS (Zhou et al., 2023), and Self-Refine (Madaan et al., 2023) papers, and public documentation for the Claude Agent SDK, OpenAI Agents SDK, LangGraph, and Claude Code as of that cutoff.*
