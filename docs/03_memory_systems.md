# Research 3 — Memory Systems for AI Agents

Implementation-ready architecture for Ed.it.

## 1. Memory Architecture (2026 State of the Art)

Production agent memory splits into **five tiers** that are almost always combined:

| Tier | What it holds | Storage | Lifetime |
|---|---|---|---|
| **Short-term** | Raw conversation turns in-context | LLM context window | current session |
| **Working** | Current task state, active plan, tool-call outputs | JSON blob / scratchpad in prompt | current task |
| **Episodic** | Specific past events ("last Tuesday you rejected yellow caption style") | Vector DB + timestamps | weeks–months, decays |
| **Semantic** | Stable facts ("Naomi is a worship creator, studio LUT = Naomi_Worship_Warm.cube") | SQLite key-value + JSON | permanent until changed |
| **Procedural** | Learned preferences/patterns ("worship mode → Cormorant 45px") | SQLite rules table | permanent, contradiction-resolved |

Dominant 2026 pattern: **MemGPT/Letta-style layered memory** — explicit "core memory" block (always in context, ~2KB pinned facts) + "archival memory" readable/writable via tool calls. What ChatGPT memory, Claude's memory tool, and Letta all converged on.

## 2. Vector DB Options for Desktop Apps

For Electron+Python single-user desktop, realistic options:

| DB | Embedded? | Electron fit | Notes |
|---|---|---|---|
| **LanceDB** | Yes (columnar, file-based) | Excellent — Python + JS bindings, zero-copy Arrow | Best all-around 2026. Fast, versioned, multi-modal. Recommended. |
| **sqlite-vec** | Yes (SQLite extension) | Excellent — same DB as structured data | Best if you want *one file*. Slightly slower past 100k vectors but trivial to deploy. |
| **ChromaDB** | Yes (embedded mode) | OK but heavy | 300MB with deps, opinionated API, duckdb backend. |

**Skip for desktop:** Qdrant/Weaviate (separate server), pgvector (needs Postgres), Turso (cloud-leaning).

**Recommendation for Ed.it: sqlite-vec + SQLite in ONE file** for MVP. Migrate vector side to LanceDB if you exceed ~500k rows or need hybrid full-text. One file = easy backup, easy "export my data," zero IPC.

**Embedding model to pair:**
- **Local default: BGE-small-en-v1.5** (384 dim, 130MB, runs on CPU via `sentence-transformers` or ONNX). No API calls, no privacy concerns, aligns with "local-first" brand.
- **Cloud fallback: OpenAI `text-embedding-3-small`** (1536 dim, $0.02/1M tokens) — for higher quality when user opts in.
- **Voyage voyage-3-lite** is best non-OpenAI cloud small in 2026.

Store both in same collection only if you commit to one dimensionality; otherwise keep separate tables keyed by `embedding_model`.

## 3. SQL vs Vector — When to Use Each

| Use SQL when... | Use vector when... |
|---|---|
| Exact key lookup (user_id, project_id, file_path) | "Find edits similar to this one" |
| Filterable facts (LUT, font, BPM, duration) | "Past clips with similar vibe" |
| Counting / aggregation ("how many times rejected yellow?") | Free-text memory recall ("what she said about pacing last week") |
| Ordered lists (recent projects, last 10 edits) | Style matching on embeddings |

**Hybrid retrieval is the default in 2026:** SQL WHERE first (narrow candidate set — `mode='worship' AND accepted=1`), then vector similarity rank candidates. sqlite-vec supports this in one query via `vec_match` + normal WHERE. What Mem0, Letta, and most production agents do.

## 4. Memory Write Policies

Don't write every turn — gives you 10k noisy episodic entries that poison retrieval. 2026 consensus:

**Three write triggers:**
- **Explicit**: "remember that," "from now on," "I prefer X." → always write, high confidence.
- **Salience-judged**: after each turn, small cheap LLM call (Haiku / Flash Lite) asks *"is this new info about the user worth remembering? return JSON {remember: bool, type: semantic|episodic|preference, text: string}"*. Threshold ~0.7.
- **Behavioral**: deterministic triggers — user accepts/rejects, starts new project, applies LUT. Logged as structured events, not LLM-judged.

