from fastapi import FastAPI
from sqlalchemy.orm import Session
from db import SessionLocal
from models import User

app = FastAPI()

@app.get("/")
def root():
    return {"message": "hello"}

@app.post("/users/{name}")
def create_user(name: str):
    db: Session = SessionLocal()
    user = User(name=name)
    db.add(user)
    db.commit()
    return {"created": name}