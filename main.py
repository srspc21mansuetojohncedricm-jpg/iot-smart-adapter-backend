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
