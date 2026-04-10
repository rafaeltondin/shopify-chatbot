# -*- coding: utf-8 -*-
"""
Endpoints para consulta de produtos da Shopify.
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.core.shopify import get_shopify_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/products", tags=["Products"])


# ─────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────
class ProductVariantResponse(BaseModel):
    id: str
    title: str
    price: str
    compare_at_price: Optional[str] = None
    available: bool = True
    inventory_quantity: Optional[int] = None
    sku: Optional[str] = None
    options: Optional[List[dict]] = None


class ProductResponse(BaseModel):
    id: str
    title: str
    handle: str
    description: Optional[str] = None
    product_type: Optional[str] = None
    vendor: Optional[str] = None
    status: Optional[str] = None
    total_inventory: Optional[int] = None
    online_store_url: Optional[str] = None
    featured_image_url: Optional[str] = None
    min_price: Optional[str] = None
    max_price: Optional[str] = None
    currency: Optional[str] = "BRL"
    variants: List[ProductVariantResponse] = []
    tags: Optional[List[str]] = None


class ProductListResponse(BaseModel):
    products: List[ProductResponse]
    total: int


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _parse_product(product: dict) -> ProductResponse:
    """Converte produto GraphQL para response model."""
    variants = []
    for edge in product.get("variants", {}).get("edges", []):
        node = edge["node"]
        variants.append(ProductVariantResponse(
            id=node["id"],
            title=node.get("title", ""),
            price=node.get("price", "0"),
            compare_at_price=node.get("compareAtPrice"),
            available=node.get("availableForSale", True),
            inventory_quantity=node.get("inventoryQuantity"),
            sku=node.get("sku"),
            options=node.get("selectedOptions"),
        ))

    price_range = product.get("priceRangeV2", {})
    min_price = price_range.get("minVariantPrice", {}).get("amount")
    max_price = price_range.get("maxVariantPrice", {}).get("amount")
    currency = price_range.get("minVariantPrice", {}).get("currencyCode", "BRL")

    featured_image = product.get("featuredImage", {})

    return ProductResponse(
        id=product["id"],
        title=product.get("title", ""),
        handle=product.get("handle", ""),
        description=product.get("description"),
        product_type=product.get("productType"),
        vendor=product.get("vendor"),
        status=product.get("status"),
        total_inventory=product.get("totalInventory"),
        online_store_url=product.get("onlineStoreUrl"),
        featured_image_url=featured_image.get("url") if featured_image else None,
        min_price=min_price,
        max_price=max_price,
        currency=currency,
        variants=variants,
        tags=product.get("tags"),
    )


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────
@router.get("/", response_model=ProductListResponse)
async def list_products(
    limit: int = Query(20, ge=1, le=250, description="Quantidade de produtos"),
    search: Optional[str] = Query(None, description="Termo de busca"),
):
    """Lista produtos da loja Shopify."""
    client = get_shopify_client()
    if not client:
        raise HTTPException(status_code=503, detail="Shopify client não configurado")

    try:
        products = await client.get_products(first=limit, query=search)
        parsed = [_parse_product(p) for p in products]
        return ProductListResponse(products=parsed, total=len(parsed))
    except Exception as e:
        logger.error(f"Erro ao listar produtos: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao consultar Shopify: {str(e)}")


@router.get("/search", response_model=ProductListResponse)
async def search_products(
    q: str = Query(..., min_length=1, description="Termo de busca"),
    limit: int = Query(10, ge=1, le=50),
):
    """Busca produtos por termo (título, descrição, tags)."""
    client = get_shopify_client()
    if not client:
        raise HTTPException(status_code=503, detail="Shopify client não configurado")

    try:
        products = await client.search_products(q, first=limit)
        parsed = [_parse_product(p) for p in products]
        return ProductListResponse(products=parsed, total=len(parsed))
    except Exception as e:
        logger.error(f"Erro ao buscar produtos: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro na busca: {str(e)}")


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: str):
    """Busca detalhes de um produto específico pelo ID."""
    client = get_shopify_client()
    if not client:
        raise HTTPException(status_code=503, detail="Shopify client não configurado")

    try:
        product = await client.get_product_by_id(product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Produto não encontrado")
        return _parse_product(product)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao buscar produto {product_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao consultar produto: {str(e)}")


@router.get("/{product_id}/checkout-link")
async def get_checkout_link(
    product_id: str,
    variant_id: Optional[str] = Query(None, description="ID da variante específica"),
    quantity: int = Query(1, ge=1, le=100),
):
    """Gera link de checkout direto para um produto."""
    client = get_shopify_client()
    if not client:
        raise HTTPException(status_code=503, detail="Shopify client não configurado")

    try:
        # Se não informou variant_id, pegar a primeira variante do produto
        if not variant_id:
            product = await client.get_product_by_id(product_id)
            if not product:
                raise HTTPException(status_code=404, detail="Produto não encontrado")
            variants = product.get("variants", {}).get("edges", [])
            if not variants:
                raise HTTPException(status_code=400, detail="Produto sem variantes disponíveis")
            variant_id = variants[0]["node"]["id"]

        checkout_url = await client.create_checkout_link(variant_id, quantity)
        return {"checkout_url": checkout_url, "variant_id": variant_id, "quantity": quantity}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao gerar checkout link: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao gerar link: {str(e)}")


logger.info("products.py: Módulo carregado.")