**Contradiction handling:** on write, SQL query for existing facts with same `fact_key`. If found, don't delete — write new row with `supersedes=<old_id>` + `valid_from=now`. Audit trail. At read, filter `WHERE superseded_by IS NULL`. (How Letta and Mem0 do it.)

**Decay:** episodic memories get `confidence` that decays exponentially with age (half-life ~30 days) and boosts on re-access. Semantic facts don't decay. Hard-delete confidence <0.1 in nightly job.

## 5. Memory Read Policies

1. **Always-load core memory** (~500–2000 tokens): pinned identity facts, top 5 preferences, current project name. Cheap, massive quality win.
2. **Query-load on retrieval**: top-k=8 from vector + MMR reranking (λ=0.5) to diversify. For editing agent, always include last 3 episodic events from current project regardless of similarity.
3. **Token budget:** hard-cap memory at ~15% of context window. 200k window → 30k for memory. Summarize anything over budget with a "memory digest" call.
4. **Summarization:** every 50 episodic entries per project, compress to 1 semantic summary via LLM. Keep originals for audit, retrieve only the summary.

## 6. Production Examples

- **ChatGPT Memory**: single flat list of bullet "memories," LLM-written, ~1000 tokens capped, always injected. No vector retrieval — just truncation. Simple but limited.
- **Claude's memory tool (2025)**: tool-call based read/write; agent explicitly calls `memory.read(query)` / `memory.write(text)`. Server-side storage. More flexible than ChatGPT's always-inject.
- **Letta (MemGPT)**: two-tier (core block + archival), agent self-edits via tool calls, runs context-compaction loop when window fills. Open source — worth cloning to study.
- **Mem0**: production library with SQL + vector hybrid, LLM-judged write policy, contradiction resolution. Drop-in Python lib — you could literally use it.
- **Rewind.ai**: full-recall approach, OCRs everything, stores locally in SQLite+vector, queries on demand. Model for "local-first privacy."
- **Sana AI**: graph-based "context layer" — entities (people, docs, projects) with typed edges. Not just text chunks. More structured than chunk-RAG.

## 7. Style Learning (Specific to Naomi)

Three layers, combined:

1. **Explicit onboarding** (one-time): ask 10 preference questions → seed `preferences` table.
2. **Observation logging**: every render, log `{mode, LUT, font, caption_style, pacing_bpm, music_bed, duration, accepted}`. After 10 accepted edits in a mode, run aggregation: "for worship mode, modal LUT = X, median cut length = Ys" → promote to `procedural_rules`.
3. **A/B preference learning**: when you offer A vs B and she picks one, log `{chosen: B, rejected: A, delta_features: {LUT, captions, music}}`. After ~10 of these, the feature that most predicts "chosen" becomes strong preference (logistic regression or count-based Bradley-Terry).

Feature extraction on past outputs: for every rendered file, store `{avg_brightness, avg_warmth_hue, cut_count, avg_clip_duration, caption_density, LUT_name}` — becomes the "style fingerprint" and embeds for similarity search.

## 8. Concrete Schema — SQLite + sqlite-vec

