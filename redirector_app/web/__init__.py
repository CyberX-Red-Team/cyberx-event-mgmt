"""Standalone web UI sub-package for the Redirector Manager.

Contains everything specific to the browser-facing web interface:
  auth.py       — bcrypt password verification + JWT cookie session management
  log_buffer.py — in-memory rotating log handler for the error log viewer
  middleware.py — CSRF protection middleware
  pages.py      — HTML route handlers (login, dashboard, redirectors, logs)
  templates/    — Self-contained Jinja2 templates (no dependency on cyberx-event-mgmt)
  static/       — Static assets (logo, etc.)

This sub-package is standalone-mode only. It is NOT included in the
cyberx-event-mgmt integration, which uses its own auth and layout system.
"""
