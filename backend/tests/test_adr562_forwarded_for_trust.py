"""X-Forwarded-For is trusted only from the proxy (ADR-562).

Every slowapi limit keys on the client IP ProxyHeadersMiddleware produces. It
trusted "*". Measured on staging, a spoofed header reached the log as the real
address -- because Caddy, the edge, overwrites it. These pin both halves so the
safety stops depending on nobody touching either.
"""
import asyncio
import pathlib

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.config import settings

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _client_seen(peer: str, xff: str | None) -> str:
    seen = {}

    async def app(scope, receive, send):
        seen["client"] = scope["client"][0]

    mw = ProxyHeadersMiddleware(app, trusted_hosts=[h.strip() for h in settings.trusted_proxy_hosts.split(",")])
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    scope = {"type": "http", "client": (peer, 5555), "headers": headers, "scheme": "http"}
    asyncio.run(mw(scope, None, None))
    return seen["client"]


def test_a_spoof_from_outside_the_network_is_ignored():
    """Anything reaching :8000 without Caddy keeps its own address."""
    assert _client_seen("198.51.100.9", "203.0.113.77") == "198.51.100.9"


def test_caddy_on_the_compose_network_is_believed():
    """Staging's Caddy was 172.18.0.8 on 172.18.0.0/16."""
    assert _client_seen("172.18.0.8", "172.56.30.194") == "172.56.30.194"


def test_the_app_never_trusts_everyone():
    from app.main import app
    mw = next(m for m in app.user_middleware if m.cls is ProxyHeadersMiddleware)
    hosts = mw.kwargs["trusted_hosts"]
    assert "*" not in hosts and hosts, hosts


def test_caddy_decides_the_client_ip_itself():
    """Caddy without trusted_proxies overwrites an incoming X-Forwarded-For.
    Adding a CDN means changing this AND the backend list, in one decision."""
    caddy = (ROOT / "Caddyfile").read_text()
    assert "trusted_proxies" not in caddy


def test_an_appended_chain_yields_the_address_the_edge_saw_not_the_one_the_client_wrote():
    """uvicorn under "*" (always_trust) takes the LEFTMOST entry -- the one a
    client writes. Under a trust list it walks right to left and takes the
    first untrusted host -- the one the edge appended. If any proxy ever
    appends instead of overwriting, "*" hands the attacker's value to the
    rate limiter."""
    assert _client_seen("172.18.0.8", "203.0.113.77, 172.56.30.194") == "172.56.30.194"
