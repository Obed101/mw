## Long-Term Product Roadmap
### Purpose
Define long-horizon product and UX improvements to be implemented iteratively after current core milestones.

### 1. Product Experience
- Build a dedicated product view page with extended product details and more action buttons.
- Make products reviewable by users.
- Show review comments on the product view page.

### 2. Shop Management and Merchant Experience
- Redesign the shop management header to match the profile-page style, including logo/primary photo and cover image support.
- Support flippable shop media with a maximum of 2 header images.
- Add a full product management list on the shop management page with live action controls:
  increment/decrement stock, discontinue product, pin to top in shop view, and similar quick actions.
- Replace image-URL-based shop photo input with a modern media picker/upload flow.

### 3. Shop Discovery, Onboarding, and Claiming
- Allow users to add shops they discover on the street.
- Add a shop claiming workflow so real owners can claim and verify existing shop listings later.

### 4. Search and Discovery Improvements
- Improve search usability on the home page for faster discovery.
- Add image search to support visual product/shop discovery.

### 5. Data Quality and Validation
- Fix phone number issues on the profile page.
- Replace free-text region/district/town fields with validated autocompletes.

### 6. Category and Recommendation Intelligence
- Redesign category cards to be smaller and cleaner:
  remove details from cards, remove open/products buttons, and make cards directly clickable.
- On category open, show category details together with relevant products in that category.
- Replace parent category badge behavior so it displays the highest-level category for easier identification.
- Add view counts to categories, products, and shops to improve recommendation quality.

---------------------------------------------------------------------
## Task 10 - Release Readiness and Handoff
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

## Task 11 â€” Subdomain Routing Foundation (Planned for Later Activation)
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



