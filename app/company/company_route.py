from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.company.services import signup_company_admin
from app.company.schema import SignupCompanyRequest, SignupCompanyResponse

router = APIRouter(
    prefix="/api",
    tags=["Company"]
)


@router.post(
    "/signup",
    response_model=SignupCompanyResponse,
    status_code=status.HTTP_201_CREATED
)
def signup_company(
    request_data: SignupCompanyRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    ip_address = request.client.host
    result = signup_company_admin(db=db, data=request_data, ip_address=ip_address)
    return SignupCompanyResponse(**result)
