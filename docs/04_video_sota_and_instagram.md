# Research 4 — Video Editing SOTA + Instagram API Access

## Part 1 — State of the Art in AI Video Editing (2026)

### 1. Submagic

Thin-but-good wrapper over a standard pipeline, not a research lab. Architecture (from marketing + output reverse-engineering):

- **ASR layer**: Whisper-family word-level transcription (likely WhisperX or proprietary fork) for sub-100ms timing their animated captions need. Auto-detects 50+ languages.
- **Caption styling**: template engine, not AI — "viral templates" (MrBeast, Hormozi, Ali Abdaal) are hand-designed After-Effects-style compositions keyed off word timestamps. The "AI" part: (a) picking which word to emphasize (heuristic: keyword extraction + length + audio energy), (b) emoji insertion via small LLM reading transcript, (c) B-roll suggestion via CLIP-style text→stock-video search against Storyblocks/Pexels.
- **Virality / hook**: "AI Hooks" = LLM (GPT-4o/Claude class) reading transcript and rewriting first 3 seconds.
- **Clipping (Magic Clips)**: long-form → shorts uses LLM over transcript to find self-contained moments. Weaker than Opus.
- **Pricing (2026)**: ~$16–$49/mo. No public API.

"Wow" is genuinely beautiful caption templates and tight word-sync. Rest is commodity.

### 2. Opus Clip

Clearest "agentic" SaaS in space. Publicly-claimed **ClipAnything** / **ClipGenius** stack:

- **Transcript-first**: Whisper-class ASR → fine-tuned LLM ensemble (including OpenAI + their own) segments transcript into candidate clips by detecting narrative arcs — "hook → tension → payoff." This is the piece competitors fake.
- **Virality Score (0–100)**: regression model trained on ~1M+ TikTok/Reels/Shorts clips labeled with views, watch-time, engagement. Features hinted at:
  - (i) hook strength from LLM scoring first sentence
  - (ii) speech energy / pitch variance from audio
  - (iii) face presence + emotion (FER) per second
  - (iv) scene-change density
  - (v) caption density
  - (vi) narrative arc completeness from LLM
  - (vii) topic embeddings matched to currently-trending clusters
  - Score is marketing-grade — directionally useful, not literally predictive — but underlying features are the right ones.
- **Layout Agent ("AI Reframe")**: active-speaker detection (face + lip-sync correlation) drives 9:16 crop. Table-stakes now; uses standard face-tracking (RetinaFace / YuNet) + Kalman-filter smoother.
- **Pricing**: ~$19–$79/mo. API in beta for agencies ("Opus Clip API").

### 3. Vizard, Veed, Captions.ai, Descript

- **Vizard** — Opus competitor for clipping long videos. Weaker virality model, cleaner B-roll from stock. Wow: batch-processing podcast backlog.
- **Veed** — browser NLE + AI features. "Magic Cut" removes silences (`auto-editor` dressed up) and "Eye Contact" does gaze-correction GAN so speaker always looks at camera. Real genuine wow — one of the few places you see a real generative model (gaze-aware face reenactment, likely a LivePortrait or Diffusion-VAE variant fine-tune) inside a mainstream editor.
- **Captions.ai** — most interesting agent. "AI Creator" generates talking-head end-to-end from script using trained avatar of yourself. "AI Edit" applies viral-style captions + zooms + B-roll. "Twin" is voice+face clone. They fine-tune own models; shipped "Mirage" in 2024, controllable face/voice cloning. Wow = your own avatar speaking a script.
- **Descript** — the odd one out. Transcript-driven editor: edit video by editing text. "Underlord" is an LLM agent watching your session and suggesting cuts, removing filler, writing chapter titles, proposing B-roll. **Closest thing on the market to what you're building.** Full NLE, not desktop agent. $12–$24/mo.

### 4. Runway, Pika, Sora, Luma

Generation labs, edit-adjacent features:
- **Runway Gen-3/Gen-4** + **Act-One** (mo-cap a performance, re-puppet character) + **Aleph** (video-to-video style/relighting/edit). Aleph closest to "editing agent" — type "make this golden-hour, remove logo on wall" and it redoes the shot. Too slow + hallucinatory for real footage; great for stylized B-roll.
- **Pika** — Pikaffects (inflate/melt/squish). Entertainment-tier, not editing.
- **Sora / Sora Turbo** — Storyboard UI closest to "editing agent" in generative tool. Remix/blend/loop lets you stitch generated shots. Not useful for editing your own recorded footage.
- **Luma Dream Machine / Ray-2** — image-to-video with keyframes. Stylized cutaways.

None of these is "edit my 30-min talking head." For generating new shots to stitch in.

### 5. Research + Open Source (2024–2026)

Relevant for "understand a 30-min video and pull the best 60 seconds":

