from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI

from app.auth.router import Auth_router
from app.gps_api.router import Vehicle_Router

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

app.include_router(Auth_router)
app.include_router(Vehicle_Router)


@app.get("/")
def root():
    return dict(message="че надо тут?")
