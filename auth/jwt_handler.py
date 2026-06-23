import os
from datetime import datetime, timedelta
from jose import jwt
from dotenv import load_dotenv

load_dotenv()

SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-prod")
ALGO = "HS256"
EXPIRE_HOURS = 24


def create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.utcnow() + timedelta(hours=EXPIRE_HOURS)
    }
    return jwt.encode(payload, SECRET, algorithm=ALGO)


def decode_token(token: str) -> int:
    payload = jwt.decode(token, SECRET, algorithms=[ALGO])
    return int(payload["sub"])