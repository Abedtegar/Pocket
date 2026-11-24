"""Endpoint REST (plan.md 8.1) + endpoint uji dan rekam dataset."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import deep_merge
from ..engine.event_engine import SEVERITY, SOUNDS
from .auth import COOKIE, MAX_AGE, require_auth
from .status import build_status

public = APIRouter()
router = APIRouter(dependencies=[Depends(require_auth)])


def ctx_of(request: Request):
    return request.app.state.ctx


# ---------------- auth ----------------
class LoginBody(BaseModel):
    password: str


@public.post("/api/login")
async def login(body: LoginBody, request: Request, response: Response):
    auth = request.app.state.auth
    if not auth.check_password(body.password):
        await asyncio.sleep(1.0)  # perlambat tebak password
        raise HTTPException(401, "password salah")
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, auth.make_token(), max_age=MAX_AGE, httponly=True, samesite="lax", secure=secure)
    return {"ok": True}


@public.post("/api/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@public.get("/api/auth")
async def auth_info(request: Request):
    auth = request.app.state.auth
    return {"auth_required": auth.enabled, "logged_in": auth.valid_token(request.cookies.get(COOKIE))}


# ---------------- status & riwayat ----------------
@router.get("/api/status")
async def status(request: Request):
    return build_status(ctx_of(request))


@router.get("/api/power")
async def power(request: Request, minutes: float = Query(60, gt=0, le=60 * 24 * 7)):
    return await ctx_of(request).db.power_since(minutes)


@router.get("/api/hr")
async def hr(request: Request, minutes: float = Query(60, gt=0, le=60 * 24 * 7)):
    return await ctx_of(request).db.hr_since(minutes)


@router.get("/api/track")
async def track(request: Request, minutes: float = Query(60, gt=0, le=60 * 24 * 7)):
    return await ctx_of(request).db.track_since(minutes)


@router.get("/api/events")
async def events(request: Request, limit: int = Query(100, gt=0, le=1000), type: str | None = None,
                 offset: int = Query(0, ge=0)):
    return await ctx_of(request).db.list_events(limit, type or None, offset)


@router.post("/api/events/ack_all")
async def ack_all(request: Request):
    return {"acknowledged": await ctx_of(request).engine.ack_all()}


@router.post("/api/events/{ev_id}/ack")
async def ack(ev_id: str, request: Request):
    if not await ctx_of(request).engine.ack(ev_id):
        raise HTTPException(404, "event tidak ditemukan")
    return {"ok": True}


# ---------------- zona ----------------
class ZoneBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_m: float = Field(gt=0, le=50000)
    active: bool = True


class ZonePatch(BaseModel):
    name: str | None = None
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    radius_m: float | None = Field(None, gt=0, le=50000)
    active: bool | None = None


@router.get("/api/zones")
async def zones(request: Request):
    return await ctx_of(request).db.list_zones()


@router.post("/api/zones")
async def add_zone(body: ZoneBody, request: Request):
    ctx = ctx_of(request)
    zid = await ctx.db.add_zone(body.name, body.lat, body.lon, body.radius_m, body.active)
    await ctx.rules.reload_zones()
    return {"id": zid}


@router.put("/api/zones/{zone_id}")
async def update_zone(zone_id: int, body: ZonePatch, request: Request):
    ctx = ctx_of(request)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not await ctx.db.update_zone(zone_id, fields):
        raise HTTPException(404, "zona tidak ditemukan")
    await ctx.rules.reload_zones()
    return {"ok": True}


@router.delete("/api/zones/{zone_id}")
async def delete_zone(zone_id: int, request: Request):
    ctx = ctx_of(request)
    if not await ctx.db.delete_zone(zone_id):
        raise HTTPException(404, "zona tidak ditemukan")
    await ctx.rules.reload_zones()
    return {"ok": True}


# ---------------- pengaturan ----------------
@router.get("/api/settings")
async def get_settings(request: Request):
    return ctx_of(request).cfg.editable_view()


@router.put("/api/settings")
async def put_settings(request: Request, body: dict = Body(...)):
    ctx = ctx_of(request)
    clean = ctx.cfg.validate_overrides(body)
    if not clean:
        raise HTTPException(400, "tidak ada pengaturan valid")
    ctx.cfg.merge(clean)
    overrides = await ctx.db.get_setting("config_overrides", {}) or {}
    await ctx.db.set_setting("config_overrides", deep_merge(overrides, clean))
    return ctx.cfg.editable_view()


# ---------------- video ----------------
async def _mjpeg(request: Request, view: str):
    ctx = ctx_of(request)
    interval = 1.0 / max(0.5, float(ctx.cfg.get("api.stream_max_fps", 5)))

    async def gen():
        last = -1
        while not await request.is_disconnected():
            jpeg, seq = ctx.pipeline.latest(view)
            if jpeg and seq != last:
                last = seq
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                       + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
            await asyncio.sleep(interval)

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store"})


@router.get("/api/stream")
async def stream(request: Request, view: str = Query("processed", pattern="^(raw|processed)$")):
    return await _mjpeg(request, view)


@router.get("/api/camera/snapshot")
async def camera_snapshot(request: Request, view: str = Query("processed", pattern="^(raw|processed)$")):
    jpeg, _ = ctx_of(request).pipeline.latest(view)
    if not jpeg:
        raise HTTPException(503, "belum ada frame")
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ---------------- kamera ----------------
@router.get("/api/camera/sensor")
async def get_sensor(request: Request):
    ctx = ctx_of(request)
    return {"sensor": ctx.camera.get_sensor(), "esp_state": ctx.state.value("camera", "esp_state")}


@router.put("/api/camera/sensor")
async def put_sensor(request: Request, body: dict = Body(...)):
    res = await ctx_of(request).camera.set_sensor(body)
    if res["errors"] and not res["applied"]:
        raise HTTPException(400, res["errors"])
    return res


@router.get("/api/camera/preprocess")
async def get_preprocess(request: Request):
    return ctx_of(request).camera.get_preprocess()


@router.put("/api/camera/preprocess")
async def put_preprocess(request: Request, body: dict = Body(...)):
    try:
        return await ctx_of(request).camera.set_preprocess(body)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, str(e))


class PresetBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)


@router.get("/api/camera/presets")
async def presets(request: Request):
    return await ctx_of(request).camera.list_presets()


@router.post("/api/camera/presets")
async def save_preset(body: PresetBody, request: Request):
    try:
        return await ctx_of(request).camera.save_preset(body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/camera/presets/{name}")
async def delete_preset(name: str, request: Request):
    try:
        if not await ctx_of(request).camera.delete_preset(name):
            raise HTTPException(404, "preset tidak ditemukan")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/api/camera/presets/{name}/apply")
async def apply_preset(name: str, request: Request):
    try:
        return await ctx_of(request).camera.apply_preset(name)
    except KeyError:
        raise HTTPException(404, "preset tidak ditemukan")


@router.post("/api/camera/reset")
async def reset_camera(request: Request):
    return await ctx_of(request).camera.reset_default()


# ---------------- snapshot file ----------------
@router.get("/snapshots/{path:path}")
async def snapshot_file(path: str, request: Request):
    p = ctx_of(request).snapshots.resolve(path)
    if p is None:
        raise HTTPException(404, "snapshot tidak ditemukan")
    return FileResponse(p, media_type="image/jpeg")


# ---------------- uji ----------------
@router.post("/api/test/speaker")
async def test_speaker(request: Request, body: dict = Body(default={})):
    ctx = ctx_of(request)
    sound = body.get("sound") or "test.wav"
    if sound not in set(SOUNDS.values()) | {"test.wav"}:
        raise HTTPException(400, "suara tidak dikenal")
    ctx.speaker.play(sound, priority=1)
    return {"ok": True, "sound": sound}


@router.post("/api/test/telegram")
async def test_telegram(request: Request):
    ctx = ctx_of(request)
    if not ctx.telegram.enabled:
        raise HTTPException(400, "Telegram belum dikonfigurasi (.env)")
    try:
        await ctx.telegram.send_text(f"✅ [UJI] Pesan uji Guardian\nWaktu: {ctx.cfg.now():%d-%m-%Y %H:%M:%S}")
    except Exception as e:
        raise HTTPException(502, f"gagal: {e}")
    return {"ok": True}


@router.post("/api/test/led")
async def test_led(request: Request):
    ctx = ctx_of(request)
    ctx.led.test_cycle()
    return {"ok": True, "hardware": ctx.led.out is not None}


@router.post("/api/test/panic")
async def test_panic(request: Request):
    ev = await ctx_of(request).engine.emit("panic", {"source": "web_test"}, force=True)
    return ev


@router.post("/api/test/event")
async def test_event(request: Request, body: dict = Body(...)):
    typ = body.get("type")
    if typ not in SEVERITY:
        raise HTTPException(400, f"type harus salah satu {list(SEVERITY)}")
    ev = await ctx_of(request).engine.emit(typ, {"test": True, **(body.get("data") or {})}, force=True)
    return ev


# ---------------- rekam dataset ----------------
@router.get("/api/record/status")
async def record_status(request: Request):
    return ctx_of(request).recorder.status()


@router.post("/api/record/start")
async def record_start(request: Request, body: dict = Body(default={})):
    ctx = ctx_of(request)
    info = {k: str(body.get(k, ""))[:200] for k in
            ("nama", "lokasi", "cahaya", "jarak", "gerak", "benda", "relawan_id", "catatan")}
    gps = ctx.state.get("gps")
    extra = {
        "preset_name": ctx.camera.active_preset,
        "sensor": ctx.camera.get_sensor(),
        "preprocess": ctx.camera.get_preprocess(),
        "gps_start": {"lat": gps.get("lat"), "lon": gps.get("lon"), "fix": gps.get("fix")},
        "detector_paused": bool(body.get("pause_detector", True)),
    }
    try:
        res = ctx.recorder.start(info, extra)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    ctx.reader.add_frame_callback(ctx.recorder.on_frame)
    if extra["detector_paused"]:
        ctx.pipeline.pause(True)
    return res


@router.post("/api/record/stop")
async def record_stop(request: Request):
    ctx = ctx_of(request)
    ctx.reader.remove_frame_callback(ctx.recorder.on_frame)
    gps = ctx.state.get("gps")
    try:
        res = ctx.recorder.stop({"gps_end": {"lat": gps.get("lat"), "lon": gps.get("lon"), "fix": gps.get("fix")}})
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    finally:
        ctx.pipeline.pause(False)
    return res
