# ⚙️ LinkedIn Post Scheduler — Backend Core & Concurrency Engine
> **Candidate:** Amrita Maity  
> **Framework:** Flask 3 (Python 3.12) • SQLAlchemy 2.0 • MySQL 8.0 InnoDB  
> **Key Capabilities:** Row-Level Concurrency (`SKIP LOCKED`), AES-256 Token Enclave, Google Gemini AI, Resilient Retries

---

## 📌 Architectural Highlights

The backend is engineered for high reliability, concurrency safety, and cryptographic data protection:

1. **Race-Condition-Free Worker (`publisher_worker.py`):**
   - Implements MySQL 8.0 `SELECT ... FOR UPDATE SKIP LOCKED` inside a strict database transaction.
   - Allows multiple publisher workers to run simultaneously without duplicate dispatches or deadlock states.
2. **At-Rest Token Encryption Enclave (`crypto_service.py`):**
   - Uses **Fernet symmetric encryption (AES-256 in CBC mode with HMAC-SHA256 authentication)**.
   - Plaintext OAuth tokens never touch the database disk or application logs.
3. **Google Gemini AI Ghostwriter (`llm_service.py`):**
   - Leverages `gemini-3.5-flash-lite` with fallback resilience.
   - Guarantees 100% preservation of author hashtags and appends 3–5 trending tags to boost feed impressions.
4. **Resilient Retry & Backoff Engine (`retry_policy.py`):**
   - Distinguishes between **transient errors** (HTTP 429 Rate Limits, 502/503/504 gateway failures, network timeouts) and **fatal errors** (HTTP 400 Bad Request, 401 Invalid Token).
   - Implements exponential backoff with jitter up to `max_attempts = 5`.
5. **Audit Logging & Telemetry:**
   - Every single attempt is logged to `post_attempts` with response codes and error traces.

---

## 🏗️ Directory Layout

```text
backend/
├── app.py                      # Flask App Factory & embedded worker thread startup
├── config.py                   # Pydantic Settings & environment variable validation
├── db.py                       # SQLAlchemy session scope context manager & engine
├── models.py                   # ORM Models: User, LinkedInConnection, Post, PostAttempt
├── requirements.txt            # Production & development dependencies
├── ruff.toml                   # Linter & formatter configuration
├── schema.sql                  # MySQL 8.0 DDL schema with composite indices
├── controllers/
│   ├── auth_controller.py      # OAuth 2.0 PKCE, session management, persona switching
│   ├── post_controller.py      # CRUD, scheduling, metrics, soft cancel
│   └── ai_controller.py        # Gemini AI prompt polish, rewrite, and brainstorm
├── services/
│   ├── linkedin_service.py     # LinkedIn REST API v2 client (ugcPosts, userinfo)
│   ├── crypto_service.py       # Fernet AES-256 encryption & decryption enclave
│   ├── llm_service.py          # Google Gemini AI integration & prompt governance
│   └── retry_policy.py         # Exponential backoff calculator & error classifier
├── workers/
│   └── publisher_worker.py     # Concurrency-safe publisher daemon (15s poll loop)
├── scripts/
│   └── init_db.py              # Idempotent DB setup & version check script
└── tests/
    ├── conftest.py             # Pytest fixtures & mock engines
    ├── unit/                   # Unit tests (crypto, linkedin, llm, retry, state machine)
    └── integration/            # Concurrency & API endpoint tests
```

---

## 📡 REST API Reference

