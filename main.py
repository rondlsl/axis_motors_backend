from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI

from app.auth.router import Auth_router
from app.gps_api.router import Vehicle_Router
from app.rent.router import RentRouter

app = FastAPI()
origins = [
    "*"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(Auth_router)  # регистрация (фото удоста и тд тоже тут)
app.include_router(Vehicle_Router)
app.include_router(RentRouter)


@app.get("/")
def root():
    return dict(message="че надо тут?")
