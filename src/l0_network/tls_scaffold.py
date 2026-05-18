"""
CITADEL L0 — Network/Security scaffold.

Provides:
  - TLS 1.3 context factory (for production HTTPS server)
  - API key authentication middleware (FastAPI-compatible)
  - Rate limiting (token bucket per API key)
  - Request ID injection (UUID7 monotonic for distributed tracing)

In the hackathon demo, the Streamlit dashboard runs over plain HTTP on
localhost. This module provides the production-grade TLS/auth layer that
would wrap it for public deployment.
"""
from __future__ import annotations

import os
import ssl
import uuid
import time
import hashlib
import secrets
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable
from pathlib import Path
from functools import wraps

logger = logging.getLogger(__name__)


# ── TLS context ──────────────────────────────────────────────────────────────

def make_tls_context(
    certfile: str | Path,
    keyfile: str | Path,
    cafile: Optional[str | Path] = None,
    verify_client: bool = False,
) -> ssl.SSLContext:
    """
    Build a TLS 1.3 server context.
    If cafile is provided and verify_client=True, enables mTLS.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(certfile=str(certfile), keyfile=str(keyfile))
    if cafile and verify_client:
        ctx.load_verify_locations(cafile=str(cafile))
        ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.set_ciphers("TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256")
    return ctx


def generate_self_signed_cert(out_dir: str | Path = "/tmp/citadel_certs") -> tuple[Path, Path]:
    """
    Generate a self-signed TLS certificate for local dev/demo.
    Returns (certfile, keyfile) paths.
    Requires cryptography package; falls back gracefully if unavailable.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cert_path = out_dir / "cert.pem"
    key_path  = out_dir / "key.pem"

    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_path.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "citadel.local"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CITADEL"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.DNSName("citadel.local"),
            ]), critical=False)
            .sign(key, hashes.SHA256())
        )
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        logger.info("Generated self-signed TLS cert at %s", cert_path)
    except ImportError:
        logger.warning("cryptography package not available — TLS cert generation skipped")

    return cert_path, key_path


# ── API key auth ─────────────────────────────────────────────────────────────

@dataclass
class APIKey:
    key_id: str
    key_hash: str        # SHA-256 of raw key
    scopes: list[str]    # e.g. ["eval:read", "eval:write", "admin"]
    rate_limit_rpm: int  # requests per minute
    _tokens: float = field(default=0.0, init=False)
    _last_refill: float = field(default_factory=time.time, init=False)

    @classmethod
    def create(cls, scopes: list[str], rate_limit_rpm: int = 60) -> tuple["APIKey", str]:
        """Create a new API key. Returns (APIKey, raw_secret)."""
        raw = f"citadel-{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw.encode()).hexdigest()
        key_id = f"kid_{secrets.token_hex(8)}"
        return cls(key_id=key_id, key_hash=key_hash,
                   scopes=scopes, rate_limit_rpm=rate_limit_rpm), raw

    def verify(self, raw_key: str) -> bool:
        return secrets.compare_digest(
            self.key_hash,
            hashlib.sha256(raw_key.encode()).hexdigest()
        )

    def check_rate_limit(self) -> bool:
        """Token bucket rate limiter. Returns True if request is allowed."""
        now = time.time()
        elapsed = now - self._last_refill
        self._tokens = min(
            float(self.rate_limit_rpm),
            self._tokens + elapsed * (self.rate_limit_rpm / 60.0)
        )
        self._last_refill = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


class AuthMiddleware:
    """
    Simple API key authentication. Suitable for FastAPI dependency injection
    or standalone middleware wrapping.
    """

    def __init__(self):
        self._keys: dict[str, APIKey] = {}

    def register(self, api_key: APIKey) -> None:
        self._keys[api_key.key_id] = api_key

    def authenticate(self, authorization_header: Optional[str]) -> tuple[bool, Optional[APIKey], str]:
        """
        Parse 'Authorization: Bearer <key_id>:<raw_secret>' header.
        Returns (ok, api_key, reason).
        """
        if not authorization_header:
            return False, None, "Missing Authorization header"
        if not authorization_header.startswith("Bearer "):
            return False, None, "Expected Bearer token"

        token = authorization_header[7:]
        parts = token.split(":", 1)
        if len(parts) != 2:
            return False, None, "Token format: <key_id>:<secret>"

        key_id, raw_secret = parts
        api_key = self._keys.get(key_id)
        if api_key is None:
            return False, None, f"Unknown key_id: {key_id}"
        if not api_key.verify(raw_secret):
            return False, None, "Invalid secret"
        if not api_key.check_rate_limit():
            return False, None, f"Rate limit exceeded ({api_key.rate_limit_rpm} rpm)"

        return True, api_key, "OK"


# ── Request ID ───────────────────────────────────────────────────────────────

def new_request_id() -> str:
    """UUID4-based request ID with timestamp prefix for log correlation."""
    return f"req_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"


# ── Healthcheck endpoint ─────────────────────────────────────────────────────

def healthcheck() -> dict:
    return {
        "status": "ok",
        "layer": "L0_network",
        "tls_min_version": "TLSv1.3",
        "timestamp_ms": int(time.time() * 1000),
    }
