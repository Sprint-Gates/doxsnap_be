from fastapi import FastAPI

from . import models
from .login import login_route
from .signup import signup_route
from .database import engine

app = FastAPI()

models.Base.metadata.create_all(engine)

app.include_router(login_route.router)

app.include_router(signup_route.router)