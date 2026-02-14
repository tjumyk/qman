# Qman: Product redesign proposal

This document proposes a **re-design** of the quota management system from the perspective of end-users and their goals, rather than a 1:1 copy of the current UI and flows.

---

## Current system (what we’re moving away from)

- **Single view:** Flat list of hosts → devices → one large table of all user quotas per device.
- **Single role:** Effectively “admin” only: view everything, edit any user’s limits.
- **Interaction:** Find host → find device → find user row → Edit → change numbers → Save.
- **No:** Search, filters, “my quota”, alerts, history, or clear separation between “view” and “manage.”

---

## Design principles for the redesign

1. **Role-first:** Different experiences for people who only need to see their own usage vs people who manage quotas for others.
2. **Outcome-focused:** Help users answer “Am I near my limit?” and “Who needs attention?” before “What is the exact block count?”
3. **Progressive disclosure:** Overview first (health, hotspots), then drill into details (devices, users, history) when needed.
4. **Safe and auditable:** Destructive or bulk actions are explicit; important changes are visible (e.g. history or audit trail where feasible).

---

## User personas and jobs-to-be-done

| Persona | Goal | Pain today |
|--------|------|------------|
| **End-user** (e.g. researcher, student) | Know “Am I OK?” and “How much can I use?” | No self-service view; must ask admins. |
| **Quota admin** (e.g. lab admin, support) | See who’s over/close to limits and fix them quickly. | One big table; hard to spot problems and slow to act. |
| **Infra / fleet admin** | See health of all hosts and devices; delegate or fix issues. | Host-centric only; no cross-host view of “problem” users or devices. |

---

## Proposed functional redesign

### 1. Two main modes (by role)

- **My usage (end-user)**  
  - Single screen: “Your quota” across all hosts/devices the user has access to.  
  - Per-filesystem: used vs limit (e.g. bar or percentage), clear “OK / warning / over” state.  
  - No edit; optional “Request increase” that notifies admins or creates a ticket (can be phase 2).

- **Manage quotas (admin)**  
  - Focus on “who needs attention” and “change a quota” without scrolling huge tables.  
  - Search by username or host; filters (e.g. over soft, over hard, by host).  
  - Edit from a user-centric or device-centric path, not only from a giant table.

This implies **backend/API**: ability to resolve “current user” (from OAuth/session) and return only that user’s quotas for “My usage,” and existing or extended APIs for admin “all users / per host / per device.”

### 2. Overview-first for admins

- **Dashboard (admin home)**  
  - High-level health: number of hosts up, number of devices with quota, counts like “users over soft limit,” “users over hard limit.”  
  - Optional: list of “hot” devices (e.g. by usage %) or “users needing attention” (over soft or hard).  
  - Links/actions: “View by host,” “View by user,” “Manage quotas.”

- **Navigation by intent**  
  - “By host” → choose host → see devices and summary (e.g. “3 users over soft”) → drill into device → user list (filterable, sortable).  
  - “By user” → search user → see that user’s quotas on all hosts/devices → edit from there.  
  - “Alerts” or “Needs attention” → list of users/devices over soft or hard → one-click jump to edit.

So we **re-design the flow** around “problem first” and “user first,” not only “host → device → table.”

### 3. Clearer, safer editing

- **Edit in context:** Open a user’s quota in a side panel or modal (or dedicated small page) instead of inline in a 10-column table.  
- **Limits in human units:** Prefer GB/TB (and inodes as counts) with sensible defaults; keep block math under the hood.  
- **Confirm meaningful changes:** e.g. “Reduce hard limit” or “Revoke quota” could require confirmation.  
- **History (if we persist in DB):** “Last changed by X at Y” or a simple audit log for limit changes (can be phase 2).

### 4. Information architecture (IA) and UI structure

- **App shell**  
  - Role-aware nav: “My usage” vs “Manage” (admin). “Dashboard” for admin; optional “Alerts.”  
  - Global search (user or host) for admins.

- **My usage**  
  - One page: list of “filesystems” (or host + device) with a compact card or row each: name, used vs limit, status (OK / warning / over).  
  - No tables of other users; no edit.

- **Manage**  
  - **Dashboard:** summary and “Needs attention” list.  
  - **By host:** Host list → host detail (devices + summaries) → device detail (user list, filters, search) → edit user.  
  - **By user:** Search → user detail (quotas on all devices) → edit.  
  - **Alerts (optional):** List of over-soft / over-hard with links to the right edit context.

- **Visual language**  
  - Status-first: color/symbol for OK / warning / over (soft vs hard).  
  - Progress or “used vs limit” bars instead of raw numbers where it helps.  
  - Dense tables only where necessary (e.g. device user list); prefer cards or rows with key info and “Edit” or “View.”

### 5. Backend and API implications

- **Current:** Master aggregates slaves; slave exposes devices and user/group quotas; master has OAuth.  
- **Reuse:** Keep master/slave and remote-api; keep auth (OAuth + admin group).  
- **Add or extend:**  
  - **“My quotas” endpoint:** e.g. `GET /api/me/quotas` that returns quotas for the current user (uid from session) across all hosts/devices. Slaves already expose per-user data; master can aggregate per-uid for the logged-in user.  
  - **Optional:** “Needs attention” or “over soft/hard” aggregation (could be computed from existing data in the frontend, or a small backend endpoint for efficiency).  
  - **Optional (phase 2):** Persist quota change history in the existing DB (e.g. who changed which limit when).

No need to copy the old “one big table per device” API; we can keep the same data but add endpoints and response shapes that match the new flows (e.g. “by user” and “my usage”).

---

## What “rewrite” means in implementation

- **Frontend:** Build the new IA and flows (My usage, Dashboard, By host, By user, Alerts, edit in context) with the existing stack (React, Mantine, TanStack Query, etc.). No copy of the old host→device→single-table layout.  
- **Backend:** Add or adjust APIs to support “my quotas” and, if useful, “needs attention”; keep existing auth and master/slave model.  
- **UX:** Design around roles, overview-first, and safe editing as above; then implement, rather than replicating the current UI.

---

## Next steps

1. **Confirm personas and priorities:** e.g. “My usage” and “Dashboard + By user” for v1; “Alerts” and “History” later.  
2. **Define “My quotas” API:** Exact shape and how to resolve “current user” (uid) from session on the master.  
3. **Wireframes or high-fidelity mockups** for: My usage page, Admin dashboard, By-user flow, Edit (modal or panel).  
4. **Implement** in this order: backend “my quotas” (and optional “needs attention”) → new frontend IA and pages → migrate away from the old single-table UI.

If you want, the next step can be a concrete **API spec** for `GET /api/me/quotas` and a **page-by-page breakdown** (routes and main components) for the new frontend.
