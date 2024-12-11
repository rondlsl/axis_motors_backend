from fastapi import FastAPI

from app.cars_api.router import Vehicle_Router

app = FastAPI()

app.include_router(Vehicle_Router)


@app.get("/")
def root():
    return dict(message="че надо тут?")
