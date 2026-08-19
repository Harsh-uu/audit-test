# CRITICAL: Frontend has NO hot reload in this repo

`frontend/package.json` "start" script is `vite build && vite preview` (production
build served statically, likely intentional to test the PWA/service-worker layer).
This means:
- Editing frontend .js files does NOT hot-reload. The preview keeps serving the
  OLD bundle (hashed filename, e.g. MeetingReport-CbR36bx3.js) until rebuilt.
- After ANY frontend code change, MUST run `sudo supervisorctl restart frontend`
  and wait ~15-30s for `vite build && vite preview` to finish before testing/
  screenshotting, otherwise you'll be testing stale code and waste time debugging
  a "fix" that never shipped.
- Confirmed via browser console error stack trace pointing at a bundle hash that
  didn't match latest source (Aug 2026, session 15/41 — "Create Action from
  Risk" crash fix appeared not to work until frontend was rebuilt).
