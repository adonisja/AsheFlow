// Some dependencies read Node's `global`. A file, not an inline script, so the
// Content Security Policy needs no hash for it (ADR-574 D4).
window.global = window;
