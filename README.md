# Shopify WhatsApp Chatbot

Chatbot de atendimento ao cliente via WhatsApp com integração nativa ao Shopify, utilizando IA via OpenRouter e Evolution API para envio/recebimento de mensagens.

## Funcionalidades

- Atendimento automático via WhatsApp com IA configurável
- Integração com Shopify (pedidos, produtos, estoque)
- Dashboard web de gerenciamento
- Agendamento e confirmação de consultas/pedidos
- Sistema de follow-up e recuperação de carrinho
- Notificações por e-mail (templates HTML)
- Multi-instância (uma instalação por loja)
- Autenticação JWT com painel administrativo

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.11 + FastAPI |
| Banco de dados | MySQL 8.0 |
| Cache / Filas | Redis 7 |
| IA / LLM | OpenRouter (GLM, GPT, Claude, etc.) |
| WhatsApp | Evolution API v2 |
| Shopify | REST API 2025-01 |
| Deploy | Docker Compose |

## Pré-requisitos

- Docker e Docker Compose instalados
- Conta no [OpenRouter](https://openrouter.ai)
- [Evolution API](https://github.com/EvolutionAPI/evolution-api) rodando e configurada
- Loja Shopify com token de acesso privado
- Domínio com proxy reverso (ex: OpenLiteSpeed / Nginx)

## Instalação

```bash
# 1. Clone o repositório
git clone https://github.com/rafaeltondin/shopify-chatbot.git
cd shopify-chatbot

# 2. Configure as variáveis de ambiente
cp .env.example .env
# Edite .env com suas credenciais

# 3. Adicione as variáveis de banco ao .env
echo "DB_ROOT_PASSWORD=sua-senha-root" >> .env
echo "DB_USER=mysql" >> .env
echo "DB_PASSWORD=sua-senha-db" >> .env
echo "HOST_PORT=8520" >> .env

# 4. Suba os containers
docker compose up -d --build

# 5. Verifique os logs
docker compose logs -f app
```

## Configuração

Copie `.env.example` para `.env` e preencha:

| Variável | Descrição |
|----------|-----------|
| `INSTANCE_ID` | Identificador único da instância (ex: `minhaloja`) |
| `SITE_URL` | URL pública do chatbot |
| `LOGIN_USER` / `LOGIN_PASSWORD` | Credenciais do painel web |
| `SECRET_KEY` | Chave secreta JWT (gere com `openssl rand -hex 32`) |
| `SHOPIFY_STORE_URL` | Domínio `.myshopify.com` da loja |
| `SHOPIFY_ACCESS_TOKEN` | Token de acesso privado Shopify |
| `OPENROUTER_API_KEY` | Chave da API OpenRouter |
| `LLM_MODEL_PREFERENCE` | Modelo de IA (ex: `openai/gpt-4o-mini`) |

## Estrutura do Projeto

```
shopify-chatbot/
├── main.py                  # Entrypoint FastAPI
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── llm_config.yaml          # Configurações do LLM
├── src/
│   ├── api/                 # Endpoints REST
│   ├── core/                # Lógica principal
│   │   ├── config.py        # Settings (Pydantic)
│   │   ├── llm.py           # Integração OpenRouter
│   │   ├── shopify.py       # Integração Shopify
│   │   ├── evolution.py     # Integração Evolution API
│   │   ├── automation_engine.py
│   │   └── ...
│   └── utils/               # Utilitários
├── static/                  # Frontend (HTML/CSS/JS)
│   ├── index.html
│   ├── css/
│   └── js/
└── data/                    # Arquivos de áudio e dados temporários
```

## Acesso ao Painel

Após subir, acesse `http://localhost:PORT` (ou seu domínio) e faça login com as credenciais definidas em `LOGIN_USER` / `LOGIN_PASSWORD`.

A documentação da API estará disponível em `/api/docs`.

## Proxy Reverso (OpenLiteSpeed / Nginx)

Configure um virtual host apontando para `http://127.0.0.1:HOST_PORT`. Exemplo Nginx:

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

## Múltiplas Instâncias

Para rodar o chatbot para diferentes lojas no mesmo servidor, clone o projeto em diretórios separados com `INSTANCE_ID` e `HOST_PORT` distintos em cada `.env`.

## Licença

MIT
