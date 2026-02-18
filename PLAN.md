# Modern UI/UX Implementation Plan for Market Window (Purple/Blue Blend Theme)

## Goal
Build and polish the Market Window platform so that each page is production-ready, role-aware (Admin/Seller/Buyer), and visually consistent with modern UI/UX standards, using the existing Purple/Blue visual system defined in `backend/mw_app/static/css/style.css`.

## Design Direction (Applies to all tasks)
- Use the existing gradient and palette tokens from `:root` in `style.css`:
  - `--primary-purple: #6B46C1`
  - `--secondary-mauve: #9333EA`
  - `--accent-blue: #3B82F6`
  - `--dark-purple: #4C1D95`
  - `--light-mauve: #E9D5FF`
  - `--gradient-primary: linear-gradient(135deg, #6B46C1 0%, #9333EA 50%, #3B82F6 100%)`
- Maintain a modern product feel:
  - clean spacing and readable typography
  - card-based layouts for content-heavy screens
  - clear visual hierarchy for CTAs
  - responsive behavior for desktop + mobile
  - meaningful empty, loading, and error states
- Preserve accessibility basics:
  - adequate contrast, visible focus states
  - keyboard navigable controls
  - semantic form labels and inline validation messaging

---

## Task 1 — Environment and Baseline Setup
### Objective
Ensure every contributor can run the project consistently before feature work starts.

### Detailed actions
1. Create and activate a Python virtual environment (Python 3.10+).
2. Install dependencies from root `requirements.txt`.
3. Define local environment variables (`SECRET_KEY`, `DATABASE_URL`, `FLASK_APP`, `FLASK_ENV`).
4. Run database migrations and verify migration history is clean.
5. Start the application and confirm base routes render.

### Deliverables
- Working local environment.
- Confirmed database connectivity.
- Developer runbook section (or notes) validated by a second machine/user.

### Acceptance criteria
- App starts without runtime import/config errors.
- Database migration command completes successfully.
- Home/login/register pages load.

---

## Task 2 — Data Model and Business Rule Validation
### Objective
Validate that core marketplace entities and relationships enforce business rules.

### Detailed actions
1. Review models for: categories, shops, products, users, subscriptions, OTP lifecycle, stock updates.
2. Confirm role constraints (admin/seller/buyer) and ownership checks.
3. Verify verification fields (`is_verified`, status enums) are used consistently.
4. Ensure stock mutation operations always produce audit trail records.
5. Add/adjust model-level validation where missing.

### Deliverables
- Model consistency checklist.
- Any required migration scripts for schema changes.

### Acceptance criteria
- No orphaned relationships from expected user flows.
- Verification + stock rules are enforceable from backend logic.

---

## Task 3 — Authentication and Session Flows
### Objective
Deliver secure, reliable login/register/logout and OTP verification behavior.

### Detailed actions
1. Validate auth routes and forms for registration/login/logout.
2. Confirm password handling is secure (hashing, no plaintext persistence).
3. Ensure OTP flow is single-use, hashed, and expiry-aware.
4. Improve UX feedback in auth templates:
   - clear error copy
   - success messages
   - recovery/next-step guidance
5. Confirm session behavior is correct across roles.

### Deliverables
- Stable auth flow with role-aware redirection.
- Improved auth page UX messaging.

### Acceptance criteria
- Invalid credentials and expired OTPs are handled gracefully.
- Successful auth always lands user in appropriate dashboard path.

---

## Task 4 — Role-Based Route Audit (Admin/Seller/Buyer)
### Objective
Ensure each role only accesses permitted routes and actions.

### Detailed actions
1. Audit route files (`admin_routes.py`, `seller_routes.py`, `buyer_routes.py`, `auth_routes.py`, `template_routes.py`).
2. Verify decorators/guards and role checks on each sensitive endpoint.
3. Confirm unauthorized access returns safe redirects/errors.
4. Verify route naming, endpoint consistency, and blueprint prefixes.
5. Remove or lock down routes not intended for production.

### Deliverables
- Route access matrix (role vs endpoint).
- Patched access control gaps.

### Acceptance criteria
- Buyers cannot execute seller/admin operations.
- Sellers cannot access admin-only controls.
- Admin can perform verification and oversight actions as designed.

---

## Task 5 — Seller Experience Completion
### Objective
Provide a full seller workflow with clear UX and strong feedback.

### Detailed actions
1. Confirm seller dashboard metrics and widgets load correctly.
2. Validate product create/update/delete flows with proper form errors.
3. Ensure inventory updates are atomic and create stock history entries.
4. Add UX patterns for low-stock warnings and undo actions.
5. Standardize seller pages with consistent card spacing, CTA placement, and state indicators.

### Deliverables
- End-to-end seller inventory flow.
- Polished seller dashboard and inventory interaction UX.

### Acceptance criteria
- Seller can manage catalog and stock without inconsistent states.
- Each inventory action is reflected in both product stock and history.

---

## Task 6 — Buyer Experience Completion
### Objective
Enable buyers to discover verified shops/products with fast, clear interactions.

### Detailed actions
1. Validate buyer shop listing only includes verified shops.
2. Ensure product browsing supports category-based discovery.
3. Optimize partial updates (HTMX) for filters, cards, and pagination states.
4. Improve empty results UX with actionable copy (e.g., "Try another category").
5. Ensure all buyer pages use modern UI patterns and theme consistency.

