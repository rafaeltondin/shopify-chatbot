# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict, Any, Annotated
from decimal import Decimal

class GenericResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None

class WalletBalanceResponse(BaseModel):
    balance: Decimal = Field(..., description="Saldo atual da carteira.")
    currency: str = Field("BRL", description="Moeda do saldo.")

class AddCreditRequest(BaseModel):
    amount: Annotated[Decimal, Field(gt=0, decimal_places=2, description="Valor a ser adicionado em BRL.")]

class InitiatePaymentResponseData(BaseModel):
    preference_id: str
    init_point: str
    external_reference: str
    db_transaction_id: int

class InitiatePaymentResponse(GenericResponse):
    data: Optional[InitiatePaymentResponseData] = None

class WalletTransactionItem(BaseModel):
    id: int
    type: str
    amount_brl: Decimal
    payment_method: Optional[str] = None
    payment_provider: Optional[str] = None
    transaction_id_provider: Optional[str] = None
    status: str
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: str

class WalletHistoryResponse(BaseModel):
    transactions: List[WalletTransactionItem]
    total_count: int
