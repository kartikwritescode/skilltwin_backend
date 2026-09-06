# SkillTwin Backend & AI Orchestration Layer

Personalized AI mentor platform backend, AI orchestrator, learner intelligence, and data layer for **SkillTwin**.

---

## Architecture Overview

SkillTwin is engineered as a **Modular Monolith** adhering to strict domain-driven boundaries:

```
Flutter Mobile App (Separate Repository)
       │
       ▼ (HTTPS / JSON)
┌─────────────────────────────────────────────────────────────┐
│                       FastAPI Layer                         │
│  /health, /api/v1/health, /api/v1/goals, /api/v1/journeys,  │
│  /api/v1/mentor, /api/v1/sessions, /api/v1/concepts, etc.   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                       Services Layer                        │
│  GoalService, JourneyService, LearnerService, MentorService,│
│  RecommendationService, SessionService, RevisionService     │
└──────────────┬───────────────────────────────┬──────────────┘
               │                               │
               ▼                               ▼
┌──────────────────────────────┐ ┌─────────────────────────────┐
│      Repositories Layer      │ │     AI Abstraction Layer    │
│  BaseRepository, GoalRepo,   │ │  LLMProvider (Abstract)     │
│  JourneyRepo, LearnerRepo,   │ │  ├── generate_text()        │
│  ConceptRepo, RevisionRepo   │ │  ├── generate_structured()  │
│                              │ │  ├── embed()                │
│                              │ │  └── evaluate()             │
│                              │ │  MockLLMProvider (Offline)  │
│                              │ │  Gemini / OpenAI (Pluggable)│
└──────────────┬───────────────┘ └─────────────────────────────┘
               │
               ▼
┌──────────────────────────────┐
│       Supabase / Postgres    │
│  pgvector, Row-Level-Security│
└──────────────────────────────┘
```

### Core Product Principles Enforced
1. **Goal-first**: Every recommendation maps to the learner's chosen outcome.
2. **Action over information**: The API surfaces one high-leverage next move rather than cognitive overload.
3. **Evidence over completion**: Mastery is calibrated based on demonstrated reasoning and spaced retrieval proof.
4. **Deterministic state over LLM hallucinations**: State and business logic live in services and databases; LLMs act as reasoning and evaluation engines returning structured validated outputs.
5. **Decoupled AI Vendor**: SkillTwin is never locked to OpenAI, Gemini, or Claude. All generative reasoning runs through `LLMProvider`.

---

## Directory Structure

```
backend/
├── app/
│   ├── main.py                     # FastAPI app factory, CORS, exception handlers, health
│   ├── api/
│   │   └── v1/                     # Versioned routing (/api/v1/)
│   │       ├── endpoints/
│   │       │   ├── health.py       # GET /api/v1/health
│   │       │   ├── goals.py        # POST /api/v1/goals, GET /api/v1/goals/{id}
│   │       │   ├── journeys.py     # GET /api/v1/journeys/{id} (winding path nodes)
│   │       │   ├── mentor.py       # GET /api/v1/mentor/today, POST /api/v1/mentor/message
│   │       │   ├── sessions.py     # POST /api/v1/sessions, POST /api/v1/sessions/{id}/complete
│   │       │   ├── concepts.py     # GET /api/v1/concepts/{id}
│   │       │   └── revision.py     # GET /api/v1/revision/next, POST /api/v1/revision/submit
│   │       └── router.py           # v1 router aggregator
│   ├── core/
│   │   ├── config.py               # Environment configuration with Pydantic v2 BaseSettings
│   │   ├── security.py             # Auth dependencies & Supabase JWT verification
│   │   ├── logging.py              # Structured JSON logging
│   │   ├── exceptions.py           # Domain exceptions & uniform HTTP handlers
│   │   └── database.py             # Async SQLAlchemy engine & Supabase client hook
│   ├── domain/                     # Pure domain models (zero UI logic)
│   │   ├── users/
│   │   ├── goals/
│   │   ├── journeys/
│   │   ├── concepts/
│   │   ├── learner/
│   │   ├── mentor/
│   │   ├── sessions/
│   │   ├── resources/
│   │   └── revision/
│   ├── schemas/                    # Pydantic v2 Request/Response contracts
│   ├── ai/                         # Vendor-neutral AI layer
│   │   ├── providers/              # LLMProvider interface, MockLLMProvider, ProviderFactory
│   │   ├── prompts/                # Structured pedagogical prompt templates
│   │   ├── schemas/                # Structured AI output schemas
│   │   ├── orchestrator/           # MentorOrchestrator
│   │   └── evaluators/             # SessionEvaluator
│   ├── repositories/               # Data access layer (in-memory + DB-backed)
│   ├── services/                   # Business and pedagogical services
│   └── workers/                    # Background jobs (retention risk decay monitoring)
├── tests/                          # Complete automated test suite (pytest + httpx)
├── export_openapi.py               # Script to generate openapi.json for Flutter client
├── openapi.json                    # Exported OpenAPI contract
├── pytest.ini                      # Pytest configuration
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment template
└── .env                            # Local configuration
```

---

## Environment Variables

Placeholders are configured in `.env.example`:

| Variable | Description | Default (Dev) |
|---|---|---|
| `APP_ENV` | Application environment (`development`, `production`) | `development` |
| `DEBUG` | Enable verbose debugging and stack traces | `true` |
| `SUPABASE_URL` | Supabase project URL | `https://placeholder.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role secret | `placeholder-service-role-key` |
| `SUPABASE_ANON_KEY` | Supabase client anonymous key | `placeholder-anon-key` |
| `DATABASE_URL` | PostgreSQL connection string | `sqlite+aiosqlite:///:memory:` |
| `LLM_PROVIDER` | AI provider selector (`mock`, `gemini`, `openai`) | `mock` |
| `LLM_API_KEY` | Active AI vendor API key | `mock-key` |
| `LLM_MODEL` | Model name identifier | `mock-model` |
| `EMBEDDING_MODEL` | Vector embedding model name | `text-embedding-3-small` |

---

## Quickstart & Local Execution

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Development Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
- Interactive Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- Interactive ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- Root Health Check: [http://localhost:8000/health](http://localhost:8000/health)
- API v1 Health Check: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

### 3. Run Automated Tests
```bash
pytest -v
```

### 4. Export OpenAPI Contract for Flutter
```bash
python export_openapi.py
```
This updates `backend/openapi.json` for code generation or contract validation in Flutter.
