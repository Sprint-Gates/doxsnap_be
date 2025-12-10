from sqlalchemy import Boolean, Column, Float, Integer, String
from config.database import Base

class VendorsModel(Base):

    __tablename__ = "vendors"

    vend_id                     = Column(Integer, primary_key=True, index=True)
    vend_name                   = Column(String, nullable=True)
    vend_address                = Column(String, nullable=True)
    vend_phone                  = Column(String, nullable=True)
    vend_registration_number    = Column(String, nullable=True)
    vend_vat_number             = Column(String, nullable=True)
    vend_company_email          = Column(String, nullable=True)


class InvoiceHeaderModel(Base):

    __tablename__ = "invoice_header"

    invh_id                     = Column(Integer, primary_key=True, index=True)
    invh_vend_id                = Column(Integer, nullable=True)
    invh_number                 = Column(String, nullable=True)
    invh_date                   = Column(String, nullable=True)
    invh_currency               = Column(String, nullable=True)

    invh_gross_total            = Column(Float, nullable=True)
    invh_vat_amount             = Column(Float, nullable=True)
    invh_net_after_vat          = Column(Float, nullable=True)
    invh_calculation_check      = Column(Boolean, nullable=True)
   
class InvoiceDetailsModel(Base):

    __tablename__ = "invoice_details"

    invd_id                     = Column(Integer, primary_key=True, index=True)
    invd_invh_id                = Column(Integer, nullable=True)
    invd_description            = Column(String, nullable=True)
    invd_quantity               = Column(Float, nullable=True)
    invd_unit_price             = Column(Float, nullable=True)
    invd_total_price            = Column(Float, nullable=True)

    invd_discount               = Column(Float, nullable=True)
    invd_net_amount             = Column(Float, nullable=True)
    invd_vat_rate               = Column(Float, nullable=True)
    invd_vat_amount             = Column(Float, nullable=True)
    invd_total_price            = Column(Float, nullable=True)
    
    invd_calculation_check      = Column(Boolean, nullable=True)
