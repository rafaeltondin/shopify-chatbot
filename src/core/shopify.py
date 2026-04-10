# -*- coding: utf-8 -*-
"""
Cliente para Shopify Admin API (GraphQL + REST fallback).
Permite buscar produtos, pedidos, clientes e variantes da loja Shopify.
"""
import logging
import httpx
import json
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)

# Será inicializado no lifespan
_shopify_client: Optional["ShopifyClient"] = None


class ShopifyClient:
    """Cliente async para Shopify Admin API via GraphQL."""

    def __init__(self, store_url: str, access_token: str, api_version: str = "2024-10"):
        # Normalizar URL: remover trailing slash e garantir formato correto
        self.store_url = store_url.rstrip("/")
        if not self.store_url.startswith("https://"):
            self.store_url = f"https://{self.store_url}"
        # Remover .myshopify.com se já tem, para evitar duplicação
        self.store_domain = self.store_url.replace("https://", "").replace("http://", "")

        self.access_token = access_token
        self.api_version = api_version
        self.graphql_url = f"{self.store_url}/admin/api/{api_version}/graphql.json"
        self.rest_base_url = f"{self.store_url}/admin/api/{api_version}"

        self._http_client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "X-Shopify-Access-Token": self.access_token,
                "Content-Type": "application/json",
            },
        )
        logger.info(f"ShopifyClient inicializado para {self.store_domain} (API {api_version})")

    async def close(self):
        """Fecha o cliente HTTP."""
        await self._http_client.aclose()
        logger.info("ShopifyClient fechado.")

    # ─────────────────────────────────────────────
    # GraphQL Helper
    # ─────────────────────────────────────────────
    async def _graphql(self, query: str, variables: Optional[Dict] = None) -> Dict[str, Any]:
        """Executa uma query GraphQL na Shopify Admin API."""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = await self._http_client.post(self.graphql_url, json=payload)
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                logger.error(f"Shopify GraphQL errors: {data['errors']}")
                return {"errors": data["errors"], "data": data.get("data")}

            return data.get("data", {})

        except httpx.HTTPStatusError as e:
            logger.error(f"Shopify API HTTP error {e.response.status_code}: {e.response.text[:500]}")
            raise
        except Exception as e:
            logger.error(f"Shopify API error: {e}", exc_info=True)
            raise

    # ─────────────────────────────────────────────
    # PRODUTOS
    # ─────────────────────────────────────────────
    async def get_products(self, first: int = 20, query: Optional[str] = None) -> List[Dict]:
        """
        Busca produtos da loja Shopify.

        Args:
            first: Quantidade de produtos (max 250)
            query: Filtro de busca (ex: "title:camiseta", "product_type:acessório")

        Returns:
            Lista de produtos com título, descrição, preços, imagens e variantes
        """
        query_filter = f', query: "{query}"' if query else ""

        gql = f"""
        {{
            products(first: {first}{query_filter}) {{
                edges {{
                    node {{
                        id
                        title
                        handle
                        descriptionHtml
                        description
                        productType
                        vendor
                        status
                        totalInventory
                        onlineStoreUrl
                        featuredImage {{
                            url
                            altText
                        }}
                        priceRangeV2 {{
                            minVariantPrice {{
                                amount
                                currencyCode
                            }}
                            maxVariantPrice {{
                                amount
                                currencyCode
                            }}
                        }}
                        variants(first: 100) {{
                            edges {{
                                node {{
                                    id
                                    title
                                    price
                                    compareAtPrice
                                    availableForSale
                                    inventoryQuantity
                                    sku
                                    selectedOptions {{
                                        name
                                        value
                                    }}
                                }}
                            }}
                        }}
                        tags
                        createdAt
                        updatedAt
                    }}
                }}
            }}
        }}
        """
        result = await self._graphql(gql)
        products = result.get("products", {}).get("edges", [])
        return [edge["node"] for edge in products]

    async def get_product_by_id(self, product_id: str) -> Optional[Dict]:
        """Busca um produto específico pelo ID (formato gid://shopify/Product/123)."""
        if not product_id.startswith("gid://"):
            product_id = f"gid://shopify/Product/{product_id}"

        gql = """
        query getProduct($id: ID!) {
            product(id: $id) {
                id
                title
                handle
                descriptionHtml
                description
                productType
                vendor
                status
                totalInventory
                onlineStoreUrl
                featuredImage {
                    url
                    altText
                }
                priceRangeV2 {
                    minVariantPrice {
                        amount
                        currencyCode
                    }
                    maxVariantPrice {
                        amount
                        currencyCode
                    }
                }
                variants(first: 100) {
                    edges {
                        node {
                            id
                            title
                            price
                            compareAtPrice
                            availableForSale
                            inventoryQuantity
                            sku
                            selectedOptions {
                                name
                                value
                            }
                        }
                    }
                }
                tags
                createdAt
                updatedAt
            }
        }
        """
        result = await self._graphql(gql, {"id": product_id})
        return result.get("product")

    # Sinônimos para expandir buscas — mapeia termos genéricos para termos específicos do catálogo
    _SEARCH_SYNONYMS = {
        "calcado": ["sapatilha", "tenis", "chinelo"],
        "calçado": ["sapatilha", "tenis", "chinelo"],
        "sapato": ["sapatilha", "tenis"],
        "academia": ["treino", "sapatilha", "barefoot", "musculação"],
        "musculacao": ["treino", "sapatilha", "barefoot", "academia"],
        "musculação": ["treino", "sapatilha", "barefoot", "academia"],
        "treino": ["sapatilha", "tenis", "academia", "barefoot"],
        "corrida": ["running", "tenis"],
        "protecao": ["manguito", "munhequeira", "strap", "faixa"],
        "proteção": ["manguito", "munhequeira", "strap", "faixa"],
        "mao": ["luva", "strap", "octo", "grip"],
        "mão": ["luva", "strap", "octo", "grip"],
        "perna": ["meia", "compressão", "caneleira"],
        "braco": ["manguito", "munhequeira"],
        "braço": ["manguito", "munhequeira"],
        "ioga": ["sapatilha", "balance"],
        "yoga": ["sapatilha", "balance"],
        "pilates": ["sapatilha", "balance"],
        "crossfit": ["strap", "munhequeira", "sapatilha", "joelho"],
    }

    async def search_products(self, search_term: str, first: int = 10) -> List[Dict]:
        """
        Busca produtos por termo de pesquisa (título, descrição, tags).
        Estratégia: busca exata → termos separados → sinônimos → expansão de categoria.
        """
        all_results = []
        seen_ids = set()

        def _add_results(products):
            for p in products:
                pid = p.get("id")
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    all_results.append(p)

        # 1. Busca com todos os termos
        results = await self.get_products(first=first, query=search_term)
        _add_results(results)

        # 2. Se poucos resultados e múltiplas palavras, tentar cada termo
        terms = search_term.lower().strip().split()
        if len(all_results) < 3 and len(terms) > 1:
            for term in terms:
                if len(term) < 3:
                    continue
                term_results = await self.get_products(first=first, query=term)
                _add_results(term_results)

        # 3. Se ainda poucos, expandir com sinônimos
        if len(all_results) < 3:
            extra_terms = set()
            for term in terms:
                synonyms = self._SEARCH_SYNONYMS.get(term, [])
                for syn in synonyms:
                    if syn not in terms:
                        extra_terms.add(syn)
            for syn_term in list(extra_terms)[:4]:
                syn_results = await self.get_products(first=3, query=syn_term)
                _add_results(syn_results)

        # Filtrar produtos ACTIVE e com estoque > 0 primeiro, depois esgotados
        available = [p for p in all_results if p.get("totalInventory", 0) > 0 and p.get("status") != "DRAFT"]
        unavailable = [p for p in all_results if p.get("totalInventory", 0) <= 0 and p not in available]

        return (available + unavailable)[:first]

    # ─────────────────────────────────────────────
    # PEDIDOS
    # ─────────────────────────────────────────────
    async def get_orders(self, first: int = 20, query: Optional[str] = None) -> List[Dict]:
        """
        Busca pedidos da loja.

        Args:
            first: Quantidade de pedidos
            query: Filtro (ex: "email:cliente@email.com", "financial_status:paid")
        """
        query_filter = f', query: "{query}"' if query else ""

        gql = f"""
        {{
            orders(first: {first}{query_filter}, sortKey: CREATED_AT, reverse: true) {{
                edges {{
                    node {{
                        id
                        name
                        email
                        phone
                        createdAt
                        displayFinancialStatus
                        displayFulfillmentStatus
                        totalPriceSet {{
                            shopMoney {{
                                amount
                                currencyCode
                            }}
                        }}
                        subtotalPriceSet {{
                            shopMoney {{
                                amount
                                currencyCode
                            }}
                        }}
                        totalShippingPriceSet {{
                            shopMoney {{
                                amount
                                currencyCode
                            }}
                        }}
                        lineItems(first: 20) {{
                            edges {{
                                node {{
                                    title
                                    quantity
                                    originalUnitPriceSet {{
                                        shopMoney {{
                                            amount
                                            currencyCode
                                        }}
                                    }}
                                    variant {{
                                        title
                                        sku
                                    }}
                                }}
                            }}
                        }}
                        shippingAddress {{
                            city
                            province
                            country
                        }}
                        fulfillments {{
                            status
                            trackingInfo {{
                                number
                                url
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """
        result = await self._graphql(gql)
        orders = result.get("orders", {}).get("edges", [])
        return [edge["node"] for edge in orders]

    async def get_orders_by_customer_email(self, email: str, first: int = 10) -> List[Dict]:
        """Busca pedidos de um cliente pelo email."""
        return await self.get_orders(first=first, query=f"email:{email}")

    async def get_orders_by_phone(self, phone: str, first: int = 10) -> List[Dict]:
        """Busca pedidos de um cliente pelo telefone."""
        # Limpar número para busca
        clean_phone = phone.replace("+", "").replace("-", "").replace(" ", "")
        return await self.get_orders(first=first, query=f"phone:{clean_phone}")

    async def get_order_by_name(self, order_name: str) -> Optional[Dict]:
        """
        Busca um pedido pelo nome/número (ex: #1001).
        Útil quando o cliente informa o número do pedido no WhatsApp.
        """
        if not order_name.startswith("#"):
            order_name = f"#{order_name}"

        orders = await self.get_orders(first=1, query=f"name:{order_name}")
        return orders[0] if orders else None

    # ─────────────────────────────────────────────
    # CLIENTES
    # ─────────────────────────────────────────────
    async def get_customer_by_phone(self, phone: str) -> Optional[Dict]:
        """Busca cliente pelo telefone."""
        clean_phone = phone.replace("+", "").replace("-", "").replace(" ", "")

        gql = f"""
        {{
            customers(first: 1, query: "phone:{clean_phone}") {{
                edges {{
                    node {{
                        id
                        firstName
                        lastName
                        email
                        phone
                        numberOfOrders
                        amountSpent {{
                            amount
                            currencyCode
                        }}
                        tags
                        createdAt
                        addresses {{
                            city
                            province
                            country
                        }}
                    }}
                }}
            }}
        }}
        """
        result = await self._graphql(gql)
        customers = result.get("customers", {}).get("edges", [])
        return customers[0]["node"] if customers else None

    async def get_customer_by_email(self, email: str) -> Optional[Dict]:
        """Busca cliente pelo email."""
        gql = f"""
        {{
            customers(first: 1, query: "email:{email}") {{
                edges {{
                    node {{
                        id
                        firstName
                        lastName
                        email
                        phone
                        numberOfOrders
                        amountSpent {{
                            amount
                            currencyCode
                        }}
                        tags
                        createdAt
                    }}
                }}
            }}
        }}
        """
        result = await self._graphql(gql)
        customers = result.get("customers", {}).get("edges", [])
        return customers[0]["node"] if customers else None

    # ─────────────────────────────────────────────
    # CHECKOUT / CARRINHO
    # ─────────────────────────────────────────────
    async def get_popular_products(self, first: int = 5) -> List[Dict]:
        """Busca produtos mais vendidos / com mais estoque (proxy para 'populares')."""
        gql = f"""
        {{
            products(first: {first}, sortKey: UPDATED_AT, reverse: true) {{
                edges {{
                    node {{
                        id
                        title
                        handle
                        description
                        totalInventory
                        onlineStoreUrl
                        priceRangeV2 {{
                            minVariantPrice {{ amount currencyCode }}
                            maxVariantPrice {{ amount currencyCode }}
                        }}
                        featuredImage {{ url altText }}
                        variants(first: 100) {{
                            edges {{
                                node {{
                                    id title price availableForSale inventoryQuantity
                                    selectedOptions {{ name value }}
                                }}
                            }}
                        }}
                        tags
                    }}
                }}
            }}
        }}
        """
        result = await self._graphql(gql)
        products = result.get("products", {}).get("edges", [])
        return [e["node"] for e in products]

    async def check_variant_stock(self, variant_id: str) -> Optional[Dict]:
        """Verifica estoque de uma variante específica."""
        if not variant_id.startswith("gid://"):
            variant_id = f"gid://shopify/ProductVariant/{variant_id}"

        gql = """
        query checkStock($id: ID!) {
            productVariant(id: $id) {
                id
                title
                inventoryQuantity
                availableForSale
                price
                product { title }
            }
        }
        """
        result = await self._graphql(gql, {"id": variant_id})
        return result.get("productVariant")

    async def get_shipping_zones(self) -> List[Dict]:
        """Busca zonas de entrega configuradas na Shopify."""
        gql = """
        {
            deliveryProfiles(first: 5) {
                edges {
                    node {
                        name
                        profileLocationGroups {
                            locationGroupZones(first: 10) {
                                edges {
                                    node {
                                        zone { name countries { name code { countryCode } } }
                                        methodDefinitions(first: 5) {
                                            edges {
                                                node {
                                                    name
                                                    rateProvider {
                                                        ... on DeliveryRateDefinition {
                                                            price { amount currencyCode }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        try:
            result = await self._graphql(gql)
            return result.get("deliveryProfiles", {}).get("edges", [])
        except Exception as e:
            logger.error(f"Erro ao buscar zonas de entrega: {e}")
            return []

    async def get_shop_policies(self) -> Dict[str, str]:
        """Busca políticas da loja (reembolso, privacidade, termos, envio)."""
        gql = """
        {
            shop {
                shopPolicies {
                    title
                    body
                    type
                }
            }
        }
        """
        try:
            result = await self._graphql(gql)
            shop_policies = result.get("shop", {}).get("shopPolicies", [])
            policies = {}
            type_map = {
                "REFUND_POLICY": "refundPolicy",
                "PRIVACY_POLICY": "privacyPolicy",
                "TERMS_OF_SERVICE": "termsOfService",
                "SHIPPING_POLICY": "shippingPolicy",
                "SUBSCRIPTION_POLICY": "subscriptionPolicy",
                "LEGAL_NOTICE": "legalNotice",
            }
            for policy in shop_policies:
                policy_type = policy.get("type", "")
                key = type_map.get(policy_type, policy_type)
                body = policy.get("body", "")
                if body:
                    if len(body) > 500:
                        body = body[:500] + "..."
                    policies[key] = {"title": policy.get("title", ""), "body": body}
            return policies
        except Exception as e:
            logger.error(f"Erro ao buscar políticas da loja: {e}")
            return {}

    async def recommend_products_by_purchase(self, product_ids: List[str], first: int = 4) -> List[Dict]:
        """
        Busca recomendações de produtos baseado em compras anteriores.
        Usa tags dos produtos comprados para encontrar similares.
        """
        if not product_ids:
            return await self.get_popular_products(first)

        # Buscar tags dos produtos comprados
        all_tags = set()
        for pid in product_ids[:3]:  # Limitar a 3 para performance
            product = await self.get_product_by_id(pid)
            if product and product.get("tags"):
                all_tags.update(product["tags"][:5])

        if not all_tags:
            return await self.get_popular_products(first)

        # Buscar produtos com tags similares
        tag_query = " OR ".join([f"tag:{t}" for t in list(all_tags)[:5]])
        results = await self.get_products(first=first + len(product_ids), query=tag_query)

        # Filtrar produtos já comprados
        return [p for p in results if p.get("id") not in product_ids][:first]

    async def verify_customer_identity(self, phone: str, verification_data: Dict) -> Dict[str, Any]:
        """
        Verifica a identidade do cliente comparando dados fornecidos com dados da Shopify.

        Args:
            phone: Telefone do cliente
            verification_data: Dict com dados a verificar. Ex:
                {"email": "cliente@email.com"} ou
                {"order_number": "#1001"} ou
                {"name": "Maria Silva"}

        Returns:
            Dict com: verified (bool), match_type (str), customer_data (dict se verificado)
        """
        clean_phone = phone.replace("+", "").replace("-", "").replace(" ", "").replace("@s.whatsapp.net", "")
        result = {"verified": False, "match_type": None, "message": ""}

        try:
            # Buscar cliente pelo telefone
            customer = await self.get_customer_by_phone(clean_phone)

            if not customer:
                result["message"] = "Nenhum cadastro encontrado para este número."
                return result

            # Verificar por email
            if verification_data.get("email"):
                provided_email = verification_data["email"].strip().lower()
                shopify_email = (customer.get("email") or "").lower()
                if provided_email == shopify_email:
                    result["verified"] = True
                    result["match_type"] = "email"
                    result["message"] = "Identidade verificada por email."
                else:
                    result["message"] = "O email informado não corresponde ao cadastro."
                return result

            # Verificar por número de pedido
            if verification_data.get("order_number"):
                order_num = verification_data["order_number"]
                order = await self.get_order_by_name(order_num)
                if order:
                    order_phone = (order.get("phone") or "").replace("+", "").replace("-", "").replace(" ", "")
                    order_email = (order.get("email") or "").lower()
                    customer_email = (customer.get("email") or "").lower()

                    if clean_phone in order_phone or (customer_email and customer_email == order_email):
                        result["verified"] = True
                        result["match_type"] = "order_number"
                        result["message"] = "Identidade verificada pelo número do pedido."
                    else:
                        result["message"] = "Este pedido não pertence a este número."
                else:
                    result["message"] = f"Pedido {order_num} não encontrado."
                return result

            # Verificar por nome
            if verification_data.get("name"):
                provided_name = verification_data["name"].strip().lower()
                shopify_name = f"{customer.get('firstName', '')} {customer.get('lastName', '')}".strip().lower()
                # Match parcial (primeiro nome)
                first_name = (customer.get("firstName") or "").lower()
                if provided_name == shopify_name or (first_name and first_name in provided_name):
                    result["verified"] = True
                    result["match_type"] = "name"
                    result["message"] = "Identidade verificada pelo nome."
                else:
                    result["message"] = "O nome informado não corresponde ao cadastro."
                return result

            result["message"] = "Nenhum dado de verificação fornecido."
            return result

        except Exception as e:
            logger.error(f"Erro na verificação de identidade para {clean_phone}: {e}", exc_info=True)
            result["message"] = "Erro ao verificar identidade. Tente novamente."
            return result

    async def create_checkout_link(self, variant_id: str, quantity: int = 1) -> Optional[str]:
        """
        Gera um link de checkout direto para um produto/variante.
        Útil para enviar ao cliente no WhatsApp como atalho de compra.
        """
        # Extrair o ID numérico do variant
        numeric_id = variant_id.replace("gid://shopify/ProductVariant/", "")
        checkout_url = f"{self.store_url}/cart/{numeric_id}:{quantity}"
        return checkout_url

    # ─────────────────────────────────────────────
    # CUPONS DE DESCONTO
    # ─────────────────────────────────────────────
    async def create_discount_code(
        self,
        code: str,
        title: str,
        percentage: float,
        starts_at: Optional[str] = None,
        ends_at: Optional[str] = None,
        usage_limit: int = 1,
        applies_once_per_customer: bool = True,
        minimum_subtotal: Optional[float] = None,
    ) -> Optional[Dict]:
        """
        Cria um cupom de desconto percentual na Shopify.

        Args:
            code: Código do cupom (ex: "WELCOME10")
            title: Nome interno do cupom
            percentage: Porcentagem de desconto (ex: 10.0 para 10%)
            starts_at: ISO 8601 datetime de início (default: agora)
            ends_at: ISO 8601 datetime de expiração (default: None = sem expiração)
            usage_limit: Máximo de usos totais (default: 1)
            applies_once_per_customer: Se cada cliente pode usar só 1 vez
            minimum_subtotal: Valor mínimo de compra para aplicar o cupom

        Returns:
            Dict com dados do cupom criado ou None em caso de erro
        """
        if not starts_at:
            from datetime import datetime, timezone
            starts_at = datetime.now(timezone.utc).isoformat()

        # Montar variáveis da mutation
        variables = {
            "basicCodeDiscount": {
                "title": title,
                "code": code,
                "startsAt": starts_at,
                "endsAt": ends_at,
                "usageLimit": usage_limit,
                "appliesOncePerCustomer": applies_once_per_customer,
                "customerSelection": {
                    "all": True,
                },
                "customerGets": {
                    "value": {
                        "percentage": percentage / 100.0,  # Shopify espera decimal (0.1 = 10%)
                    },
                    "items": {
                        "all": True,
                    },
                },
                "combinesWith": {
                    "orderDiscounts": False,
                    "productDiscounts": False,
                    "shippingDiscounts": True,
                },
            }
        }

        # Adicionar valor mínimo se especificado
        if minimum_subtotal is not None:
            variables["basicCodeDiscount"]["minimumRequirement"] = {
                "subtotal": {
                    "greaterThanOrEqualToSubtotal": str(minimum_subtotal),
                },
            }

        gql = """
        mutation discountCodeBasicCreate($basicCodeDiscount: DiscountCodeBasicInput!) {
            discountCodeBasicCreate(basicCodeDiscount: $basicCodeDiscount) {
                codeDiscountNode {
                    id
                    codeDiscount {
                        ... on DiscountCodeBasic {
                            title
                            codes(first: 1) {
                                edges {
                                    node {
                                        code
                                    }
                                }
                            }
                            startsAt
                            endsAt
                            usageLimit
                            customerGets {
                                value {
                                    ... on DiscountPercentage {
                                        percentage
                                    }
                                }
                            }
                        }
                    }
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        try:
            result = await self._graphql(gql, variables)

            if "errors" in result:
                logger.error(f"Shopify GraphQL errors ao criar cupom: {result['errors']}")
                return None

            create_result = result.get("discountCodeBasicCreate", {})
            user_errors = create_result.get("userErrors", [])

            if user_errors:
                logger.error(f"Shopify userErrors ao criar cupom: {user_errors}")
                return None

            discount_node = create_result.get("codeDiscountNode", {})
            logger.info(f"Cupom '{code}' criado com sucesso na Shopify. ID: {discount_node.get('id')}")
            return discount_node

        except Exception as e:
            logger.error(f"Erro ao criar cupom na Shopify: {e}", exc_info=True)
            return None

    async def has_recent_order(self, phone: str, days: int = 7) -> bool:
        """
        Verifica se um número de telefone tem pedido nos últimos N dias.

        Args:
            phone: Número de telefone do cliente
            days: Quantidade de dias para verificar (default: 7)

        Returns:
            True se tem pedido recente, False caso contrário
        """
        from datetime import datetime, timedelta, timezone

        clean_phone = phone.replace("+", "").replace("-", "").replace(" ", "").replace("@s.whatsapp.net", "")
        since_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")

        gql = f"""
        {{
            orders(first: 1, query: "phone:{clean_phone} created_at:>={since_date}") {{
                edges {{
                    node {{
                        id
                        name
                        createdAt
                    }}
                }}
            }}
        }}
        """

        try:
            result = await self._graphql(gql)
            orders = result.get("orders", {}).get("edges", [])
            has_order = len(orders) > 0

            if has_order:
                order_name = orders[0]["node"].get("name", "N/A")
                logger.info(f"Cliente {clean_phone} tem pedido recente: {order_name}")
            else:
                logger.info(f"Cliente {clean_phone} NÃO tem pedido nos últimos {days} dias")

            return has_order

        except Exception as e:
            logger.error(f"Erro ao verificar pedido recente para {clean_phone}: {e}", exc_info=True)
            return False  # Em caso de erro, não enviar cupom (segurança)

    # ─────────────────────────────────────────────
    # PERFIL COMPLETO DO CLIENTE (para contexto LLM)
    # ─────────────────────────────────────────────
    async def get_full_customer_profile(self, phone: str) -> Dict[str, Any]:
        """
        Busca perfil completo do cliente na Shopify para enriquecimento de contexto.
        Retorna dados unificados: dados pessoais + pedidos + produtos comprados + preferências.

        Args:
            phone: Número de telefone do cliente

        Returns:
            Dict com todos os dados disponíveis do cliente
        """
        clean_phone = phone.replace("+", "").replace("-", "").replace(" ", "").replace("@s.whatsapp.net", "")
        profile = {
            "found": False,
            "customer": None,
            "orders": [],
            "products_purchased": [],
            "total_spent": 0,
            "orders_count": 0,
            "is_returning": False,
            "tags": [],
            "last_order_date": None,
            "favorite_categories": [],
            "average_order_value": 0,
        }

        try:
            # 1. Buscar dados do cliente
            customer = await self.get_customer_by_phone(clean_phone)
            if customer:
                profile["found"] = True
                profile["customer"] = {
                    "id": customer.get("id"),
                    "first_name": customer.get("firstName", ""),
                    "last_name": customer.get("lastName", ""),
                    "email": customer.get("email", ""),
                    "phone": customer.get("phone", ""),
                    "orders_count": customer.get("numberOfOrders", 0),
                    "total_spent": float(customer.get("amountSpent", {}).get("amount", 0) if customer.get("amountSpent") else 0),
                    "tags": customer.get("tags", []),
                    "created_at": customer.get("createdAt", ""),
                }
                profile["total_spent"] = profile["customer"]["total_spent"]
                profile["orders_count"] = profile["customer"]["orders_count"]
                profile["is_returning"] = profile["orders_count"] > 0
                profile["tags"] = profile["customer"]["tags"]

            # 2. Buscar pedidos recentes (últimos 5)
            orders = await self.get_orders_by_phone(clean_phone, first=5)
            if orders:
                profile["found"] = True
                profile["is_returning"] = True

                categories = {}
                for order in orders:
                    order_name = order.get("name", "")
                    created = order.get("createdAt", "")
                    total = float(order.get("totalPriceSet", {}).get("shopMoney", {}).get("amount", 0))
                    financial = order.get("displayFinancialStatus", "")
                    fulfillment = order.get("displayFulfillmentStatus", "")

                    # Extrair produtos comprados
                    items = []
                    for edge in order.get("lineItems", {}).get("edges", []):
                        node = edge["node"]
                        item_title = node.get("title", "")
                        items.append(item_title)
                        profile["products_purchased"].append(item_title)

                        # Rastrear categorias via variant
                        variant = node.get("variant", {}) or {}
                        variant_title = variant.get("title", "")
                        if variant_title and variant_title != "Default Title":
                            categories[variant_title] = categories.get(variant_title, 0) + 1

                    # Rastreamento de tracking
                    tracking = []
                    for f in order.get("fulfillments", []):
                        for t in f.get("trackingInfo", []):
                            if t.get("number"):
                                tracking.append({"number": t["number"], "url": t.get("url", "")})

                    profile["orders"].append({
                        "name": order_name,
                        "date": created,
                        "total": total,
                        "financial_status": financial,
                        "fulfillment_status": fulfillment,
                        "items": items,
                        "tracking": tracking,
                    })

                # Calcular data do último pedido
                if profile["orders"]:
                    profile["last_order_date"] = profile["orders"][0].get("date")

                # Categorias favoritas (top 3)
                if categories:
                    sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)
                    profile["favorite_categories"] = [c[0] for c in sorted_cats[:3]]

                # Ticket médio
                if orders:
                    totals = [float(o.get("totalPriceSet", {}).get("shopMoney", {}).get("amount", 0)) for o in orders]
                    profile["average_order_value"] = round(sum(totals) / len(totals), 2)

        except Exception as e:
            logger.error(f"Erro ao buscar perfil do cliente {clean_phone}: {e}", exc_info=True)

        return profile

    def format_customer_context_for_llm(self, profile: Dict[str, Any], interests: List[str] = None) -> str:
        """
        Formata o perfil do cliente como texto de contexto para o LLM.
        O LLM recebe isso como mensagem de sistema antes de responder.
        """
        if not profile.get("found"):
            context = "## PERFIL DO CLIENTE\nCliente novo — primeira vez entrando em contato. Não há histórico na loja."
            if interests:
                context += f"\nInteresses detectados na conversa: {', '.join(interests)}"
            return context

        customer = profile.get("customer") or {}
        name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
        email = customer.get("email", "")
        total_spent = profile.get("total_spent", 0)
        orders_count = profile.get("orders_count", 0)
        avg_order = profile.get("average_order_value", 0)
        tags = profile.get("tags", [])
        products = profile.get("products_purchased", [])
        fav_categories = profile.get("favorite_categories", [])
        last_order_date = profile.get("last_order_date", "")

        lines = ["## PERFIL DO CLIENTE (dados reais da Shopify — use para personalizar)"]

        if name:
            lines.append(f"- Nome: {name}")
        if email:
            lines.append(f"- Email: {email}")

        if orders_count > 0:
            lines.append(f"- Cliente recorrente: {orders_count} pedido(s)")
            lines.append(f"- Total gasto: R$ {total_spent:.2f}")
            lines.append(f"- Ticket médio: R$ {avg_order:.2f}")
        else:
            lines.append("- Cadastrado mas ainda sem pedidos")

        if last_order_date:
            try:
                dt = datetime.fromisoformat(last_order_date.replace("Z", "+00:00"))
                lines.append(f"- Último pedido: {dt.strftime('%d/%m/%Y')}")
            except Exception:
                pass

        if products:
            unique_products = list(dict.fromkeys(products))[:8]  # Top 8 únicos
            lines.append(f"- Produtos já comprados: {', '.join(unique_products)}")

        if fav_categories:
            lines.append(f"- Categorias preferidas: {', '.join(fav_categories)}")

        if tags:
            lines.append(f"- Tags do cliente: {', '.join(tags)}")

        # Pedidos recentes com status
        recent_orders = profile.get("orders", [])[:3]
        if recent_orders:
            lines.append("\n### Pedidos recentes:")
            for o in recent_orders:
                status_map = {
                    "PAID": "Pago", "PENDING": "Pendente", "REFUNDED": "Reembolsado",
                    "FULFILLED": "Enviado", "UNFULFILLED": "Aguardando envio",
                    "IN_TRANSIT": "Em trânsito", "DELIVERED": "Entregue",
                }
                fin = status_map.get(o.get("financial_status", ""), o.get("financial_status", ""))
                ful = status_map.get(o.get("fulfillment_status", ""), o.get("fulfillment_status", ""))
                items_str = ", ".join(o.get("items", [])[:3])
                tracking_str = ""
                if o.get("tracking"):
                    tracking_str = f" | Rastreio: {o['tracking'][0]['number']}"
                lines.append(f"  - {o.get('name')}: R$ {o.get('total', 0):.2f} — {fin} / {ful} — {items_str}{tracking_str}")

        # Interesses detectados na conversa
        if interests:
            lines.append(f"\n### Interesses detectados nesta conversa:")
            lines.append(f"  {', '.join(interests)}")

        # Instruções de personalização
        lines.append("\n### REGRAS DE PERSONALIZAÇÃO:")
        if orders_count > 0:
            lines.append("- USE o nome do cliente nas respostas")
            lines.append("- REFERENCIE produtos que ele já comprou para sugerir complementos")
            lines.append("- Se perguntar sobre pedido, consulte os dados acima ANTES de usar a ferramenta")
            lines.append("- Trate como VIP se total_gasto > 500")
        else:
            lines.append("- Trate como cliente novo, seja acolhedor")
            lines.append("- Sugira produtos populares como ponto de partida")

        if products:
            lines.append(f"- Para cross-sell: sugira produtos complementares aos que ele já comprou ({', '.join(products[:3])})")

        return "\n".join(lines)

    # ─────────────────────────────────────────────
    # HELPERS PARA O CHATBOT
    # ─────────────────────────────────────────────
    def format_product_for_chat(self, product: Dict) -> str:
        """Formata informações de produto para envio via WhatsApp."""
        title = product.get("title", "Produto")
        description = product.get("description", "")
        if len(description) > 300:
            description = description[:300] + "..."

        price_range = product.get("priceRangeV2", {})
        min_price = price_range.get("minVariantPrice", {}).get("amount", "0")
        max_price = price_range.get("maxVariantPrice", {}).get("amount", "0")
        currency = price_range.get("minVariantPrice", {}).get("currencyCode", "BRL")

        if min_price == max_price:
            price_text = f"R$ {float(min_price):.2f}"
        else:
            price_text = f"R$ {float(min_price):.2f} - R$ {float(max_price):.2f}"

        inventory = product.get("totalInventory", 0)
        stock_text = f"Em estoque ({inventory} unid.)" if inventory > 0 else "Esgotado"

        # Variantes
        variants = product.get("variants", {}).get("edges", [])
        variant_text = ""
        if len(variants) > 1:
            options = []
            for v in variants[:5]:
                node = v["node"]
                opt_names = [f"{o['name']}: {o['value']}" for o in node.get("selectedOptions", [])]
                options.append(f"  - {', '.join(opt_names)} — R$ {float(node['price']):.2f}")
            variant_text = "\n*Opções:*\n" + "\n".join(options)

        url = product.get("onlineStoreUrl", "")
        url_text = f"\n🔗 {url}" if url else ""

        return (
            f"*{title}*\n"
            f"💰 {price_text}\n"
            f"📦 {stock_text}\n"
            f"\n{description}"
            f"{variant_text}"
            f"{url_text}"
        )

    def format_order_for_chat(self, order: Dict) -> str:
        """Formata informações de pedido para envio via WhatsApp."""
        name = order.get("name", "N/A")
        status_financial = order.get("displayFinancialStatus", "N/A")
        status_fulfillment = order.get("displayFulfillmentStatus", "N/A")

        total = order.get("totalPriceSet", {}).get("shopMoney", {})
        total_text = f"R$ {float(total.get('amount', 0)):.2f}"

        # Status traduzido
        status_map = {
            "PAID": "✅ Pago",
            "PENDING": "⏳ Pendente",
            "REFUNDED": "↩️ Reembolsado",
            "PARTIALLY_REFUNDED": "↩️ Parcialmente reembolsado",
            "AUTHORIZED": "🔐 Autorizado",
            "VOIDED": "❌ Cancelado",
        }
        fulfillment_map = {
            "FULFILLED": "📦 Enviado",
            "UNFULFILLED": "⏳ Aguardando envio",
            "PARTIALLY_FULFILLED": "📦 Parcialmente enviado",
            "IN_TRANSIT": "🚚 Em trânsito",
            "DELIVERED": "✅ Entregue",
        }

        financial_display = status_map.get(status_financial, status_financial)
        fulfillment_display = fulfillment_map.get(status_fulfillment, status_fulfillment)

        # Itens do pedido
        items = order.get("lineItems", {}).get("edges", [])
        items_text = ""
        if items:
            item_lines = []
            for item in items:
                node = item["node"]
                qty = node.get("quantity", 1)
                item_title = node.get("title", "Item")
                item_lines.append(f"  • {qty}x {item_title}")
            items_text = "\n*Itens:*\n" + "\n".join(item_lines)

        # Rastreamento
        tracking_text = ""
        fulfillments = order.get("fulfillments", [])
        for f in fulfillments:
            tracking_list = f.get("trackingInfo", [])
            for t in tracking_list:
                tracking_number = t.get("number", "")
                tracking_url = t.get("url", "")
                if tracking_number:
                    tracking_text = f"\n📋 Rastreamento: {tracking_number}"
                    if tracking_url:
                        tracking_text += f"\n🔗 {tracking_url}"

        created = order.get("createdAt", "")
        date_text = ""
        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                date_text = f"\n📅 Data: {dt.strftime('%d/%m/%Y %H:%M')}"
            except Exception:
                date_text = f"\n📅 Data: {created}"

        return (
            f"*Pedido {name}*\n"
            f"💳 {financial_display}\n"
            f"📦 {fulfillment_display}\n"
            f"💰 Total: {total_text}"
            f"{date_text}"
            f"{items_text}"
            f"{tracking_text}"
        )


# ─────────────────────────────────────────────
# Funções globais (acessadas pelos outros módulos)
# ─────────────────────────────────────────────
def get_shopify_client() -> Optional[ShopifyClient]:
    """Retorna a instância global do ShopifyClient."""
    return _shopify_client


async def initialize_shopify_client(store_url: str, access_token: str, api_version: str = "2024-10"):
    """Inicializa o cliente Shopify global."""
    global _shopify_client
    if _shopify_client:
        await _shopify_client.close()
    _shopify_client = ShopifyClient(store_url, access_token, api_version)
    logger.info(f"Shopify client inicializado para {store_url}")
    return _shopify_client


async def close_shopify_client():
    """Fecha o cliente Shopify global."""
    global _shopify_client
    if _shopify_client:
        await _shopify_client.close()
        _shopify_client = None


# ─────────────────────────────────────────────
# Funções de conveniência para o chatbot
# ─────────────────────────────────────────────
async def search_products_for_chat(search_term: str, limit: int = 5) -> List[Dict]:
    """Busca produtos e retorna formatado para uso no chatbot."""
    client = get_shopify_client()
    if not client:
        logger.error("ShopifyClient não inicializado")
        return []
    return await client.search_products(search_term, first=limit)


async def get_order_status_for_chat(order_number: str) -> Optional[str]:
    """Busca status de um pedido e retorna texto formatado para WhatsApp."""
    client = get_shopify_client()
    if not client:
        return None

    order = await client.get_order_by_name(order_number)
    if not order:
        return None
    return client.format_order_for_chat(order)


async def get_customer_orders_for_chat(phone: str, limit: int = 5) -> List[str]:
    """Busca pedidos de um cliente pelo telefone e retorna textos formatados."""
    client = get_shopify_client()
    if not client:
        return []

    orders = await client.get_orders_by_phone(phone, first=limit)
    return [client.format_order_for_chat(order) for order in orders]


async def generate_checkout_link(variant_id: str, quantity: int = 1) -> Optional[str]:
    """Gera link de checkout direto para enviar ao cliente."""
    client = get_shopify_client()
    if not client:
        return None
    return await client.create_checkout_link(variant_id, quantity)


async def get_popular_products_for_chat(limit: int = 5) -> List[Dict]:
    """Busca produtos populares."""
    client = get_shopify_client()
    if not client:
        return []
    return await client.get_popular_products(first=limit)


async def check_stock_for_chat(variant_id: str) -> Optional[Dict]:
    """Verifica estoque de uma variante."""
    client = get_shopify_client()
    if not client:
        return None
    return await client.check_variant_stock(variant_id)


async def get_store_policies_for_chat() -> Dict[str, str]:
    """Busca políticas da loja."""
    client = get_shopify_client()
    if not client:
        return {}
    return await client.get_shop_policies()


async def recommend_products_for_chat(product_ids: List[str], limit: int = 4) -> List[Dict]:
    """Busca recomendações baseadas em compras anteriores."""
    client = get_shopify_client()
    if not client:
        return []
    return await client.recommend_products_by_purchase(product_ids, first=limit)


async def verify_customer_for_chat(phone: str, verification_data: Dict) -> Dict:
    """Verifica identidade do cliente antes de mostrar dados sensíveis."""
    client = get_shopify_client()
    if not client:
        return {"verified": False, "message": "Shopify não configurado."}
    return await client.verify_customer_identity(phone, verification_data)


async def get_customer_context_for_llm(phone: str, interests: List[str] = None) -> str:
    """
    Busca perfil completo do cliente e retorna texto formatado para injetar no LLM.
    Essa é a função principal de personalização — chamada antes de cada interação.
    """
    client = get_shopify_client()
    if not client:
        return "## PERFIL DO CLIENTE\nShopify não configurado — sem dados do cliente disponíveis."

    try:
        profile = await client.get_full_customer_profile(phone)
        return client.format_customer_context_for_llm(profile, interests)
    except Exception as e:
        logger.error(f"Erro ao buscar contexto do cliente {phone}: {e}", exc_info=True)
        return "## PERFIL DO CLIENTE\nNão foi possível consultar dados do cliente na Shopify."


logger.info("shopify.py: Módulo carregado.")
