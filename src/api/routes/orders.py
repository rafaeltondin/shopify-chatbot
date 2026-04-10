# -*- coding: utf-8 -*-
"""
Endpoints para consulta de pedidos da Shopify.
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.core.shopify import get_shopify_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/orders", tags=["Orders"])


# ─────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────
class OrderItemResponse(BaseModel):
    title: str
    quantity: int
    unit_price: Optional[str] = None
    variant_title: Optional[str] = None
    sku: Optional[str] = None


class TrackingResponse(BaseModel):
    number: Optional[str] = None
    url: Optional[str] = None


class OrderResponse(BaseModel):
    id: str
    name: str  # Ex: #1001
    email: Optional[str] = None
    phone: Optional[str] = None
    created_at: Optional[str] = None
    financial_status: Optional[str] = None
    fulfillment_status: Optional[str] = None
    total: Optional[str] = None
    subtotal: Optional[str] = None
    shipping: Optional[str] = None
    currency: str = "BRL"
    items: List[OrderItemResponse] = []
    tracking: List[TrackingResponse] = []
    shipping_city: Optional[str] = None
    shipping_province: Optional[str] = None


class OrderListResponse(BaseModel):
    orders: List[OrderResponse]
    total: int


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _parse_order(order: dict) -> OrderResponse:
    """Converte pedido GraphQL para response model."""
    items = []
    for edge in order.get("lineItems", {}).get("edges", []):
        node = edge["node"]
        unit_price = node.get("originalUnitPriceSet", {}).get("shopMoney", {}).get("amount")
        variant = node.get("variant", {}) or {}
        items.append(OrderItemResponse(
            title=node.get("title", ""),
            quantity=node.get("quantity", 1),
            unit_price=unit_price,
            variant_title=variant.get("title"),
            sku=variant.get("sku"),
        ))

    tracking = []
    for f in order.get("fulfillments", []):
        for t in f.get("trackingInfo", []):
            tracking.append(TrackingResponse(
                number=t.get("number"),
                url=t.get("url"),
            ))

    total_set = order.get("totalPriceSet", {}).get("shopMoney", {})
    subtotal_set = order.get("subtotalPriceSet", {}).get("shopMoney", {})
    shipping_set = order.get("totalShippingPriceSet", {}).get("shopMoney", {})
    shipping_addr = order.get("shippingAddress", {}) or {}

    return OrderResponse(
        id=order.get("id", ""),
        name=order.get("name", ""),
        email=order.get("email"),
        phone=order.get("phone"),
        created_at=order.get("createdAt"),
        financial_status=order.get("displayFinancialStatus"),
        fulfillment_status=order.get("displayFulfillmentStatus"),
        total=total_set.get("amount"),
        subtotal=subtotal_set.get("amount"),
        shipping=shipping_set.get("amount"),
        currency=total_set.get("currencyCode", "BRL"),
        items=items,
        tracking=tracking,
        shipping_city=shipping_addr.get("city"),
        shipping_province=shipping_addr.get("province"),
    )


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────
@router.get("/", response_model=OrderListResponse)
async def list_orders(
    limit: int = Query(20, ge=1, le=250),
    search: Optional[str] = Query(None, description="Filtro de busca"),
):
    """Lista pedidos da loja Shopify."""
    client = get_shopify_client()
    if not client:
        raise HTTPException(status_code=503, detail="Shopify client não configurado")

    try:
        orders = await client.get_orders(first=limit, query=search)
        parsed = [_parse_order(o) for o in orders]
        return OrderListResponse(orders=parsed, total=len(parsed))
    except Exception as e:
        logger.error(f"Erro ao listar pedidos: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao consultar pedidos: {str(e)}")


@router.get("/by-phone/{phone}", response_model=OrderListResponse)
async def get_orders_by_phone(
    phone: str,
    limit: int = Query(10, ge=1, le=50),
):
    """Busca pedidos de um cliente pelo número de telefone."""
    client = get_shopify_client()
    if not client:
        raise HTTPException(status_code=503, detail="Shopify client não configurado")

    try:
        orders = await client.get_orders_by_phone(phone, first=limit)
        parsed = [_parse_order(o) for o in orders]
        return OrderListResponse(orders=parsed, total=len(parsed))
    except Exception as e:
        logger.error(f"Erro ao buscar pedidos por telefone {phone}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro na busca: {str(e)}")


@router.get("/by-email/{email}", response_model=OrderListResponse)
async def get_orders_by_email(
    email: str,
    limit: int = Query(10, ge=1, le=50),
):
    """Busca pedidos de um cliente pelo email."""
    client = get_shopify_client()
    if not client:
        raise HTTPException(status_code=503, detail="Shopify client não configurado")

    try:
        orders = await client.get_orders_by_customer_email(email, first=limit)
        parsed = [_parse_order(o) for o in orders]
        return OrderListResponse(orders=parsed, total=len(parsed))
    except Exception as e:
        logger.error(f"Erro ao buscar pedidos por email {email}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro na busca: {str(e)}")


@router.get("/track/{order_number}")
async def track_order(order_number: str):
    """
    Consulta status de um pedido pelo número (ex: 1001 ou #1001).
    Retorna informações formatadas para o chatbot.
    """
    client = get_shopify_client()
    if not client:
        raise HTTPException(status_code=503, detail="Shopify client não configurado")

    try:
        order = await client.get_order_by_name(order_number)
        if not order:
            raise HTTPException(status_code=404, detail=f"Pedido #{order_number} não encontrado")

        parsed = _parse_order(order)
        chat_text = client.format_order_for_chat(order)

        return {
            "order": parsed.model_dump(),
            "chat_formatted": chat_text,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao rastrear pedido {order_number}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao rastrear pedido: {str(e)}")


logger.info("orders.py: Módulo carregado.")
