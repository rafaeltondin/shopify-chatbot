# Shopify WhatsApp Chatbot

Chatbot de atendimento ao cliente via WhatsApp com integracao nativa ao Shopify.

## Funcionalidades

### Atendimento ao Cliente
- Respostas automaticas via WhatsApp com IA configuravel
- Consulta de **status de pedidos** em tempo real
- Exibicao de **codigo de rastreio** com link direto da transportadora
- Listagem do **historico de compras** do cliente
- Busca de produtos, estoque e recomendacoes personalizadas
- Geracao de links de checkout direto

### Vendas e Automacao
- Funil de vendas com multiplos estagios configuraveis
- Sistema de follow-up automatico
- Recuperacao de carrinho abandonado
- Deteccao semantica de intencoes do cliente
- Tags e automacoes baseadas em comportamento

### Operacional
- Agendamento e confirmacao de consultas/pedidos
- Notificacoes por e-mail (templates HTML)
- Dashboard web de gerenciamento
- Multi-instancia (uma instalacao por loja)
- Autenticacao JWT com painel administrativo

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.11 + FastAPI |
| Banco de dados | MySQL 8.0 |
| Cache / Filas | Redis 7 |
| IA / LLM | OpenRouter (GLM, GPT, Claude, etc.) |
| WhatsApp | Evolution API v2 |
| Shopify | Admin API 2025-01 (GraphQL + REST) |
| Deploy | Docker Compose |

## Consulta de Pedidos e Rastreio

O agente de IA tem acesso nativo aos dados de pedidos da Shopify. Os clientes podem perguntar via WhatsApp:

| O cliente diz... | O agente faz... |
|-----------------|-----------------|
| "onde esta meu pedido?" | Busca status por telefone ou numero do pedido |
| "codigo de rastreio do #1001" | Retorna codigo + link direto da transportadora |
| "quais meus pedidos recentes?" | Lista historico com status de pagamento e envio |
| "meu pedido foi entregue?" | Consulta status de fulfillment em tempo real |

### Transportadoras Suportadas (link automatico)
- Correios (codigo no formato )
- JadLog
- Total Express
- Loggi
- Melhor Envio

### Seguranca
Antes de exibir dados de pedidos, o sistema exige verificacao de identidade (e-mail cadastrado ou numero do pedido). A verificacao fica em cache por 30 minutos.

## Pre-requisitos

- Docker e Docker Compose instalados
- Conta no [OpenRouter](https://openrouter.ai)
- [Evolution API](https://github.com/EvolutionAPI/evolution-api) rodando e configurada
- Loja Shopify com token de acesso privado
- Dominio com proxy reverso (ex: OpenLiteSpeed / Nginx)

## Instalacao

```bash
# 1. Clone o repositorio
git clone https://github.com/rafaeltondin/shopify-chatbot.git
cd shopify-chatbot

# 2. Configure as variaveis de ambiente
cp .env.example .env

# 3. Adicione as variaveis de banco ao .env
echo "DB_ROOT_PASSWORD=sua-senha-root" >> .env
echo "DB_USER=mysql" >> .env
echo "DB_PASSWORD=sua-senha-db" >> .env
echo "HOST_PORT=8520" >> .env

# 4. Suba os containers
docker compose up -d --build
```

## Configuracao

Copie  para  e preencha:

| Variavel | Descricao |
|----------|-----------|
|  | Identificador unico da instancia |
|  | URL publica do chatbot |
|  /  | Credenciais do painel web |
|  | Chave secreta JWT (08b99e7fb4ddbd303d1c1cbb9bf2789b5155eaf05881b07531a49b101d0b4faa) |
|  | Dominio  da loja |
|  | Token de acesso privado Shopify |
|  | Chave da API OpenRouter |
|  | Modelo de IA (ex: ) |
|  | Senha root do MySQL |
|  | Usuario do banco |
|  | Senha do banco |
|  | Porta exposta pelo container (ex: ) |

## Estrutura do Projeto

```
shopify-chatbot/
├── main.py                  # Entrypoint FastAPI
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── llm_config.yaml
├── src/
│   ├── api/routes/          # Auth, pedidos, produtos, agenda, leads...
│   ├── core/
│   │   ├── llm.py           # Integracao OpenRouter + system prompt
│   │   ├── shopify.py       # Pedidos, rastreio, produtos (GraphQL)
│   │   ├── evolution.py     # Evolution API (WhatsApp)
│   │   ├── automation_engine.py
│   │   └── prospect_management/
│   └── utils/
└── static/                  # Frontend (HTML/CSS/JS)
```

## Acesso ao Painel

Apos subir, acesse  e faca login com  / .

Documentacao da API: 

## Proxy Reverso

```nginx
location / {
    proxy_pass http://127.0.0.1:8520;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

## Multiplas Instancias

Clone o projeto em diretorios separados com  e  distintos em cada .

## Licenca

MIT
