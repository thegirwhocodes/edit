# Ed.it — Research Docs

Research that informs the build plan for Ed.it (the AI video editing agent).

## Files

### Foundation (session 3ca6f6d6)
- [01_agent_frameworks.md](01_agent_frameworks.md) — Claude Agent SDK vs OpenAI Agents SDK vs LangGraph vs Vercel AI SDK. Recommended stack.
- [02_alive_ux_patterns.md](02_alive_ux_patterns.md) — What makes AI feel alive. Patterns from Sana, Granola, Rewind, Cursor, Pi, Midjourney.
- [03_memory_systems.md](03_memory_systems.md) — 5-tier memory architecture, SQLite + sqlite-vec schema, BGE embeddings, write/read policies.
- [04_video_sota_and_instagram.md](04_video_sota_and_instagram.md) — Video editing SOTA (Submagic, Opus, Descript, LongVU), Instagram Graph API access.

### How people actually build agents (session 6abf9016)
- [05_agent_loops_and_architectures.md](05_agent_loops_and_architectures.md) — ReAct, Reflexion, Plan-Execute, the modern harness, long-horizon context, stop conditions, failure modes, Ed.it loop skeleton.
- [06_tool_design_and_mcp.md](06_tool_design_and_mcp.md) — Tool schema rules, MCP ecosystem + transports, writing an MCP server, error handling, approval/sandboxing, dynamic tool sets, testing, observability.
- [07_multi_agent_orchestration.md](07_multi_agent_orchestration.md) — Single-vs-multi tradeoff, orchestrator-worker, handoffs, pipelines, model tiering, shared state, Ed.it recommendation (single-agent v1, subagents only for variation generation).
- [08_evaluation_and_reliability.md](08_evaluation_and_reliability.md) — Three eval layers (unit/trajectory/outcome), LLM-as-judge with rubric, Langfuse + Inspect, guardrails, cost/latency observability, failure recovery, v1 reliability checklist.
- [09_production_engineering.md](09_production_engineering.md) — Prompt caching (`cache_control` breakpoints), streaming UX, structured outputs, cost control, observability stack, BYO keys in Keychain, Electron+bundled-Python packaging, signing, privacy one-pager, day-1 shipping checklist.

## TL;DR of the Research

**Stack:** Claude Agent SDK (brain) + Vercel AI SDK (UI) + MCP (tools) + SQLite/sqlite-vec (memory) + BGE-small (embeddings) + Gemini 2.5 Flash (video analysis) + FFmpeg (rendering) + DaVinci Resolve MCP (optional pro path).

**Feel:** background daemon watches folders → proactive greetings → 3 variations always → visible reasoning → editable taste profile → never-suggest-again trust-builder.

**Memory:** 5-tier, one SQLite file, BGE embeddings local, Mem0-style write policies.

**Video pipeline:** don't rebuild Opus — feature dashboard instead of virality score. Use Gemini + WhisperX + PySceneDetect + face/emotion + audio energy.

**Instagram:** skip for MVP. Add in v2 with Graph API + Instagram Login.
