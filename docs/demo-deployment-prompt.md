# Prompt: Verify provider changes and migrate AskTube AI to free demo hosting

AskTube AI is a demo (not a business). Goal: verify the recently merged provider
changes, slim the default build, document a $0 hosting path, and retire the paid
EC2 instance safely. Make the smallest changes that achieve this; follow existing
project patterns.

---

## Part 1 — Code-review findings on the recent provider changes (verified against `main` @ 29c5513)

These findings come from a line-by-line review. Do not re-litigate them; act on the tasks below.

### What was merged

**A. NVIDIA chat provider (was requested — quality is good, keep as is):**
- `backend/app/services/llm_provider.py`: chat-model factory, provider-aware 503s,
  `NVIDIA_TOOL_CALLING` opt-out. Defaults are safe — anything except
  `LLM_PROVIDER=nvidia` reproduces the previous OpenAI behavior exactly.
- Agent fallback (`AgentService._answer_via_rag`) correctly delegates to the existing
  `RAGService.answer()` (verified: exists with the exact signature used), preserves
  citations, returns `tool_steps_used=[]`. No duplicate pipeline was built.
- The five context-specific 503 messages were unified to generic per-provider
  messages; no remaining tests assert the old strings (only the speech route kept
  its own message, unchanged).
- 11 unit tests in `backend/tests/test_llm_provider.py`, plus updated agent tests.

**B. Local embeddings provider (was NOT requested — functional but has costs):**
- `backend/app/services/embedding_provider.py`: `EMBEDDING_PROVIDER=openai|local`
  with HuggingFace sentence-transformers; `chunking_service.py` and
  `vectorstore_service.py` refactored through it. Code quality is good (lazy torch
  import, instance cache, correct warnings that switching providers requires wiping
  ChromaDB).
- **Problem 1 — unconditional weight:** `sentence-transformers==5.5.0` and
  `langchain-huggingface==1.2.2` were added to the main `requirements.txt`, so every
  backend image build installs ~0.5–1 GB of torch/transformers even with the default
  `EMBEDDING_PROVIDER=openai`.
- **Problem 2 — ARM incompatibility:** `backend/requirements-cpu.txt` pins
  `torch==2.9.1+cpu` from the PyTorch CPU wheel index. `+cpu` local-version wheels on
  that index target `linux_x86_64`; on an arm64 host (the recommended free hosting
  below is ARM) this pin fails to resolve. On aarch64, plain PyPI `torch` is already
  CPU-only.

**C. Verification status: NONE of the merged backend changes have been executed.**
The tests exist but have never been run. This is the first task.

### Tasks for Part 1

1. **Run the full backend test suite** (`cd backend && pip install -r requirements-dev.txt && python -m pytest`)
   and the frontend suite (`cd frontend && npm ci && npx tsc --noEmit && npm test`).
   Fix any failures. Paste actual output — do not claim success without it.
   (Windows note: if greenlet fails with "filename too long", put the venv at a short
   path, e.g. `C:\tmp\venv` — see LEARNINGS.md.)
2. **Make the local-embeddings dependencies opt-in** so the default image stays slim
   and ARM-safe:
   - Remove `sentence-transformers` and `langchain-huggingface` from
     `backend/requirements.txt`.
   - Create `backend/requirements-local-embeddings.txt` containing them (and the
     torch note). Keep the lazy import in `embedding_provider.py` (already correct);
     if `EMBEDDING_PROVIDER=local` is set without the extras installed, raise a clear
     503/ImportError message naming the requirements file to install.
   - Revert the Dockerfile to plain `pip install -r requirements.txt`; keep the
     `HF_HOME=/app/data/hf_cache` env lines (harmless, useful if extras are added) and
     add a commented-out RUN line showing how to bake the local-embeddings extras in.
   - Fix or document the ARM case: on aarch64 do NOT use the `+cpu` pin; plain
     `torch` from PyPI is CPU-only there.
   - Update `test_embedding_provider.py` so the local-provider tests skip cleanly
     (`pytest.importorskip("langchain_huggingface")`) when extras are absent.
