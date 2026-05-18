import time
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

import models
import schemas
import auth
from database import engine, get_db

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="IoT Smart Adapter API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth helper ────────────────────────────────────────────────────

def current_user(authorization: str = Header(default=None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = auth.decode_token(authorization.split(" ", 1)[1])
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ── Health ─────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": int(time.time())}


# ── Auth ───────────────────────────────────────────────────────────

@app.post("/api/register")
def register(req: schemas.RegisterRequest, db: Session = Depends(get_db)):
    count = db.query(func.count(models.User.id)).scalar()
    if count >= 4:
        raise HTTPException(status_code=400, detail="MAX_USERS")
    if db.query(models.User).filter(models.User.username == req.username).first():
        raise HTTPException(status_code=400, detail="EXISTS")
    user = models.User(
        username=req.username,
        password_hash=auth.hash_password(req.password),
        created_at=int(time.time()),
    )
    db.add(user)
    db.commit()
    return {"message": "OK"}


@app.post("/api/login", response_model=schemas.LoginResponse)
def login(req: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == req.username).first()
    if not user or not auth.verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
    return schemas.LoginResponse(token=auth.create_token(user.username), username=user.username)


# ── Device pairing ─────────────────────────────────────────────────

@app.post("/api/pair")
def pair_device(
    req: schemas.PairRequest,
    me: models.User = Depends(current_user),
    db: Session = Depends(get_db),
):
    db.query(models.DevicePairing).filter(models.DevicePairing.username == me.username).delete()
    db.add(models.DevicePairing(username=me.username, room_id=req.room_id, paired_at=int(time.time())))
    db.commit()
    return {"message": "OK", "room_id": req.room_id}


@app.get("/api/paired-device")
def paired_device(me: models.User = Depends(current_user), db: Session = Depends(get_db)):
    pairing = db.query(models.DevicePairing).filter(models.DevicePairing.username == me.username).first()
    if not pairing:
        return {"paired": False, "room_id": None}
    return {"paired": True, "room_id": pairing.room_id}


# ── Device → Server (no auth — device uses room_id as identity) ────

@app.post("/api/energy")
def receive_energy(data: schemas.EnergyPost, db: Session = Depends(get_db)):
    reading = models.EnergyReading(**data.dict())
    db.add(reading)
    db.commit()
    return {"status": "ok"}


@app.post("/api/sessions")
def receive_session(data: schemas.SessionPost, db: Session = Depends(get_db)):
    session = models.Session(**data.dict())
    db.add(session)
    db.commit()
    return {"status": "ok"}


# ── App → Server ───────────────────────────────────────────────────

@app.get("/api/live/{room_id}")
def live_reading(room_id: str, db: Session = Depends(get_db)):
    r = (
        db.query(models.EnergyReading)
        .filter(models.EnergyReading.room_id == room_id)
        .order_by(desc(models.EnergyReading.timestamp))
        .first()
    )
    if not r:
        return {"room_id": room_id, "timestamp": 0, "kwh": 0.0, "watts": 0.0, "volts": 0.0, "amps": 0.0}
    return {
        "room_id": r.room_id,
        "timestamp": r.timestamp,
        "kwh": r.kwh,
        "watts": r.watts,
        "volts": r.volts,
        "amps": r.amps,
        "user_id": r.user_id,
    }


@app.get("/api/consumption")
def consumption(me: models.User = Depends(current_user), db: Session = Depends(get_db)):
    users = db.query(models.User).order_by(models.User.created_at).all()
    result = {}
    for u in users:
        total = db.query(func.sum(models.Session.kwh)).filter(models.Session.user_id == u.username).scalar() or 0.0
        result[u.username] = round(total, 4)
    return result


@app.get("/api/users")
def list_users(me: models.User = Depends(current_user), db: Session = Depends(get_db)):
    users = db.query(models.User).order_by(models.User.created_at).all()
    return [u.username for u in users]


@app.delete("/api/admin/delete-user/{username}")
def delete_user(username: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.query(models.DevicePairing).filter(models.DevicePairing.username == username).delete()
    db.query(models.Session).filter(models.Session.user_id == username).delete()
    db.query(models.EnergyReading).filter(models.EnergyReading.user_id == username).delete()
    db.delete(user)
    db.commit()
    return {"message": f"User '{username}' deleted"}


@app.post("/api/admin/reset")
def reset_data(req: schemas.AdminRequest, db: Session = Depends(get_db)):
    if req.password != "SmartAdapter123":
        raise HTTPException(status_code=403, detail="WRONG_PASSWORD")

    now = int(time.time())
    six_months_ago = now - (6 * 30 * 24 * 3600)
    cycle_id = str(now)

    # Archive current sessions per user into billing history
    users = db.query(models.User).all()
    for u in users:
        sessions = db.query(models.Session).filter(models.Session.user_id == u.username).all()
        if sessions:
            db.add(models.BillingHistory(
                cycle_id=cycle_id,
                archived_at=now,
                user_id=u.username,
                kwh=round(sum(s.kwh for s in sessions), 4),
                cost_php=round(sum(s.cost_php for s in sessions), 2),
                session_count=len(sessions),
                period_start=min(s.start_time for s in sessions),
                period_end=max(s.end_time for s in sessions),
            ))

    # Auto-purge history older than 6 months
    db.query(models.BillingHistory).filter(
        models.BillingHistory.archived_at < six_months_ago
    ).delete()

    # Clear current cycle data
    db.query(models.Session).delete()
    db.query(models.EnergyReading).delete()
    db.query(models.DevicePairing).delete()
    if req.clear_users:
        db.query(models.User).delete()

    db.commit()
    return {"message": "Reset complete", "cycle_id": cycle_id}


@app.get("/api/history")
def get_history(me: models.User = Depends(current_user), db: Session = Depends(get_db)):
    six_months_ago = int(time.time()) - (6 * 30 * 24 * 3600)
    records = (
        db.query(models.BillingHistory)
        .filter(models.BillingHistory.archived_at >= six_months_ago)
        .order_by(desc(models.BillingHistory.archived_at))
        .all()
    )
    cycles: dict = {}
    for r in records:
        if r.cycle_id not in cycles:
            cycles[r.cycle_id] = {
                "cycle_id": r.cycle_id,
                "archived_at": r.archived_at,
                "users": [],
            }
        cycles[r.cycle_id]["users"].append({
            "user_id": r.user_id,
            "kwh": r.kwh,
            "cost_php": r.cost_php,
            "session_count": r.session_count,
            "period_start": r.period_start,
            "period_end": r.period_end,
        })
    return list(cycles.values())


@app.delete("/api/admin/clear-history")
def clear_history(req: schemas.AdminRequest, db: Session = Depends(get_db)):
    if req.password != "SmartAdapter123":
        raise HTTPException(status_code=403, detail="WRONG_PASSWORD")
    db.query(models.BillingHistory).delete()
    db.commit()
    return {"message": "History cleared"}


@app.get("/api/sessions/history")
def session_history(me: models.User = Depends(current_user), db: Session = Depends(get_db)):
    sessions = (
        db.query(models.Session)
        .order_by(desc(models.Session.end_time))
        .limit(50)
        .all()
    )
    return [
        {
            "user_id": s.user_id,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "duration_s": s.duration_s,
            "kwh": s.kwh,
            "cost_php": s.cost_php,
        }
        for s in sessions
    ]
