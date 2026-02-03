# Sentinel Scout Agent MVP

AI-Native Agency Platform - Website Analysis Agent

## Overview

Sentinel is an AI-native agency platform where autonomous agents handle spec work, code generation, and campaign delivery. This MVP implements the **Scout Agent** for automated website analysis.

### Features

- **Website Audits**: Comprehensive analysis using Lighthouse and Claude AI
- **Screenshot Capture**: Desktop and mobile viewport screenshots
- **Brand Extraction**: Colors, fonts, CTAs, and logo detection
- **AI Recommendations**: Actionable insights for improvement
- **Competitor Analysis**: Compare against up to 5 competitors

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      SUPABASE                                │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│   │    Auth     │  │  Postgres   │  │   Storage   │        │
│   │ (Magic Link)│  │  (Projects) │  │ (Reports)   │        │
│   └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│    RENDER WEB SERVICE   │     │   RENDER BACKGROUND     │
│    (FastAPI + API)      │────▶│   WORKER (Scout Agent)  │
│    - REST endpoints     │     │   - Playwright          │
│    - Auth middleware    │     │   - Claude analysis     │
│    - Job queuing        │     │   - Report generation   │
└─────────────────────────┘     └─────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Redis (for local development)
- Supabase account
- Anthropic API key

### Local Development

1. **Clone and setup:**

```bash
cd sentinel-mvp
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
npx playwright install chromium --with-deps
```

2. **Configure environment:**

```bash
cp .env.example .env
# Edit .env with your credentials
```

3. **Setup Supabase:**
   - Create a new project at [supabase.com](https://supabase.com)
   - Run `supabase_schema.sql` in the SQL Editor
   - Copy credentials to `.env`

4. **Start Redis:**

```bash
# Using Docker
docker run -d -p 6379:6379 redis:alpine

# Or install locally
brew install redis && brew services start redis
```

5. **Run the API:**

```bash
uvicorn api.main:app --reload --port 8000
```

6. **Run the Worker (in another terminal):**

```bash
python -m worker.main
```

7. **Access the API:**
   - API: http://localhost:8000
   - Docs: http://localhost:8000/docs
   - Health: http://localhost:8000/health

## API Endpoints

### Authentication

```bash
# Request magic link
POST /auth/login
{"email": "user@example.com"}

# Get current user
GET /auth/me
Authorization: Bearer <token>
```

### Audits

```bash
# Create new audit
POST /audits
Authorization: Bearer <token>
{
  "url": "https://example.com",
  "competitors": ["https://competitor.com"],
  "options": {
    "includeMobile": true,
    "includeSeo": true
  }
}

# List audits
GET /audits?status=completed&limit=20

# Get audit results
GET /audits/{audit_id}

# Download report
GET /audits/{audit_id}/report?format=pdf
```

### Webhooks

```bash
# Register webhook
POST /webhooks
{
  "url": "https://your-app.com/webhook",
  "events": ["audit.completed", "audit.failed"]
}

# List webhooks
GET /webhooks

# Delete webhook
DELETE /webhooks/{webhook_id}
```

## Deployment

### Deploy to Render

1. Push code to GitHub
2. Connect repo to Render
3. Render auto-detects `render.yaml`
4. Configure environment variables in Render Dashboard:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `ANTHROPIC_API_KEY`
   - `E2B_API_KEY` (optional)
5. Deploy!

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_ANON_KEY` | Yes | Supabase anonymous key |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | Supabase service role key |
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `E2B_API_KEY` | No | E2B sandbox API key |
| `REDIS_URL` | Yes | Redis connection URL |
| `ENVIRONMENT` | No | development/production |
| `LOG_LEVEL` | No | DEBUG/INFO/WARNING/ERROR |

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_api.py -v
```

## Project Structure

```
sentinel-mvp/
├── api/
│   ├── main.py              # FastAPI entry point
│   ├── dependencies.py      # Dependency injection
│   ├── routes/
│   │   ├── auth.py          # Auth endpoints
│   │   ├── audits.py        # Audit endpoints
│   │   └── webhooks.py      # Webhook endpoints
│   └── middleware/
│       └── auth.py          # Auth & rate limiting
├── worker/
│   ├── main.py              # Worker entry point
│   └── tasks/
│       └── audit.py         # Audit processing
├── agents/
│   ├── scout.py             # Scout Agent
│   ├── sandbox.py           # E2B integration
│   └── prompts/
│       └── scout_analysis.md
├── services/
│   ├── supabase.py          # Database client
│   ├── anthropic.py         # Claude AI client
│   ├── browser.py           # Playwright automation
│   └── lighthouse.py        # Performance audits
├── schemas/
│   ├── audit.py             # Audit models
│   └── analysis.py          # Other models
├── config/
│   └── settings.py          # Configuration
├── tests/
│   ├── test_api.py
│   └── test_scout.py
├── render.yaml              # Render Blueprint
├── requirements.txt
└── supabase_schema.sql
```

## Cost Estimates

| Operation | Tokens | Cost (Claude Sonnet) |
|-----------|--------|---------------------|
| Website Analysis | ~2,000 | ~$0.04 |
| AI Recommendations | ~1,500 | ~$0.03 |
| Competitor Compare | ~1,000 | ~$0.02 |
| **Total per Audit** | **~4,500** | **~$0.09** |

## Roadmap

### Phase 1 (Current): Scout Agent MVP
- [x] Website audit automation
- [x] Lighthouse integration
- [x] Screenshot capture
- [x] AI-powered analysis
- [x] API & webhooks

### Phase 2: Creative Automation
- [ ] Strategy Agent
- [ ] Creative Agent
- [ ] Brand voice system
- [ ] Template generation

### Phase 3: Full Campaign Lifecycle
- [ ] Code Agent
- [ ] Deploy Agent
- [ ] WordPress integration
- [ ] A/B testing

### Phase 4: Scale & Intelligence
- [ ] Multi-client orchestration
- [ ] RLHF optimization
- [ ] White-label support

## License

MIT

## Support

For issues and feature requests, please use GitHub Issues.
