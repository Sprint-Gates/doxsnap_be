from fastapi import FastAPI

from . import models
from .login import login_route
from .signup import signup_route
from .company import company_route
from .branch import branch_route
from .vendor import vendor_route
from .UDC import udc_route
from .user_branch_assign import uba_route
from .routes import email_ver_route
from .database import engine

app = FastAPI()

models.Base.metadata.create_all(engine)

app.include_router(login_route.router)

app.include_router(signup_route.router)

app.include_router(email_ver_route.router)

app.include_router(company_route.router)

app.include_router(branch_route.router)

app.include_router(vendor_route.router)

app.include_router(udc_route.router)

app.include_router(uba_route.router)