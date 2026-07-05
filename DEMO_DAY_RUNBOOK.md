# Demo-Day Runbook — AskTube AI

Live demo: **https://asktube-ai.duckdns.org** (fallback: https://asktube-ai.vercel.app)
Backend: https://asktube-ai-q2gi.onrender.com

This runbook assumes the free-tier deployment (Vercel + Render). Two free-tier
behaviors drive every step below:
- **Render sleeps after 15 idle min** → 30–60 s cold start on first request.
- **Render has no persistent disk** → ChromaDB + SQLite analytics reset on every
  restart, so the demo video must be re-ingested after any restart.

---

## ⏱️ T-minus 10 minutes — pre-flight (do this before the audience arrives)

### 0. ✅ Confirm the residential proxy is set on Render (CRITICAL)

**Status as of 2026-07-05: `WEBSHARE_PROXY_URL` is NOT set on Render.**
Without it, every ingest returns a clean 502 with the proxy hint (the
datacenter-IP block from LEARNINGS.md). This is the single most likely thing to
derail the demo — fix it first.

1. Render dashboard → **asktube-ai** service → **Environment**.
2. Confirm `WEBSHARE_PROXY_URL` exists and has a value (it's 50 chars locally).
   - If you only have username/password, set `WEBSHARE_PROXY_USERNAME` +
     `WEBSHARE_PROXY_PASSWORD` instead — both forms work; `*_URL` takes priority.
3. Adding/changing an env var on Render does **not** require a redeploy for the
   value to take effect on the *next* cold start, but to be safe: **trigger a
   manual deploy** (Manual Deploy → Deploy latest commit) after setting it.

> Why it matters: `youtube-transcript-api` raises `RequestBlocked`/`IpBlocked`
> from Render's datacenter IPs. The proxy routes the fetch through a residential
> IP. Without it: ingest = guaranteed 502.

### 1. 🌡️ Warm the backend (~1 min before presenting)

Free-tier cold start is 30–60 s. Warm it so the audience never sees it.

- Easiest: visit **https://asktube-ai-q2gi.onrender.com/health** in a browser.
  Expect `{"status":"ok","service":"AskTube AI"}` within a minute.
- Or curl it (note: on this machine, schannel/Avast may break local curl — use
  the browser or an external probe like https://check-host.net/check-http ).

### 2. 🎬 Re-ingest the demo video

After a Render restart, ChromaDB is empty — search works but **chat has nothing
to retrieve from** until you ingest. Do this during warm-up, not on stage.

1. Open the demo URL, search for your chosen video (see "Picking videos" below).
2. Click the result to ingest → wait for the "indexed/ready" state in the UI.
3. Ask one throwaway question to confirm retrieval + citation render correctly.
4. Leave that video ingested so the live demo starts from a populated workspace.

### 3. 📋 Sanity check the four pillars

Before walking on stage, confirm each works once:
- [ ] **Search** returns results (YouTube Data API key live).
- [ ] **Ingest** completes (proxy working — this is the gate).
- [ ] **Chat** answers with a **timestamped citation** you can click.
- [ ] **/analytics** page shows the question you just asked (analytics write path).
- [ ] *(Optional)* **Voice search** — the dashboard confirmed it's live, but test
      the mic in the actual room.

---

## 🎤 On stage — the demo flow

1. Land on the home page → point out "Transcript-grounded YouTube intelligence".
2. **Search** a topic (have the query typed in advance).
3. Pick a **short, captioned** video → click to ingest (narrate "indexing the
   transcript into a vector store").
4. Switch to **Workspace/Chat** → ask a question whose answer is in the video.
5. Highlight the **citation chip** with the timestamp → click it to jump.
6. Open **/analytics** → show the question you just asked counted in the dashboard.
7. *(Wow-factor)* Voice search → "ask about X" → see it transcribe + search.

---

## 🎯 Picking videos (do this in advance)

Always pick **captioned** videos — ingest depends on YouTube captions.

- **Good:** popular educational channels (TED-Ed, Kurzgesagt, Veritasium, 3Blue1Brown,
  freeCodeCamp, Stanford/MIT lectures). High caption quality, evergreen topics.
- **Bad:** auto-generated-caption-only clips, music videos, shorts, anything under
  ~60 s (too little transcript to chunk meaningfully).
- **Test it now:** open the video on YouTube → ⋮ (more) → "Show transcript". If
  a transcript panel populates, it will ingest. If it says "transcript
  unavailable," pick another.
- Keep it **under ~15 min** so ingest finishes in a few seconds on free-tier CPU.

Have **two** captioned videos pre-validated (primary + backup) in case one gets
region-blocked or its captions get pulled.

---

## 🚨 If something breaks on stage

| Symptom | Likely cause | Fix |
|---|---|---|
| First request hangs 30–60 s | Render cold start | Wait; it self-resolves. Warm `/health` next time. |
| Ingest → 502 "YouTube refused" | Proxy not set / proxy down | Set `WEBSHARE_PROXY_URL` on Render + redeploy (step 0). |
| Chat returns generic answer, no citation | ChromaDB empty (post-restart) | Re-ingest the demo video (step 2). |
| Search returns nothing / "Search paused" | `YOUTUBE_API_KEY` quota or `NEXT_PUBLIC_API_URL` wrong | Check Render env + Vercel `NEXT_PUBLIC_API_URL` matches the onrender URL. |
| duckdns URL won't load on your laptop | Your router cached the old EC2 IP (LEARNINGS.md) | Use https://asktube-ai.vercel.app instead — it's the same app. Or toggle browser DoH. |
| Everything 500s | A push to `main` broke the build | Check Render deploy logs + Vercel build; roll back the commit. |

> **Golden rule for the demo laptop:** if the duckdns URL fails *only on your
> machine* but the Vercel URL works, it's the documented local DNS issue — don't
> panic, just use the Vercel URL. Verify cutover health from an external probe
> (https://check-host.net/check-http), not from this PC.

---

## 🧊 After the demo

- No teardown needed — leaving it deployed costs $0.
- If you want a clean analytics dashboard for next time, just restart the Render
  service (it wipes SQLite). Don't forget to re-ingest afterward.
