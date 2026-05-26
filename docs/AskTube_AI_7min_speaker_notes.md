# AskTube AI - 7 Minute Speaker Notes

Use this as your speaking guide during the final presentation. The goal is to sound clear and human, not to read every word on the slides.

## Timing Plan

| Slide | Topic | Time |
|---|---:|---:|
| 1 | Opening | 30 sec |
| 2 | Product idea | 45 sec |
| 3 | User journey | 40 sec |
| 4 | Architecture | 55 sec |
| 5 | Ingestion pipeline | 55 sec |
| 6 | LangChain agent | 55 sec |
| 7 | RAG answering | 45 sec |
| 8 | Voice + UX | 35 sec |
| 9 | Testing + evaluation | 40 sec |
| 10 | Live demo plan | 45 sec |
| 11 | Closing | 35 sec |

Total: about 7 minutes.

---

## Slide 1 - Opening

**Say this:**

AskTube AI is my final project. The idea is simple: instead of only watching a YouTube video passively, the user can search for a video, let the app process the transcript, and then chat with the video content.

The important part is that the answers are not generic AI answers. They are grounded in the transcript and include timestamp citations, so the user can verify where the answer came from.

**Key message:** This is a learning assistant for YouTube videos, not just a normal chatbot.

---

## Slide 2 - Product Idea

**Say this:**

The problem I wanted to solve is that YouTube has a lot of good learning content, but long videos are difficult to search inside. You often know the answer is somewhere in the video, but finding the exact moment is slow.

AskTube AI turns the video transcript into a searchable knowledge base. The user searches, chooses a video, the backend processes the transcript, and then the user can ask questions.

The trust rule is very important: if the transcript does not contain the answer, the assistant should refuse instead of inventing.

**Key message:** The value is speed plus trust.

---

## Slide 3 - User Journey

**Say this:**

The user journey has four steps.

First, the user searches by text or voice. Second, they choose a video from a Netflix-style carousel. Third, the backend prepares the video by extracting the transcript, chunking it, embedding it, and storing it in ChromaDB. Finally, the user chats with the video and gets timestamped answers.

I also added duration filters, loading states, smooth animations, and a 3D assistant to make the flow feel more like a real product.

**Key message:** The technical pipeline is hidden behind a simple user flow.

---

## Slide 4 - Architecture

**Say this:**

The architecture has three main layers.

The frontend is Next.js with TypeScript, Tailwind, Framer Motion, Embla carousel, and Three.js for the 3D assistant.

The backend is FastAPI. It exposes routes for search, transcripts, chunking, vector storage, chat, agent chat, speech, and evaluations.

The AI and data layer uses LangChain, OpenAI models, ChromaDB, Whisper fallback, and optional LangSmith tracing.

Everything runs with Docker Compose: frontend, backend, and ChromaDB.

**Key message:** It is separated like a production app: UI, API, and AI/data pipeline.

---

## Slide 5 - Ingestion Pipeline

**Say this:**

This is the most important backend flow.

When the user selects a video, the backend first gets metadata from the YouTube Data API. Then it tries to get the transcript using `youtube-transcript-api`, which was also the approach recommended by Carlos.

After that, the transcript is split into chunks. Each chunk keeps timestamp metadata, so later the answer can cite exact moments.

Then OpenAI embeddings are generated and stored in ChromaDB. After this step, the video is ready for RAG questions.

Whisper and yt-dlp exist only as a fallback if captions are unavailable. The normal flow does not download full videos.

**Key message:** Transcript first, audio fallback only when needed.

---

## Slide 6 - LangChain Agent

**Say this:**

To match the tool requirement, I implemented a LangChain tools layer.

Each tool wraps an existing backend service. For example, there is a tool for searching YouTube, one for extracting transcripts, one for chunking, one for storing vectors, one for retrieving context, and one for answering questions.