### 🔐 Authentication & LinkedIn OAuth
| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/auth/me` | `GET` | Returns currently active user persona and LinkedIn connection status. |
| `/api/v1/auth/personas` | `GET` | Lists all available personas for testing multi-tenant isolation. |
| `/api/v1/auth/personas/switch` | `POST` | Switch active persona (`Amrita Maity`, `Krishna`, `Ram`, `Shiv`). |
| `/api/v1/auth/linkedin/login` | `GET` | Generates OAuth 2.0 PKCE authorization URL and sets CSRF cookie. |
| `/api/v1/auth/linkedin/callback` | `GET` | Exchanges code for access token, encrypts via AES-256, and links account. |
| `/api/v1/auth/linkedin/disconnect` | `POST` | Revokes and deletes encrypted token from database. |

### 📝 Posts & Scheduling
| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/posts` | `GET` | List user posts with pagination (`page`, `per_page`) and filter (`status`). |
| `/api/v1/posts` | `POST` | Create and schedule a new post (`content`, `scheduled_at_utc`, `media`). |
| `/api/v1/posts/<id>` | `GET` | Retrieve single post details and attempt audit log. |
| `/api/v1/posts/<id>/cancel` | `POST` | Soft-cancel a scheduled post before background dispatch. |
| `/api/v1/posts/metrics` | `GET` | Real-time counts: total, scheduled, processing, published, failed, cancelled. |
| `/api/v1/posts/<id>/attempts` | `GET` | Detailed audit history of all publishing attempts for a post. |

### 🤖 Google Gemini AI Copilot
| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/ai/rewrite` | `POST` | Refine post text with Google Gemini AI (`content`, `tone`, `author_tags`). |
| `/api/v1/ai/brainstorm` | `POST` | Generate high-engagement LinkedIn post hooks and outlines from a raw topic. |

---

## 🛠️ Environment Configuration (`.env`)

Create a `.env` file in the `backend/` directory based on the following template:

```ini
# Flask Configuration
FLASK_ENV=development
SECRET_KEY=generate-a-secure-random-32-byte-secret-key
PORT=5000

# Database Configuration (MySQL 8.0)
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=assesment
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_APP_USER=
DB_APP_PASSWORD=

# Security Enclave (Fernet AES-256 Key)
# Generate using: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=your-32-byte-base64-encoded-fernet-key

# Google Gemini AI Integration
GEMINI_API_KEY=your_google_gemini_api_key
GEMINI_MODEL=gemini-3.5-flash-lite

# LinkedIn Developer App Credentials (OAuth 2.0)
LINKEDIN_CLIENT_ID=your_linkedin_client_id
LINKEDIN_CLIENT_SECRET=your_linkedin_client_secret
LINKEDIN_REDIRECT_URI=http://127.0.0.1:5000/api/v1/auth/linkedin/callback
LINKEDIN_SCOPES=openid,profile,w_member_social

# Background Publisher Worker Specs
WORKER_POLL_INTERVAL=15
WORKER_BATCH_SIZE=10
WORKER_MAX_ATTEMPTS=5
```

---

## 🚀 Running Backend Services

### 1. Database Initialization
Verify that MySQL 8.0 is running and execute the database provisioning script:
```bash
python scripts/init_db.py
```
*This validates MySQL version >= 8.0, creates the database with `utf8mb4`, and applies `schema.sql` idempotently.*

### 2. Start Application Server
```bash
python app.py
```
*Starts Flask on `http://127.0.0.1:5000` with the embedded background publisher daemon running in a background thread.*

### 3. Run Standalone Worker (Optional)
If running multiple dedicated worker nodes:
```bash
python -m backend.workers.publisher_worker
```

---

## 🧪 Automated Testing

The backend includes a comprehensive automated test suite with unit tests and integration tests.

Run all tests:
```bash
pytest tests -v
```

### Test Coverage Highlights:
* `test_crypto.py`: Verifies round-trip Fernet AES-256 encryption and tamper detection.
* `test_linkedin_service.py`: Mocks LinkedIn API v2 ugcPosts, error codes, and token payloads.
* `test_llm_service.py`: Tests Gemini prompt structure, tone parameters, and hashtag preservation directives.
* `test_retry_policy.py`: Verifies exponential backoff with jitter and transient/fatal error categorization.
* `test_state_machine.py`: Enforces valid post lifecycle transitions (`scheduled` -> `processing` -> `published`).
* `test_worker_concurrency.py`: Simulates concurrent worker processes claiming records using `FOR UPDATE SKIP LOCKED` without race conditions.
* `test_api_endpoints.py`: End-to-end integration tests for REST routes.