```sql
-- IDENTITY & SEMANTIC
CREATE TABLE user_profile (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);
-- rows: name, role, faith, location, bio, studio_gear (json), etc.

CREATE TABLE preferences (
  id INTEGER PRIMARY KEY,
  scope TEXT NOT NULL,            -- 'global' | 'worship' | 'talking_head' | 'lifestyle'
  key TEXT NOT NULL,              -- 'lut', 'font', 'caption_style', 'cut_length'
  value TEXT NOT NULL,            -- 'Naomi_Worship_Warm.cube'
  confidence REAL NOT NULL,       -- 0..1
  source TEXT NOT NULL,           -- 'explicit' | 'observed' | 'ab_test'
  supersedes INTEGER,
  superseded_by INTEGER,
  valid_from INTEGER NOT NULL,
  UNIQUE(scope, key, valid_from)
);

-- PROJECTS & FILES
CREATE TABLE projects (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  folder_path TEXT NOT NULL,
  mode TEXT,                      -- 'worship' | 'talking_head' | 'lifestyle'
  created_at INTEGER,
  last_touched_at INTEGER,
  status TEXT                     -- 'active' | 'archived' | 'shipped'
);

CREATE TABLE media_files (
  id INTEGER PRIMARY KEY,
  project_id INTEGER REFERENCES projects(id),
  path TEXT NOT NULL,
  kind TEXT,                      -- 'raw' | 'render' | 'reference'
  duration_s REAL,
  features_json TEXT,             -- {brightness, warmth, cut_count, ...}
  created_at INTEGER
);

-- EPISODIC (every meaningful event)
CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  project_id INTEGER,
  kind TEXT NOT NULL,             -- 'edit_accepted' | 'edit_rejected' | 'ab_choice' | 'prompt' | 'note'
  payload_json TEXT NOT NULL,
  ts INTEGER NOT NULL
);

-- EDIT DECISIONS (for style learning)
CREATE TABLE edit_decisions (
  id INTEGER PRIMARY KEY,
  project_id INTEGER,
  version_a_json TEXT,            -- feature vector of version A
  version_b_json TEXT,
  chosen TEXT,                    -- 'A' | 'B' | 'neither'
  ts INTEGER
);

-- CONVERSATION (short + mid term)
CREATE TABLE messages (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,             -- 'user' | 'assistant' | 'tool'
  content TEXT NOT NULL,
  tokens INTEGER,
  ts INTEGER NOT NULL
);

CREATE TABLE session_summaries (
  session_id TEXT PRIMARY KEY,
  summary TEXT NOT NULL,
  tokens INTEGER,
  ts INTEGER
);

-- VECTOR MEMORIES (sqlite-vec virtual table)
CREATE VIRTUAL TABLE memory_vecs USING vec0(
  id INTEGER PRIMARY KEY,
  embedding FLOAT[384]            -- BGE-small
);

CREATE TABLE memory_items (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,             -- 'episodic' | 'semantic' | 'style_example' | 'session_summary'
  text TEXT NOT NULL,
  project_id INTEGER,
  source_event_id INTEGER,
  confidence REAL DEFAULT 1.0,
  access_count INTEGER DEFAULT 0,
  last_accessed_at INTEGER,
  created_at INTEGER NOT NULL
);

CREATE INDEX idx_mem_kind_project ON memory_items(kind, project_id);
CREATE INDEX idx_events_project_ts ON events(project_id, ts DESC);
CREATE INDEX idx_prefs_active ON preferences(scope, key) WHERE superseded_by IS NULL;
```

## Implementation Stack Recommendation

- **Storage:** one SQLite file (`naomi.db`) with sqlite-vec loaded as extension. Ship inside Electron userData dir. Backup = copy one file.
- **Embedding:** bundle **BGE-small-en-v1.5** via ONNX Runtime (runs in Python OR Electron's Node). ~130MB, CPU-fast enough for desktop.
- **Library:** start with raw SQL + thin Python wrapper. Consider **Mem0** if you want write-policy + contradiction handling OOTB — read its source first; small enough to vendor.
- **Core memory prompt block** (~800 tokens): auto-assembled from `user_profile` + top-N `preferences WHERE superseded_by IS NULL ORDER BY confidence DESC`. Inject at top of every LLM call.
- **Retrieval:** `SELECT ... FROM memory_items JOIN memory_vecs WHERE kind IN (...) AND project_id = ? ORDER BY vec_distance(embedding, ?) LIMIT 8` — single SQL round-trip does hybrid filter+rank.
- **Write pipeline:** after each turn, async fire Haiku/Flash-Lite salience check → if yes, embed + insert → done. Don't block user response.

One file. Offline. Private. Fast enough for single-user. Every memory operation is transparent SQL Naomi could inspect herself.