The `AgentService` binds these tools to the language model. So the system is not just one prompt calling the LLM. It can decide which tool is needed and then return the final answer with citations and the session ID.

There is also memory, so follow-up questions can use the previous conversation.

**Key message:** This directly covers the "LLM with tools and memory" requirement.

---

## Slide 7 - RAG Answering

**Say this:**

The RAG flow has four steps.

First, the user question is used to retrieve the most relevant transcript chunks from ChromaDB. Then those chunks, the memory, and the rules are injected into the prompt.

The model writes the answer only from that context. Finally, the UI shows timestamp citations.

If the answer is not present in the transcript, the assistant should say that it cannot answer from the video. This is the main anti-hallucination rule.

**Key message:** Retrieval controls what the model is allowed to answer.

---

## Slide 8 - Voice + Cinematic UX

**Say this:**

I also added optional features to make the project feel more complete.

Voice search uses the browser Web Speech API first. If that fails, the app can record audio and send it to the backend for Whisper transcription.

There is also text-to-speech for AI answers, a 3D assistant scene, animated loading states, responsive layouts, and accessibility improvements like labels, focus states, and reduced-motion support.

**Key message:** The optional features support the learning experience, but the core is still RAG.

---

## Slide 9 - Testing + Evaluation

**Say this:**

For testing, the backend has 98 pytest tests. They cover routes, services, tools, WebSocket ingestion, speech transcription, memory, vector storage, and RAG behavior.

I also created a RAG evaluation dataset with 17 cases. These test answerable questions, unrelated questions that should be refused, citation accuracy, summaries, memory, and hallucination prevention.

LangSmith tracing can also be enabled to inspect latency, context, tool calls, and answer quality.

**Key message:** I did not only build the app; I also tested the AI behavior.

---

## Slide 10 - Live Demo

**Say this:**

For the demo, I will show the main flow: search, prepare, ask, and verify.

I can show the EC2 deployment to prove the app runs with Docker on a server. But for the full transcript/RAG demo, local Docker is more reliable because YouTube often blocks transcript requests from cloud IP addresses.

This is a known limitation of YouTube transcript access, not a problem with the RAG pipeline. I documented the issue and added Webshare proxy support, but the proxy must support HTTPS access to YouTube.

During the demo, I want to emphasize trust: every answer should connect back to the transcript and timestamps.

**Key message:** EC2 proves deployment; local demo proves full transcript ingestion if YouTube blocks cloud IPs.

---

## Slide 11 - Closing

**Say this:**

To summarize, AskTube AI meets the main project requirements: LLM chatbot, tools, memory, vector database, text processing, UI, tests, evaluation, and deployment.

It also includes optional features like voice input, Whisper fallback, streaming, TTS, a 3D assistant, and LangSmith tracing.

The main future improvements would be persistent user accounts, multi-video comparison, HTTPS with a custom domain, and a stronger production transcript proxy.

**Final sentence:**

AskTube AI makes YouTube videos learnable by conversation, while keeping the answer grounded in the original transcript.

---

## If Carlos Asks About Gradio or Streamlit

Say:

Carlos suggested Gradio or Streamlit as simple UI options. I used Next.js because I wanted to build a more product-like learning platform with a cinematic interface, video carousel, responsive layout, 3D assistant, and better user flow. The required AI architecture is still fully covered.

---

## If Carlos Asks About YouTube Downloading

Say:

The normal flow does not download full YouTube videos. It first tries public captions with `youtube-transcript-api`. Only if captions are unavailable, yt-dlp and Whisper can be used as a fallback for audio transcription. Audio files are runtime-only and are not committed to GitHub.

---

## If Carlos Asks About EC2 Transcript Problems

Say:

The Docker app is deployed on EC2, and the frontend and backend are running. The problem is that YouTube often blocks transcript requests from cloud-provider IP ranges. I added residential proxy support and documented it, but for a reliable live demo I can run the full transcript/RAG flow locally.