- **LongVU (Meta, 2024)** — spatiotemporal adaptive compression for hour-long video understanding. Most directly applicable to long-form clipping: keeps token count tractable while retaining temporal detail. `github.com/Vision-CAIR/LongVU`
- **Gemini 1.5 / 2.0 / 2.5 Flash** — still most practical for "watch and reason over" full videos with 1M+ context. **Genuinely SOTA for the understanding step — better than building your own.** 2.5 Flash is the right default for cost.
- **VideoLLaMA 2/3, PLLaVA, Video-ChatGPT** — open-source alternatives to self-host. Weaker than Gemini 2.5 for dense temporal grounding; VideoLLaMA 3 is closest.
- **InternVideo2, V-JEPA 2 (Meta)** — strong video encoders for feature extraction (good for virality regressor).
- **TimeChat, Momentor, HawkEye** — papers on "moment retrieval" (given query, find timestamp) — directly relevant to "find best 60 seconds."
- **CLIP4Clip / X-CLIP / VideoMAE-v2** — older but useful for embedding-based highlight selection.

Open-source video tooling you'll actually import:
- **PySceneDetect** — shot boundary (ContentDetector / AdaptiveDetector). Free and reliable.
- **auto-editor** — silence/pause removal, scriptable. Good MVP backbone.
- **WhisperX / CrisperWhisper** — already in your stack.
- **RetinaFace / MediaPipe Face Mesh** — face presence + landmarks.
- **py-feat or EmoNet** — facial emotion per-frame (cheap engagement-peak proxy).
- **librosa / pyloudnorm** — speech energy, RMS envelopes.
- **FFmpeg** — render engine.

**No drop-in SOTA model** for "understand 30-min → pull best 60s." Always a pipeline. Gemini 2.5 Flash over full transcript + audio energy + face/emotion peaks + scene changes, composed into a scoring function = actual SOTA approach. That's what Opus Clip does under the hood.

### 6. Virality / Retention Scoring Research

Real research exists; mostly academic + TikTok/Meta:
- **TikTok public blog + 2021–2023 engagement papers** describe signals their ranker uses: watch-time ratio (rewatches + completion), shares-per-view, early-drop-off seconds 1–3. "Hook quality" operationalized as retention at second 3.
- **"Viral Videos in Social Networks"** + follow-ups (UCLA, USC, CMU): pacing (cuts per 10s), caption density, face-on-screen fraction, emotional arousal peaks correlate with retention — but effect sizes modest, topic-dependent.
- **MrBeast's leaked production doc (2023)** codifies hook retention, "reset attention" cuts every ~10s, visual novelty as three dominant retention levers. Most-cited practitioner framework.
- **What actually predicts retention in practice**: hook strength (first 3s), pacing variance (not just density — *variance*), caption presence on mobile, speaker face-on-screen %, musical/emotional peaks aligned to first third. What does *not* predict: production quality beyond a threshold, LUT choice, caption "style."

**For Ed.it: don't build a "virality score."** Build the *features* (hook scored by LLM, pacing, face %, emotion peaks, caption density, audio energy curve) and show them to Naomi as a **dashboard**. More honest + more useful than a 0–100 black box.

## Part 2 — Legally Pulling Instagram Videos into Ed.it

### 1. Instagram Graph API (The Current Meta API)

The one you'll use. `graph.facebook.com/v21.0/...` + `graph.instagram.com/v21.0/...`.

- **Account requirement**: Instagram must be **Business** or **Creator** and (for most scopes) linked to a Facebook Page. Late 2024, Meta opened a parallel **Instagram Login** flow that lets Creator accounts connect without a Facebook Page — this is what you want for Naomi and scaling to other creators.
- **Read user media**: `GET /{ig-user-id}/media` lists user's own posts/Reels. `GET /{ig-media-id}?fields=media_url,media_type,thumbnail_url,permalink,caption,timestamp` returns signed `media_url` (temporary CDN URL, expires in a few hours).
- **Scopes**: `instagram_business_basic`, `instagram_business_content_publish`, `instagram_business_manage_comments`, `instagram_business_manage_insights` (post-2024 names on Instagram Login flow; older FB Login uses `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`, `business_management`).
- **Rate limits**: 200 calls/user/hour legacy; newer Business Use Case rate limiting uses rolling budget based on app usage score. Media download itself not counted against Graph limits (CDN hit).
- **App Review**: required for non-trivial scopes with non-test users. 1–4 weeks. Need working demo video showing OAuth flow + what app does with each permission. Data Use Checkup annual.
- **Token expiry**: short-lived user tokens = 1 hour; long-lived = 60 days, refreshable indefinitely if exchanged before expiry.

### 2. Instagram Basic Display API

**Dead.** Meta sunset it **December 4, 2024**. Reason every indie IG tool scrambled in Q4 2024. Replacement = **Instagram API with Instagram Login** under Instagram Graph API umbrella — same endpoints, simpler OAuth, no Facebook Page required.

### 3. Content Publishing API

Under Instagram Graph API. Two-step container flow:
1. `POST /{ig-user-id}/media` with `media_type=REELS`, `video_url=<publicly reachable URL>`, `caption=...`, optional `share_to_feed=true` → returns container ID.
2. Poll `GET /{container-id}?fields=status_code` until `FINISHED` (30–90s for Reels).
3. `POST /{ig-user-id}/media_publish` with `creation_id=<container-id>` → publishes.