### Deliverables
- Verified-shop browsing flow.
- Buyer-facing templates with consistent visual treatment.

### Acceptance criteria
- Unverified shops are never shown to buyers.
- Product/shop pages are responsive and visually coherent.

---

## Task 7 — Unified UI/UX Design System Pass
### Objective
Apply a cohesive modern UI/UX pass across all templates using the Purple/Blue blend foundation.

### Detailed actions
1. Inventory all templates under `backend/templates/`.
2. Align layout primitives:
   - spacing scale
   - border radius
   - shadow depth
   - card headers/footers
3. Standardize components:
   - buttons (`btn-primary`, `btn-outline-primary`)
   - nav links and active states
   - form controls and validation states
   - badges/chips for status
4. Ensure nav paradigms are stable:
   - fixed top navbar
   - desktop sidebar behavior
   - mobile bottom-nav behavior
5. Enforce brand color continuity via CSS variables and `--gradient-primary`.

### Deliverables
- Cross-page UI consistency report.
- Refined style definitions and template classes.

### Acceptance criteria
- No page looks visually disconnected from platform brand.
- Primary interactions share a predictable component language.

---

## Task 8 — Front-End Interaction Quality (HTMX + Alpine.js)
### Objective
Keep interactions lightweight and smooth without full-page reload dependence.

### Detailed actions
1. Audit existing dynamic behaviors in templates and `main.js`.
2. Ensure HTMX partial updates target correct containers.
3. Add loading indicators/skeletons for async partial refreshes.
4. Validate Alpine state transitions for dropdowns/nav/user menu behavior.
5. Ensure no JS errors in common flows.

### Deliverables
- Stable, low-latency interaction patterns.
- Documented behavior for each dynamic component.

### Acceptance criteria
- Partial updates do not break layout or event behavior.
- Console remains clean during primary user journeys.

---

## Task 9 — Testing, QA, and Regression Coverage
### Objective
Prevent breakages in verification, inventory, and role separation logic.

### Detailed actions
1. Add/extend `pytest` coverage for:
   - auth and OTP edge cases
   - role access restrictions
   - verification filtering
   - stock update + undo behavior
2. Add route smoke tests for key templates.
3. Execute manual QA script for seller/buyer/admin flows.
4. Record and fix high-severity UX defects.

### Deliverables
- Automated test updates and run logs.
- Manual QA checklist with pass/fail results.

### Acceptance criteria
- Critical user journeys pass automated and manual checks.
- No regression in verification or stock auditability behavior.

---

## Task 10 — Release Readiness and Handoff
### Objective
Prepare the project for safe deployment and easy team handoff.

### Detailed actions
1. Re-check environment variable requirements and deployment config.
2. Verify migration state is up-to-date for target environment.
3. Confirm Gunicorn entrypoint/process config is valid.
4. Produce concise release notes:
   - changed routes/models/templates
   - known limitations
   - rollback hints
5. Create handoff package for implementation owner.

### Deliverables
- Deployment checklist.
- Handoff notes for engineering and product stakeholders.

### Acceptance criteria
- Team member unfamiliar with this branch can deploy and validate core flows using documentation only.

---

## Task 11 — Subdomain Routing Foundation (Planned for Later Activation)
### Objective
Prepare a clean, low-cost architecture for splitting Market Window surfaces by subdomain (for example, `admin.marketwindowgh.com`) while keeping one Flask app, one Heroku dyno group, and one database.

### Detailed actions
1. Add Flask subdomain routing configuration:
   - set `SERVER_NAME` to `marketwindowgh.com` (environment-aware for dev/staging/prod)
   - verify host-header based routing works for root and subdomains
2. Introduce subdomain-specific route organization using blueprints:
   - keep main-site routes on the default host
   - add an admin blueprint with `subdomain="admin"`
   - migrate current admin endpoints into that blueprint without changing business logic
3. Update environment and deployment setup for Heroku + DNS:
   - add both domains in Heroku (`marketwindowgh.com`, `admin.marketwindowgh.com`)
   - add DNS CNAME (`admin -> <heroku-app>.herokuapp.com`)
   - confirm SSL/TLS coverage for apex and subdomain
4. Define local development strategy for subdomains:
   - document hosts-file or local DNS approach
   - ensure test configuration can simulate subdomain requests reliably
5. Add test coverage for host/subdomain route behavior:
   - root domain renders main experience
   - admin subdomain resolves admin dashboard/routes
   - non-matching host/subdomain combinations fail safely

### Deliverables
- Subdomain routing implementation notes and config plan.
- Blueprint structure proposal for admin isolation.
- Deployment + DNS checklist specific to subdomain rollout.

### Acceptance criteria
- `marketwindowgh.com` and `admin.marketwindowgh.com` can be served by the same Flask app in a staging validation.
- Admin functionality is reachable via subdomain routes and remains role-protected.
- Deployment documentation is explicit enough for repeatable Heroku + DNS setup.

---

## Suggested Execution Order and Ownership
1. Task 1 (Setup)
2. Task 2 (Model rules)
3. Task 3 + Task 4 (Auth + access control)
4. Task 5 + Task 6 (Seller/Buyer feature completeness)
5. Task 7 + Task 8 (UI/UX and interaction polishing)
6. Task 9 (Testing and QA)
7. Task 10 (Release handoff)
8. Task 11 (Subdomain routing activation when ready)

For team execution, assign one owner per task and require sign-off against each task's acceptance criteria before moving to the next stage.
