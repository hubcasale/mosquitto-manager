"""FastAPI application: JSON API + static single-page UI."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, models
from .auth import (COOKIE_NAME, CSRF_HEADER, CSRF_VALUE, LoginThrottle, check_password,
                   make_token, verify_token)
from .broker import Broker, BrokerUnavailable, DynsecError, DynsecTimeout
from .config import Settings
from .ha import HaPublisher
from .netmap import HostNames, build_map
from .merge import merge_clients, normalize_client, session_dict  # noqa: F401  (re-exported)
from .tracker import Tracker, load_state, save_state

log = logging.getLogger("mosquitto_manager")
STATIC_DIR = Path(__file__).parent / "static"

ACL_PRESETS = {
    "readwrite": ["publishClientSend", "publishClientReceive", "subscribePattern",
                  "unsubscribePattern"],
    "read": ["publishClientReceive", "subscribePattern", "unsubscribePattern"],
    "write": ["publishClientSend"],
}


# --------------------------------------------------------------------- helpers
async def _manager_roles(broker: Broker, settings: Settings) -> set[str]:
    data = await broker.dynsec("getClient", username=settings.mqtt_username)
    return {r["rolename"] for r in data.get("client", {}).get("roles", [])}


# ------------------------------------------------------------------------ app
def create_app(settings: Settings, broker: Broker | None = None,
               tracker: Tracker | None = None) -> FastAPI:
    tracker = tracker or Tracker()
    broker = broker or Broker(settings, tracker)
    throttle = LoginThrottle()
    state_file = settings.data_dir / "state.json"
    ha = HaPublisher(settings, broker, tracker)
    host_names = HostNames(settings.data_dir / "hosts.json")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        load_state(tracker, state_file)
        broker.start(asyncio.get_running_loop())
        ha.start(asyncio.get_running_loop())

        async def background() -> None:
            ticks = 0
            while True:
                await asyncio.sleep(15)
                ticks += 1
                broker.sample_history()
                if ticks % 4 == 0:
                    try:
                        settings.data_dir.mkdir(parents=True, exist_ok=True)
                        save_state(tracker, state_file)
                    except OSError as exc:
                        log.warning("Cannot save state: %s", exc)

        task = asyncio.create_task(background())
        try:
            yield
        finally:
            task.cancel()
            await ha.stop()
            broker.stop()
            try:
                settings.data_dir.mkdir(parents=True, exist_ok=True)
                save_state(tracker, state_file)
            except OSError:
                pass

    app = FastAPI(title="Mosquitto Manager", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    # ---- errors
    @app.exception_handler(DynsecError)
    async def _dynsec_error(_r: Request, exc: DynsecError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(DynsecTimeout)
    async def _dynsec_timeout(_r: Request, exc: DynsecTimeout):
        return JSONResponse({"detail": str(exc)}, status_code=504)

    @app.exception_handler(BrokerUnavailable)
    async def _unavailable(_r: Request, exc: BrokerUnavailable):
        return JSONResponse({"detail": f"Broker unavailable: {exc}"}, status_code=503)

    # ---- security headers
    @app.middleware("http")
    async def headers(request: Request, call_next: Callable):
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; "
            f"frame-ancestors {settings.frame_ancestors}")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response

    # ---- auth dependencies
    def authed(request: Request) -> bool:
        return settings.auth_disabled or verify_token(
            settings.secret_key, request.cookies.get(COOKIE_NAME))

    def require_auth(request: Request) -> None:
        if not authed(request):
            raise HTTPException(status_code=401, detail="Not authenticated")
        if request.method not in ("GET", "HEAD", "OPTIONS") and \
                request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            raise HTTPException(status_code=403, detail="Missing CSRF header")

    public = APIRouter(prefix="/api")
    api = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])

    # ------------------------------------------------------------ public routes
    @public.get("/health")
    async def health():
        return {"status": "ok", "version": __version__}

    @public.get("/session")
    async def session(request: Request):
        return {"authenticated": authed(request), "auth_required": not settings.auth_disabled,
                "version": __version__}

    @public.post("/login")
    async def login(body: models.Login, request: Request, response: Response):
        if settings.auth_disabled:
            return {"ok": True}
        who = request.client.host if request.client else "unknown"
        wait = throttle.retry_after(who)
        if wait:
            raise HTTPException(status_code=429, detail=f"Too many attempts, retry in {wait}s",
                                headers={"Retry-After": str(wait)})
        if not check_password(settings.ui_password, body.password):
            throttle.record_failure(who)
            raise HTTPException(status_code=401, detail="Wrong password")
        throttle.reset(who)
        response.set_cookie(
            COOKIE_NAME, make_token(settings.secret_key, settings.session_hours),
            max_age=settings.session_hours * 3600, httponly=True, samesite="strict",
            secure=settings.cookie_secure, path="/")
        return {"ok": True}

    @public.post("/logout")
    async def logout(response: Response):
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"ok": True}

    # ------------------------------------------------------------------ status
    @api.get("/status")
    async def status():
        if broker.connected and broker.dynsec_state != "ok":
            await broker.probe()
        now = time.time()
        return {
            "version": __version__,
            "manager_user": settings.mqtt_username,
            "broker": {
                "connected": broker.connected, "host": settings.mqtt_host,
                "port": settings.mqtt_port, "error": broker.last_error, **broker.snapshot(),
            },
            "dynsec": {"state": broker.dynsec_state, "error": broker.dynsec_error,
                       "connections_supported": broker.supports_connections},
            "log_feed": broker.log_feed_seen,
            "ha": ha.info(),
            "failed_logins_24h": tracker.count_events("auth_failed", now - 86400),
            "history": list(broker.history),
            "events": tracker.events(limit=8, kinds={"connect", "disconnect", "auth_failed",
                                                      "admin"}),
        }

    @api.get("/events")
    async def events(limit: int = Query(200, ge=1, le=1000), kind: str | None = None,
                     internal: bool = False, since_id: int = Query(0, ge=0)):
        kinds = {k for k in (kind or "").split(",") if k} or None
        return {"events": tracker.events(limit, kinds, internal, since_id),
                "log_feed": broker.log_feed_seen}

    # --------------------------------------------------------------------- map
    @api.get("/map")
    async def connection_map():
        raw = await broker.list_clients()
        merged = merge_clients(raw, tracker, settings.mqtt_username)
        data = build_map(merged, tracker, host_names.all())
        snap = broker.snapshot()
        data["broker"] = {"host": settings.mqtt_host, "port": settings.mqtt_port,
                          "connected": broker.connected, "version": snap.get("version"),
                          "clients_connected": snap.get("clients_connected")}
        return data

    @api.post("/hosts/alias")
    async def host_alias(body: models.HostAlias):
        host_names.set(body.address, body.name)
        return {"ok": True}

    # ----------------------------------------------------------------- clients
    @api.get("/clients")
    async def clients():
        raw = await broker.list_clients()
        return {"clients": merge_clients(raw, tracker, settings.mqtt_username),
                "connections_supported": broker.supports_connections}

    def _protect_user(username: str, action: str) -> None:
        if username == settings.mqtt_username:
            raise HTTPException(
                status_code=409,
                detail=f"'{username}' is the account this manager uses to talk to the broker: "
                       f"{action} would lock the manager out.")

    @api.post("/clients/create")
    async def client_create(body: models.ClientCreate):
        params: dict[str, Any] = {"username": body.username, "password": body.password}
        if body.textname:
            params["textname"] = body.textname
        if body.textdescription:
            params["textdescription"] = body.textdescription
        if body.clientid:
            params["clientid"] = body.clientid
        if body.roles:
            params["roles"] = [{"rolename": r} for r in body.roles]
        if body.groups:
            params["groups"] = [{"groupname": g} for g in body.groups]
        await broker.dynsec("createClient", **params)
        return {"ok": True}

    @api.post("/clients/update")
    async def client_update(body: models.ClientUpdate):
        if body.clientid is not None:
            _protect_user(body.username, "binding a client id")
        params: dict[str, Any] = {"username": body.username}
        for field in ("textname", "textdescription", "clientid"):
            value = getattr(body, field)
            if value is not None:
                params[field] = value
        await broker.dynsec("modifyClient", **params)
        return {"ok": True}

    @api.post("/clients/password")
    async def client_password(body: models.ClientPassword):
        _protect_user(body.username, "changing its password")
        await broker.dynsec("setClientPassword", username=body.username, password=body.password)
        return {"ok": True}

    @api.post("/clients/enable")
    async def client_enable(body: models.ClientEnable):
        if not body.enabled:
            _protect_user(body.username, "disabling it")
        await broker.dynsec("enableClient" if body.enabled else "disableClient",
                            username=body.username)
        return {"ok": True}

    @api.post("/clients/delete")
    async def client_delete(body: models.ClientRef):
        _protect_user(body.username, "deleting it")
        await broker.dynsec("deleteClient", username=body.username)
        return {"ok": True}

    @api.post("/clients/role-add")
    async def client_role_add(body: models.ClientRole):
        await broker.dynsec("addClientRole", username=body.username, rolename=body.rolename,
                            priority=body.priority)
        return {"ok": True}

    @api.post("/clients/role-remove")
    async def client_role_remove(body: models.ClientRole):
        _protect_user(body.username, "removing one of its roles")
        await broker.dynsec("removeClientRole", username=body.username, rolename=body.rolename)
        return {"ok": True}

    @api.post("/clients/group-add")
    async def client_group_add(body: models.ClientGroup):
        await broker.dynsec("addGroupClient", groupname=body.groupname, username=body.username,
                            priority=body.priority)
        return {"ok": True}

    @api.post("/clients/group-remove")
    async def client_group_remove(body: models.ClientGroup):
        _protect_user(body.username, "removing it from a group")
        await broker.dynsec("removeGroupClient", groupname=body.groupname,
                            username=body.username)
        return {"ok": True}

    # ------------------------------------------------------------------- roles
    @api.get("/roles")
    async def roles():
        data = await broker.dynsec("listRoles", verbose=True)
        return {"roles": data.get("roles", [])}

    @api.post("/roles/create")
    async def role_create(body: models.RoleCreate):
        params: dict[str, Any] = {"rolename": body.rolename}
        if body.textname:
            params["textname"] = body.textname
        if body.textdescription:
            params["textdescription"] = body.textdescription
        await broker.dynsec("createRole", **params)
        return {"ok": True}

    @api.post("/roles/delete")
    async def role_delete(body: models.RoleRef):
        if body.rolename in await _manager_roles(broker, settings):
            raise HTTPException(409, f"Role '{body.rolename}' is used by the manager's own "
                                     "account: deleting it would lock the manager out.")
        await broker.dynsec("deleteRole", rolename=body.rolename)
        return {"ok": True}

    @api.post("/roles/acl-add")
    async def role_acl_add(body: models.RoleAcl):
        if not body.acltype and not body.preset:
            raise HTTPException(422, "Either acltype or preset is required")
        types = [body.acltype] if body.acltype else ACL_PRESETS[body.preset]
        added = 0
        for acltype in types:
            try:
                await broker.dynsec("addRoleACL", rolename=body.rolename, acltype=acltype,
                                    topic=body.topic, priority=body.priority, allow=body.allow)
                added += 1
            except DynsecError as exc:
                # Presets overlap with rules that may already exist: that is fine.
                if body.preset and "already" in str(exc).lower():
                    continue
                raise
        return {"ok": True, "added": added}

    @api.post("/roles/acl-remove")
    async def role_acl_remove(body: models.RoleAclRemove):
        if body.rolename in await _manager_roles(broker, settings):
            raise HTTPException(409, f"Role '{body.rolename}' is used by the manager's own "
                                     "account: changing its rules could lock the manager out.")
        await broker.dynsec("removeRoleACL", rolename=body.rolename, acltype=body.acltype,
                            topic=body.topic)
        return {"ok": True}

    # ------------------------------------------------------------------ groups
    @api.get("/groups")
    async def groups():
        data = await broker.dynsec("listGroups", verbose=True)
        return {"groups": data.get("groups", [])}

    @api.post("/groups/create")
    async def group_create(body: models.GroupCreate):
        params: dict[str, Any] = {"groupname": body.groupname}
        if body.textname:
            params["textname"] = body.textname
        if body.textdescription:
            params["textdescription"] = body.textdescription
        await broker.dynsec("createGroup", **params)
        return {"ok": True}

    @api.post("/groups/delete")
    async def group_delete(body: models.GroupRef):
        data = await broker.dynsec("getGroup", groupname=body.groupname)
        members = {c.get("username") for c in data.get("group", {}).get("clients", [])}
        if settings.mqtt_username in members:
            raise HTTPException(409, "The manager's own account is a member of this group: "
                                     "deleting it could lock the manager out.")
        await broker.dynsec("deleteGroup", groupname=body.groupname)
        return {"ok": True}

    @api.post("/groups/role-add")
    async def group_role_add(body: models.GroupRole):
        await broker.dynsec("addGroupRole", groupname=body.groupname, rolename=body.rolename,
                            priority=body.priority)
        return {"ok": True}

    @api.post("/groups/role-remove")
    async def group_role_remove(body: models.GroupRole):
        await broker.dynsec("removeGroupRole", groupname=body.groupname,
                            rolename=body.rolename)
        return {"ok": True}

    # ------------------------------------------------------------ default ACLs
    @api.get("/default-acl")
    async def default_acl_get():
        data = await broker.dynsec("getDefaultACLAccess")
        return {"acls": {a["acltype"]: bool(a["allow"]) for a in data.get("acls", [])}}

    @api.post("/default-acl")
    async def default_acl_set(body: models.DefaultAcl):
        await broker.dynsec("setDefaultACLAccess", acls=[
            {"acltype": t, "allow": allow} for t, allow in body.acls.items()])
        return {"ok": True}

    # -------------------------------------------------------------- test login
    @api.post("/test-login")
    async def test_login(body: models.TestLogin):
        if not broker.connected:
            raise BrokerUnavailable(broker.last_error or "not connected")
        return await broker.test_login(body.username, body.password, body.clientid)

    app.include_router(public)
    app.include_router(api)
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