3. Update `.env.example` files: `EMBEDDING_PROVIDER` docs must mention the extras
   install step and repeat the wipe-and-re-ingest warning.

---

## Part 2 — Free demo hosting (replace the paid EC2)

### Recommendation (verified July 2026)

**Primary: Oracle Cloud "Always Free" VM.** Since 2026-06-15 the free tier is
2 Ampere ARM OCPUs / 12 GB RAM — more than the current EC2. The entire existing
setup transfers unchanged: `docker compose up -d`, host Nginx + Certbot, and the
free DuckDNS domain (`asktube-ai.duckdns.org`) just gets repointed to the new IP.
Caveats to document: signup requires a card for identity (never charged on Always
Free), capacity varies by region, idle instances can be reclaimed, and the host is
**arm64** — images build on the VM itself, which is why Part 1 task 2 (ARM-safe
requirements) must land first.

**Fallback (if Oracle signup/capacity fails): Vercel + Render free tiers.**
- Frontend → Vercel free (native Next.js hosting, free HTTPS).
- Backend → Render free. Known tradeoffs (from docs and user reviews): a card is
  required despite "free"; services spin down after 15 idle minutes with 30–60 s
  cold starts; **no persistent disk** — ChromaDB contents and SQLite analytics are
  lost on every restart (demo must be re-ingested before showing); free Postgres
  self-deletes after ~30 days. Acceptable for a demo, unacceptable beyond one.
- ChromaDB in this mode: run embedded (`CHROMA_USE_HTTP=false`) inside the backend
  service since there is no second free service with a disk.

### Tasks for Part 2

4. **Add a "Free demo hosting" section to DEPLOY.md** covering:
   - Oracle VM path: create Always Free Ampere instance (Ubuntu), open ports
     80/443 in the security list, install Docker + compose plugin, clone repo, copy
     `.env`, `docker compose up -d --build`, update the DuckDNS record to the new
     public IP, run `sudo certbot --nginx -d asktube-ai.duckdns.org`. Note the
     arm64 build implication.
   - Vercel + Render fallback: build settings, required env vars
     (`NEXT_PUBLIC_API_URL` → Render URL at Vercel build time; `CORS_ORIGINS` →
     Vercel URL — now overridable via `.env` since the compose fix), and the
     data-loss/cold-start caveats stated plainly.
5. **Add an "EC2 teardown" checklist to DEPLOY.md** (order matters):
   1. Back up data off the instance first:
      `docker run --rm -v asktube-ai_backend_data:/d -v $(pwd):/out alpine tar czf /out/backend_data.tgz -C /d .`
      (same for the `chroma_data` volume), plus `scp` the tarballs and the server's
      `.env` to local storage.
   2. `docker compose down`.
   3. Terminate the EC2 instance in the AWS console.
   4. **Release the Elastic IP (18.157.233.122)** — an unattached Elastic IP is
      billed hourly; this is the classic leftover charge.
   5. Delete unused EBS volumes/snapshots and confirm the bill shows zero active
      resources.
   6. Keep the DuckDNS account/subdomain — it is free and gets repointed to the
      new host.

## Acceptance criteria

- Backend + frontend test suites pass with pasted output.
- Default backend Docker image builds without torch/sentence-transformers and on
  both amd64 and arm64.
- `EMBEDDING_PROVIDER=local` fails with an actionable message unless the extras
  file is installed; with it installed, the existing local-embedding tests pass.
- DEPLOY.md contains the Oracle path, the Vercel+Render fallback with honest
  caveats, and the EC2 teardown checklist including the Elastic IP release.
- No secrets committed; `LLM_PROVIDER`/`EMBEDDING_PROVIDER` defaults unchanged.
