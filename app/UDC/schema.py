"""
Schema definitions for UDC (User Defined Codes)
"""

from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID


# UDC creation request
class UDCCreateRequest(BaseModel):
    udc_country: str = Field(
        ...,
        min_length=2,
        description="Country name entry"
    )
    udc_city: str = Field(
        ...,
        min_length=2,
        description="City name entry"
    )
    udc_state: str = Field(
        ...,
        min_length=2,
        description="State or region entry"
    )



# UDC update request
class UDCUpdateRequest(BaseModel):
    udc_country: Optional[str] = Field(
        None,
        description="Updated country name (optional)"
    )
    udc_city: Optional[str] = Field(
        None,
        description="Updated city name (optional)"
    )
    udc_state: Optional[str] = Field(
        None,
        description="Updated state or region (optional)"
    )


# UDC response
class UDCResponse(BaseModel):
    udc_id: UUID = Field(
        ...,
        description="Unique identifier for the user-defined location record"
    )
    udc_country: str = Field(
        ...,
        description="Country name as stored in the system"
    )
    udc_city: str = Field(
        ...,
        description="City name as stored in the system"
    )
    udc_state: str = Field(
        ...,
        description="State or region name as stored in the system"
    )

    class Config:
        from_attributes = True
