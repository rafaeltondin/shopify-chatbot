// static/js/pages/productContext.js
import { getProductContext, setProductContext } from '../api.js';
import { showFeedback, clearFeedback, setLoadingState } from '../utils.js';

export async function loadProductContextPage(container) {
    console.log('productContext.js: Carregando página de Contexto do Produto...');
    container.innerHTML = `
        <header class="page-header">
            <h1 class="page-title"><i data-feather="book-open" class="feather-title"></i> Contexto do Produto</h1>
            <p class="page-description">Forneça informações detalhadas sobre seu produto ou serviço para o Agente de IA.</p>
        </header>

        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="file-text" class="feather-title-sm"></i> Descrição do Produto</h3>
            </div>
            <div class="card-body">
                <form id="product-context-form" class="form">
                    <div class="form-group">
                        <label for="product-context-textarea" class="label">Contexto (Texto Livre):</label>
                        <textarea id="product-context-textarea" class="textarea product-context-textarea" rows="10" placeholder="Descreva seu produto, seus benefícios, diferenciais, público-alvo, etc."></textarea>
                        <p class="form-text">Este texto será usado pelo Agente de IA para entender e responder sobre seu produto. Opcional se usar DB externo.</p>
                    </div>

                    <div class="form-group">
                        <label for="db-url-input" class="label">URL do Banco de Dados (Opcional):</label>
                        <input type="text" id="db-url-input" class="input" placeholder="Ex: sqlite:///./data/my_products.db ou mysql+mysqlconnector://user:pass@host/db">
                        <p class="form-text">URL de conexão para um banco de dados externo. Deixe em branco para usar apenas o contexto de texto livre.</p>
                    </div>

                    <div class="form-group">
                        <label for="sql-query-textarea" class="label">Query SQL (Opcional):</label>
                        <textarea id="sql-query-textarea" class="textarea" rows="5" placeholder="Ex: SELECT * FROM products WHERE category = 'automotive'"></textarea>
                        <p class="form-text">A query SQL a ser executada no banco de dados especificado. Obrigatório se a URL do DB for fornecida.</p>
                    </div>
                    
                    <div id="product-context-feedback" class="feedback-message"></div>
                    <button type="submit" class="btn btn-primary">
                        <i data-feather="save"></i> Salvar Contexto
                    </button>
                </form>
            </div>
        </div>

        <div class="card mt-4" id="db-data-preview-card" style="display:none;">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="database" class="feather-title-sm"></i> Prévia dos Dados do Banco de Dados</h3>
            </div>
            <div class="card-body">
                <div id="db-data-preview" class="table-responsive">
                    <!-- Dados do DB serão carregados aqui -->
                </div>
            </div>
        </div>
    `;

    // Event Listeners
    document.getElementById('product-context-form').addEventListener('submit', handleProductContextSubmit);

    // Initial load
    await fetchProductContext();

    // Initialize Feather icons
    if (typeof feather !== 'undefined') {
        feather.replace();
    }

    console.log('productContext.js: Página de Contexto do Produto carregada.');
}

async function fetchProductContext() {
    console.log('productContext.js: Buscando contexto do produto...');
    const feedbackContainer = document.getElementById('product-context-feedback');
    clearFeedback(feedbackContainer);

    try {
        const config = await getProductContext();
        document.getElementById('product-context-textarea').value = config.context || '';
        document.getElementById('db-url-input').value = config.db_url || '';
        document.getElementById('sql-query-textarea').value = config.sql_query || '';

        if (config.db_data && config.db_data.length > 0) {
            displayDbDataPreview(config.db_data);
        } else {
            document.getElementById('db-data-preview-card').style.display = 'none';
        }
        console.log('productContext.js: Contexto do produto carregado.');
    } catch (error) {
        console.error('productContext.js: Erro ao buscar contexto do produto:', error);
        showFeedback(feedbackContainer, error.message || 'Erro ao carregar contexto do produto.', 'error');
    }
}

async function handleProductContextSubmit(event) {
    event.preventDefault();
    console.log('productContext.js: Formulário de contexto do produto submetido.');
    const feedbackContainer = document.getElementById('product-context-feedback');
    const submitBtn = event.currentTarget.querySelector('button[type="submit"]');
    setLoadingState(submitBtn, true);
    clearFeedback(feedbackContainer);

    const context = document.getElementById('product-context-textarea').value;
    const dbUrl = document.getElementById('db-url-input').value;
    const sqlQuery = document.getElementById('sql-query-textarea').value;

    // Validação básica
    if (dbUrl && !sqlQuery) {
        showFeedback(feedbackContainer, 'A Query SQL é obrigatória se a URL do Banco de Dados for fornecida.', 'error');
        setLoadingState(submitBtn, false);
        return;
    }
    if (!context && !dbUrl) {
        showFeedback(feedbackContainer, 'Forneça um Contexto de Texto ou uma URL de Banco de Dados com uma Query SQL.', 'error');
        setLoadingState(submitBtn, false);
        return;
    }

    const payload = {
        context: context,
        db_url: dbUrl,
        sql_query: sqlQuery
    };

    try {
        const response = await setProductContext(payload); // Envia o objeto completo
        
        // Recarregar os dados ANTES de mostrar a mensagem de sucesso final.
        await fetchProductContext();
        
        // Mostrar feedback de sucesso APÓS o fetch ter sido concluído.
        const finalSuccessMessage = response.message || 'Contexto salvo e dados atualizados!';
        showFeedback(feedbackContainer, finalSuccessMessage, 'success');
        console.log('productContext.js: Contexto do produto salvo e dados recarregados. Resposta do save:', response, 'Mensagem exibida:', finalSuccessMessage);

    } catch (error) {
        // Este catch agora lida com erros de setProductContext OU fetchProductContext.
        console.error('productContext.js: Erro durante o salvamento ou carregamento do contexto do produto:', error);
        showFeedback(feedbackContainer, error.message || 'Erro ao processar o contexto do produto.', 'error');
    } finally {
        setLoadingState(submitBtn, false);
    }
}

function displayDbDataPreview(data) {
    const previewCard = document.getElementById('db-data-preview-card');
    const previewContainer = document.getElementById('db-data-preview');
    previewContainer.innerHTML = ''; // Limpa conteúdo anterior

    if (!data || data.length === 0) {
        previewCard.style.display = 'none';
        return;
    }

    previewCard.style.display = 'block';

    // Cria a tabela
    const table = document.createElement('table');
    table.classList.add('table', 'table-striped', 'table-bordered');

    // Cabeçalho da tabela
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    // Assume que todas as linhas têm as mesmas chaves para o cabeçalho
    const headers = Object.keys(data[0]);
    headers.forEach(headerText => {
        const th = document.createElement('th');
        th.textContent = headerText;
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Corpo da tabela
    const tbody = document.createElement('tbody');
    data.forEach(rowData => {
        const tr = document.createElement('tr');
        headers.forEach(header => { // Itera pelos cabeçalhos para garantir a ordem
            const td = document.createElement('td');
            td.textContent = String(rowData[header] == null ? '' : rowData[header]);
            // Adiciona uma classe para permitir o controle de estilo via CSS
            td.classList.add('table-cell-wrap');
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    // Adiciona barra de rolagem horizontal se necessário
    previewContainer.style.overflowX = 'auto';
    previewContainer.appendChild(table);
}
