# Market Window (Private Repository)

> **Confidential** – This codebase contains proprietary marketplace tooling for Market Window and must not be redistributed or published openly. Owner approval is required for cloning.

## Overview
Market Window is a vertically integrated marketplace platform for managing verified shops, tracked inventory, and secure buyer/seller experiences. The backend is a Flask application exposing role-specific blueprints for admins, sellers, and buyers. HTMX and Alpine.js power the interactive frontend to keep pages lightweight while supporting responsive layouts and partial updates.

### Core Principles
- **Verification First** – Only admin-approved, OTP-validated shops are visible to buyers.
- **Stock Auditability** – Every inventory mutation is mirrored in the `StockUpdate` model with undo support and low-stock monitoring.
- **Secure OTP Workflow** – OTPs are hashed, expire after use, and are single-active-per-type.
- **Role Separation** – Routes, templates, and permissions are isolated for sellers, buyers, and admins.

## Tech Stack
| Layer | Technology |
| --- | --- |
| Backend | Flask, Flask-SQLAlchemy, Flask-Migrate |
| Database | PostgreSQL |
| Frontend | HTMX, Alpine.js, standard HTML/CSS templates |
| Deployment | Gunicorn (Procfile) |

Dependencies are listed in `requirements.txt`.

## Project Structure
```
backend/
  mw_app/
    __init__.py          # App factory, blueprint registration
    models/              # SQLAlchemy models (Category, Shop, Product, etc.)
    routes/              # admin_routes.py, seller_routes.py, buyer_routes.py
    static/              # CSS, JS, images
    templates/           # Jinja2 templates with HTMX/Alpine snippets
config.py                # Base configuration (SECRET_KEY, DATABASE_URL)
run.py                   # Local entry point for Flask dev server
```

## Local Development
1. **Clone** the repository (private access only).
2. **Create a virtual environment** (Python 3.10+ recommended):
   ```bash
   python -m venv mw_env
   source mw_env/bin/activate  # Windows: mw_env\Scripts\activate
   ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Configure environment variables** (recommended via `.env`, which is gitignored):
   ```env
   SECRET_KEY=change-me
   DATABASE_URL=postgresql://postgres:admin123@localhost:5432/market_window
   FLASK_APP=run.py
   FLASK_ENV=development
   ```
5. **Run database migrations** (after defining models):
   ```bash
   flask db upgrade
   ```
6. **Start the development server**:
   ```bash
   flask run
   # or
   python run.py
   ```

## Key Workflows & Rules
- **Verification Workflow**
  - Admin reviews shop submissions and sets `VerificationStatus`.
  - OTPs are hashed, time-bound, and invalidated after use.
  - Buyers only see shops with `is_verified=True`.
- **Stock Management**
  - Every change must insert a `StockUpdate` entry.
  - Bulk or inline edits must remain atomic and support undo.
  - Low-stock indicators should be updated via HTMX partials.
- **Frontend Guidelines**
  - Prefer HTMX for partial refreshes and Alpine.js for UI logic.
  - Preserve responsive layouts across templates.
- **Routing**
  - Admin, seller, and buyer endpoints live under their respective blueprints (`/admin`, `/seller`, `/buyer`).
  - New route handlers should be added to the existing files rather than new modules, unless explicitly approved.

## Deployment Notes
- Gunicorn is the default WSGI server (see `Procfile`).
- Keep secrets in platform-specific config (Heroku, Render, etc.).
- Ensure migrations are applied before promoting releases.

## Testing
- Place automated tests under `tests/` and use `pytest` (cache directories are ignored via `.gitignore`).
- When adding features, include regression tests for verification, stock updates, and OTP flows.

## Contribution Policy
- This repo is **not** open source. Share code only with authorized team members.
- All changes require code review. Provide diffs and reference affected models/routes/templates.
- Follow the "Market Window project guidelines" to maintain consistency and compliance.

For additional internal documentation, consult the `docs/` directory or reach out to the Market Window platform team.
