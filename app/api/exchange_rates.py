"""
Exchange Rates API
Endpoints for managing currency exchange rates.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, List
from decimal import Decimal
from datetime import datetime

from app.database import get_db
from app.models import User, Company, ExchangeRate, ExchangeRateLog
from app.utils.security import verify_token
from app.services.exchange_rate import ExchangeRateService
from app.api.companies import SUPPORTED_CURRENCIES

router = APIRouter()
security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    """Get the current authenticated user"""
    token = credentials.credentials
    email = verify_token(token)

    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return user


def require_admin(user: User = Depends(get_current_user)):
    """Require admin role"""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


class ManualRateRequest(BaseModel):
    from_currency: str
    to_currency: str
    rate: float


class ConvertRequest(BaseModel):
    amount: float
    from_currency: str
    to_currency: str


@router.get("/exchange-rates")
async def get_exchange_rates(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current exchange rates for company's primary currency"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    company = db.query(Company).filter(Company.id == user.company_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    base_currency = company.primary_currency or "USD"

    # Get API rates
    api_rates = await ExchangeRateService.fetch_rates_from_api(base_currency)

    # Get manual overrides
    manual_rates = ExchangeRateService.get_manual_rates(db, company.id)
    manual_rate_map = {
        f"{r.from_currency}_{r.to_currency}": {
            "rate": float(r.rate),
            "effective_date": r.effective_date.isoformat() if r.effective_date else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None
        }
        for r in manual_rates
    }

    # Build response with all supported currencies
    rates = []
    for currency in SUPPORTED_CURRENCIES:
        code = currency["code"]
        if code == base_currency:
            continue

        # Check for manual override first
        key = f"{base_currency}_{code}"
        if key in manual_rate_map:
            rates.append({
                "from_currency": base_currency,
                "to_currency": code,
                "currency_name": currency["name"],
                "currency_symbol": currency["symbol"],
                "rate": manual_rate_map[key]["rate"],
                "source": "manual",
                "effective_date": manual_rate_map[key]["effective_date"],
                "updated_at": manual_rate_map[key]["updated_at"]
            })
        elif api_rates and code in api_rates:
            rates.append({
                "from_currency": base_currency,
                "to_currency": code,
                "currency_name": currency["name"],
                "currency_symbol": currency["symbol"],
                "rate": float(api_rates[code]),
                "source": "api",
                "effective_date": datetime.utcnow().date().isoformat(),
                "updated_at": None
            })
        else:
            rates.append({
                "from_currency": base_currency,
                "to_currency": code,
                "currency_name": currency["name"],
                "currency_symbol": currency["symbol"],
                "rate": None,
                "source": "unavailable",
                "effective_date": None,
                "updated_at": None
            })

    return {
        "base_currency": base_currency,
        "rates": rates,
        "fetched_at": datetime.utcnow().isoformat()
    }


@router.get("/exchange-rates/convert")
async def convert_amount(
    amount: float = Query(..., description="Amount to convert"),
    from_currency: str = Query(..., description="Source currency code"),
    to_currency: str = Query(..., description="Target currency code"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Convert an amount between currencies"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    result = await ExchangeRateService.convert_amount(
        db,
        user.company_id,
        Decimal(str(amount)),
        from_currency,
        to_currency
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to convert from {from_currency} to {to_currency}"
        )

    # Get rate used
    rate = await ExchangeRateService.get_rate(db, user.company_id, from_currency, to_currency)

    return {
        "original_amount": amount,
        "from_currency": from_currency.upper(),
        "to_currency": to_currency.upper(),
        "converted_amount": float(result),
        "rate": float(rate) if rate else None
    }


@router.post("/exchange-rates/manual")
async def set_manual_rate(
    data: ManualRateRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Set a manual exchange rate override (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    if data.rate <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rate must be greater than 0"
        )

    # Validate currencies
    valid_codes = [c["code"] for c in SUPPORTED_CURRENCIES]
    if data.from_currency.upper() not in valid_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid from_currency: {data.from_currency}"
        )
    if data.to_currency.upper() not in valid_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid to_currency: {data.to_currency}"
        )

    rate = ExchangeRateService.set_manual_rate(
        db,
        user.company_id,
        data.from_currency,
        data.to_currency,
        Decimal(str(data.rate)),
        user.email
    )

    return {
        "success": True,
        "message": f"Manual rate set: 1 {rate.from_currency} = {rate.rate} {rate.to_currency}",
        "rate": {
            "from_currency": rate.from_currency,
            "to_currency": rate.to_currency,
            "rate": float(rate.rate),
            "source": rate.source,
            "effective_date": rate.effective_date.isoformat() if rate.effective_date else None
        }
    }


@router.delete("/exchange-rates/manual")
async def delete_manual_rate(
    from_currency: str = Query(...),
    to_currency: str = Query(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Delete a manual rate override (reverts to API rate)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    deleted = ExchangeRateService.delete_manual_rate(
        db,
        user.company_id,
        from_currency,
        to_currency
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No manual rate found for {from_currency}/{to_currency}"
        )

    return {
        "success": True,
        "message": f"Manual rate deleted for {from_currency}/{to_currency}. Will use API rate."
    }


@router.post("/exchange-rates/refresh")
async def refresh_rates(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Force refresh exchange rates from API (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    company = db.query(Company).filter(Company.id == user.company_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    base_currency = company.primary_currency or "USD"
    result = await ExchangeRateService.refresh_rates(db, company.id, base_currency)

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result["message"]
        )

    return result


@router.get("/exchange-rates/history")
async def get_rate_history(
    from_currency: Optional[str] = None,
    to_currency: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get exchange rate history/logs"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    logs = ExchangeRateService.get_rate_history(
        db,
        user.company_id,
        from_currency,
        to_currency,
        limit
    )

    return {
        "history": [
            {
                "id": log.id,
                "from_currency": log.from_currency,
                "to_currency": log.to_currency,
                "rate": float(log.rate),
                "source": log.source,
                "api_provider": log.api_provider,
                "fetched_at": log.fetched_at.isoformat() if log.fetched_at else None
            }
            for log in logs
        ],
        "count": len(logs)
    }
