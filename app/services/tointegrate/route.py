
from typing import Optional
from fastapi import APIRouter, Depends, File, Query, UploadFile, status, HTTPException
from fastapi.security import HTTPBearer

from sqlalchemy import String, func, or_
from sqlalchemy.orm import Session
from config.database import get_db
import numpy as np
from .services import master_func
from schemas import VendorBase, InvoiceHeader, InvoiceDetails
from routes.models import VendorsModel, InvoiceHeaderModel, InvoiceDetailsModel

import json

endpoint_name = "Invoice"

router = APIRouter(prefix="/invoice", tags=[endpoint_name])
oauth_2_schemes = HTTPBearer()


@router.post("/")
async def handle_process_invoice_fun(
    file: UploadFile = File(...),
    db_pg: Session = Depends(get_db)
):
    # Validate file type by content type
    if file.content_type != "image/png":
        raise HTTPException(status_code=400, detail="Only PNG files are allowed.")
    
    # Read file into numpy array
    file_bytes = await file.read()
    np_arr = np.frombuffer(file_bytes, np.uint8)

    invoice_data = master_func(np_arr=np_arr)

    print(invoice_data)
    print("----------------------------")
    print(invoice_data['company_address'])
    print("----------------------------")

    vendor = VendorsModel(
        vend_address=invoice_data.get('company_address',''),
        vend_name=invoice_data.get('company_name',''),
        vend_company_email=invoice_data.get('company_email', ''),
        vend_phone=invoice_data.get('company_phone',''),
        vend_registration_number=invoice_data.get('company_registration_number', ''),
        vend_vat_number=invoice_data.get('company_vat_number', '')
    )

    vendor_result = db_pg.query(VendorsModel).filter(
        or_(
            # VendorsModel.vend_address.ilike(f"%{vendor.vend_address}%"),
            # VendorsModel.vend_name.ilike(f"%{vendor.vend_name}%"),
            VendorsModel.vend_company_email.ilike(f"%{vendor.vend_company_email}%"),
            VendorsModel.vend_phone.ilike(f"%{vendor.vend_phone}%"),
            VendorsModel.vend_registration_number.ilike(f"%{vendor.vend_registration_number}%"),
            VendorsModel.vend_vat_number.ilike(f"%{vendor.vend_vat_number}%"),
        )
    ).first()  # Execute the query
    

    vendor_id = 0
    # query if vendor exist, else create vendor
    if vendor_result:
        vendor_id = vendor_result.vend_id
    else:
        db_pg.add(vendor)
        db_pg.commit()
        db_pg.refresh(vendor)
        vendor_id = vendor.vend_id


    invoice_header = InvoiceHeaderModel(
        invh_vend_id            = vendor_id,
        invh_number             = invoice_data.get('invoice_number',''),
        invh_date               = invoice_data.get('invoice_date',''),
        invh_currency           = invoice_data.get('currency',''),
        invh_gross_total       = invoice_data.get('totals', {}).get('gross_total', 0),
        invh_vat_amount        = invoice_data.get('totals', {}).get('vat_amount', 0),
        invh_net_after_vat     = invoice_data.get('totals', {}).get('net_after_vat', 0),
        invh_calculation_check = invoice_data.get('totals', {}).get('calculation_check', False)
    )

    invoice_header_result = db_pg.query(InvoiceHeaderModel).filter(InvoiceHeaderModel.invh_vend_id == vendor_id, InvoiceHeaderModel.invh_number == invoice_data['invoice_number']).first()

    if invoice_header_result:
        raise HTTPException(status_code=400, detail="Invoice already processed")
    else:
        
        # Insert Invoice Header
        db_pg.add(invoice_header)
        db_pg.commit()
        db_pg.refresh(invoice_header)
        invoice_header_id = invoice_header.invh_id

        for item in invoice_data['items']:

            invoice_detail = InvoiceDetailsModel(
                invd_invh_id        = invoice_header_id,
                invd_quantity       = item['quantity'],
                invd_unit_price     = item['unit_price'],
                invd_discount       = item['discount'],

                invd_net_amount     = item['net_amount'],
                invd_vat_rate       = item['vat_rate'],
                invd_vat_amount     = item['vat_amount'],
                invd_description    = item['description'],
                invd_total_price    = item['total'],

                invd_calculation_check = item['calculation_check']
            )

            db_pg.add(invoice_detail)
            db_pg.commit()
            db_pg.refresh(invoice_detail)

    return invoice_data



# @router.patch("/{id}")
# async def handle_update_fun(
#     id: int,
#     payload: BuoyCreate,
#     db_pg: Session = Depends(get_db)):

#     update_fun(id=id, payload=payload, db_pg=db_pg)

#     return {"message": f"{endpoint_name} updated successfully"}

# @router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
# async def handle_delete_fun(id: int, db: Session = Depends(get_db)):
#     result = query_by_id_fun(id=id, db_pg=db)

#     if result is None:
#         raise HTTPException(status_code=404, detail=f"{endpoint_name} not found")

#     db.delete(result)
#     db.commit()