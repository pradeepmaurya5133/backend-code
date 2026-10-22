"""Production readiness checks (Phase 6).

Everything here defaults to convenient-for-development, which is wrong for a
deployment. These checks name each insecure default explicitly. In a production
environment they are fatal, because silently running with `SECRET_KEY=change-me`
is worse than failing to start.
"""

MIN_SECRET_BYTES = 32
INSECURE_SECRETS = {"change-me", "secret", "changeme", "password", ""}


class InsecureConfiguration(RuntimeError):
    pass


def findings(settings) -> list[dict]:
    """Every configuration problem, with severity. Empty means ready."""
    issues: list[dict] = []

    if settings.secret_key in INSECURE_SECRETS:
        issues.append(
            {
                "setting": "SECRET_KEY",
                "severity": "critical",
                "detail": "Still the default value. It signs JWTs and keys API-key hashes.",
                "fix": "Set SECRET_KEY to 32+ random bytes.",
            }
        )
    elif len(settings.secret_key.encode()) < MIN_SECRET_BYTES:
        issues.append(
            {
                "setting": "SECRET_KEY",
                "severity": "high",
                "detail": f"Only {len(settings.secret_key.encode())} bytes; HS256 wants {MIN_SECRET_BYTES}+.",
                "fix": f"Use at least {MIN_SECRET_BYTES} bytes.",
            }
        )

    if not settings.auth_enabled:
        issues.append(
            {
                "setting": "AUTH_ENABLED",
                "severity": "critical",
                "detail": "Authentication is off; every caller is treated as a local operator with all scopes.",
                "fix": "Set AUTH_ENABLED=true and issue API keys.",
            }
        )

    if not settings.data_encryption_key:
        issues.append(
            {
                "setting": "DATA_ENCRYPTION_KEY",
                "severity": "high",
                "detail": "Secrets are encrypted with a key derived from SECRET_KEY, so rotating "
                "SECRET_KEY would orphan every stored secret.",
                "fix": "Generate a dedicated Fernet key.",
            }
        )

    if settings.database_url.startswith("sqlite"):
        issues.append(
            {
                "setting": "DATABASE_URL",
                "severity": "medium",
                "detail": "SQLite does not support concurrent writers or more than one worker.",
                "fix": "Point DATABASE_URL at PostgreSQL.",
            }
        )

    if "*" in settings.cors_origins:
        issues.append(
            {
                "setting": "CORS_ORIGINS",
                "severity": "high",
                "detail": "A wildcard origin lets any site call this API with credentials.",
                "fix": "List your client origins explicitly.",
            }
        )

    if not settings.anthropic_api_key:
        issues.append(
            {
                "setting": "ANTHROPIC_API_KEY",
                "severity": "medium",
                "detail": "No model configured; agent calls will report llm_not_configured.",
                "fix": "Set ANTHROPIC_API_KEY.",
            }
        )

    return issues


def report(settings) -> dict:
    found = findings(settings)
    blocking = [f for f in found if f["severity"] == "critical"]
    return {
        "environment": settings.environment,
        "ready_for_production": not found,
        "blocking": len(blocking),
        "findings": found,
    }


def enforce(settings) -> list[dict]:
    """Raise on critical findings when running in production."""
    found = findings(settings)
    if settings.environment.lower() not in ("production", "prod"):
        return found
    blocking = [f for f in found if f["severity"] == "critical"]
    if blocking:
        lines = "\n".join(f"  - {f['setting']}: {f['detail']} ({f['fix']})" for f in blocking)
        raise InsecureConfiguration(
            f"Refusing to start in production with insecure configuration:\n{lines}"
        )
    return found
