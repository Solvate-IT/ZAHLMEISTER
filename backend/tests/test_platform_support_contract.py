from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT.parent / "frontend"


def backend(path: str) -> str:
    return (ROOT / path).read_text()


def frontend(path: str) -> str:
    return (FRONTEND / path).read_text()


def test_admin_and_customer_sessions_use_separate_namespaces() -> None:
    auth = backend("app/services/auth.py")
    deps = backend("app/api/deps.py")
    route = backend("app/api/routes/auth.py")

    assert 'ADMIN_TOKEN_PREFIX = "zma1."' in auth
    assert "token_prefix=ADMIN_TOKEN_PREFIX" in route
    assert "not token.startswith(ADMIN_TOKEN_PREFIX)" in deps
    assert "if token.startswith(ADMIN_TOKEN_PREFIX)" in deps


def test_support_session_is_short_lived_scoped_and_server_side_read_only() -> None:
    service = backend("app/services/support_sessions.py")
    deps = backend("app/api/deps.py")
    admin_route = backend("app/api/routes/admin_support.py")

    assert "SUPPORT_SESSION_MINUTES = 60" in service
    assert '"typ": "support"' in service
    assert '"ro": True' in service
    assert "target_user.organization_id" in service
    assert "decode_support_token(token)" in deps
    assert "target_user.organization_id != support_claims.organization_id" in deps
    assert "not is_platform_admin(admin_user)" in deps
    assert "support_request_is_allowed(request.method, request.url.path)" in deps
    assert 'detail="Support view is read-only"' in deps
    assert 'action="support.impersonation_start"' in admin_route
    assert '"reason": reason' in admin_route
    assert "last_login_at" not in admin_route


def test_support_end_is_internal_admin_audit_only() -> None:
    support_route = backend("app/api/routes/support.py")

    assert '@router.post("/support-logout"' in support_route
    assert 'action="support.impersonation_end"' in support_route
    assert "PlatformAdminAudit" in support_route


def test_support_browser_context_does_not_replace_normal_customer_session() -> None:
    session = frontend("src/lib/session.ts")
    entry = frontend("src/app/support-access/page.tsx")
    workspace = frontend("src/components/Workspace.tsx")

    assert "window.sessionStorage.setItem(SUPPORT_TOKEN_KEY" in session
    assert "window.localStorage.getItem(TOKEN_KEY)" in session
    assert "supportToken() ?? window.localStorage.getItem(TOKEN_KEY)" in session
    assert 'window.history.replaceState(null,"","/support-access")' in entry
    assert 'router.replace("/app")' in entry
    assert 'router.replace(support?"/admin":"/?auth=login")' in workspace


def test_admin_ui_requires_reason_and_opens_separate_support_tab() -> None:
    admin = frontend("src/components/PlatformAdmin.tsx")

    assert 'window.prompt(t("adminSupportReason"))' in admin
    assert 'window.open("about:blank","_blank")' in admin
    assert "supportTab.opener=null" in admin
    assert 'supportTab.location.replace(`/support-access#${fragment.toString()}`)' in admin
    assert 't("adminViewAsUser")' in admin