- **Requirements**: Business/Creator, `instagram_business_content_publish` scope, video file reachable from public URL (S3, Cloudflare R2, signed tempfile URL — **not** localhost). For MVP: Cloudflare R2 free tier (10GB).
- **Rate limit**: **25 API-published posts per IG user per 24 hours.**
- **Video specs for Reels**: MP4/MOV, H.264, AAC, ≤1GB, 3–90s, 9:16 preferred, 30fps recommended, ≤4K. Bitrate ≥5 Mbps.

### 4. Third-Party Aggregators

- **Ayrshare** — $149+/mo. Hosted API proxying posting to IG/TikTok/YouTube/LinkedIn/X. Cuts app-review work dramatically. Not free — rule out for $0 MVP. Fastest path when onboarding creator #2.
- **Buffer API** — Business tier ($6/user/mo baseline, API access gated). Good fallback.
- **Later API** — limited external API; they want you in their UI.
- **Meta Business SDK** — official Meta-authored SDK wrapping Graph API. Use this for Ed.it; IS the Graph API, not separate service.

For $0 MVP with one user (Naomi): **skip aggregators, go direct to Graph API.**

### 5. What You Cannot Do

- **No personal-account access** without Business/Creator conversion. Old Basic Display workaround gone.
- **No scraping** of instagram.com (TOS + actively rate-limited/banned; Meta won lawsuits — BrightData, Bright Initiatives).
- **No unofficial libs** (`instagrapi`, `instaloader`) against production accounts — impersonate mobile app, get Naomi's account flagged/locked, violate TOS. Fine for throwaway experimentation; not fine to ship.
- **No DM automation**, no following/liking on user's behalf, no reading other users' private content.
- **No downloading other people's Reels** via API even if public.

TOS line is clear: official Graph API, user consent via OAuth, documented scopes only.

### 6. Practical Flow for Ed.it (Desktop)

1. Register Meta developer app (free). Configure for Instagram API with Instagram Login.
2. Ed.it "Connect Instagram" button launches OAuth URL in system browser, redirects to `https://localhost:PORT/callback` (loopback server — Meta allows HTTPS redirect URIs; use self-signed cert or ngrok in dev).
3. Exchange code for short-lived token → immediately exchange for long-lived 60-day token. Store encrypted in OS keychain (macOS Keychain via `keyring` Python; Windows Credential Manager).
4. Background refresh every ~50 days to renew long-lived token.
5. Fetch media list → download `media_url`s → hand off to edit pipeline → upload edited result to public URL (R2 free tier) → Content Publishing API.

**Gotchas**:
- App Review mandatory before non-dev users can connect. For Naomi-only, add her as "Tester" in app dashboard to skip review entirely — right $0 MVP move.
- Redirect URIs must be HTTPS; `http://localhost` sometimes accepted in dev mode only.
- Video upload for Reels is async — **must** poll container status; don't publish immediately.
- Meta changes scope names + deprecates versions with ~90-day notice; subscribe to Platform Changelog.

### 7. Alternatives for Scrappy MVP

For one-user MVP with Naomi: **skip Instagram API entirely for v1.**
- Naomi already has raw `.MOV` files on her Mac. Input side needs zero IG integration — just a file picker.
- For posting, friction of "save edited MP4 → open IG on phone → upload" is ~30 seconds. Fine for v1.
- Add Graph API posting in v2 once edit pipeline solid. Add media-library read in v3 (for "re-edit my top-performing Reel").

Keeps MVP at $0, avoids App Review entirely, saves a week of OAuth/infra work for a feature Naomi can do in 30s manually.

## Key URLs to Verify Against

- Instagram Platform overview: developers.facebook.com/docs/instagram-platform
- Instagram API with Instagram Login: developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login
- Content Publishing: developers.facebook.com/docs/instagram-platform/content-publishing
- Rate limiting: developers.facebook.com/docs/graph-api/overview/rate-limiting
- Basic Display deprecation: developers.facebook.com/docs/instagram-basic-display-api
- Meta Business SDK: developers.facebook.com/docs/business-sdk
- Opus Clip API: opus.pro/api
- LongVU (Meta): github.com/Vision-CAIR/LongVU
- PySceneDetect: scenedetect.com
- auto-editor: auto-editor.com
- Gemini video understanding: ai.google.dev/gemini-api/docs/vision

## TL;DR Recommendations for Ed.it

1. **Don't rebuild Opus Clip.** Use existing Gemini 2.5 Flash + WhisperX + PySceneDetect + face/emotion + audio energy. Surface features to Naomi as **explainable dashboard** rather than single virality score. Cheaper + more trustworthy than black-box number.
2. **For long→short clipping**, LongVU is the one SOTA open-source model worth prototyping, but Gemini 2.5 Flash over transcript + audio-energy heuristic will beat it for your use case at your budget.
3. **MVP Instagram integration**: skip it. Local file → local edit → local .mp4 → Naomi uploads on phone. Add Graph API + Content Publishing in v2, with Naomi as Tester to skip App Review.
4. **When you do IG integration**: use Instagram API with Instagram Login (not legacy Basic Display, not Facebook Login), store long-lived tokens in macOS Keychain, host video upload via Cloudflare R2 free tier.
