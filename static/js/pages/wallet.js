// static/js/pages/wallet.js
import { getWalletBalance, getWalletHistory, initiateAddCredit } from '../api.js';
import { showFeedback, clearFeedback, setLoadingState, formatTimestamp, createElement, formatJidToDisplay, getTransactionTypeName, getTransactionStatusName } from '../utils.js'; // Adicionado getTransactionTypeName, getTransactionStatusName

export async function loadWalletPage(container) {
    console.log('wallet.js: Carregando página da Carteira...');
    container.innerHTML = `
        <div class="animate-fade-in">
        <header class="page-header">
            <h1 class="page-title">
                <span class="icon-wrapper">
                    <i data-feather="credit-card"></i>
                </span>
                Minha Carteira
            </h1>
            <p class="page-subtitle">Gerencie seus créditos, adicione fundos e veja seu histórico de transações.</p>
        </header>

        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i data-feather="dollar-sign"></i>
                    Saldo Atual
                </h3>
            </div>
            <div class="card-body">
                <div class="wallet-balance-display" id="wallet-balance-display">
                    <div class="spinner"></div>
                    <span>Carregando...</span>
                </div>
                <p class="form-text">Seu saldo é usado para cobrir os custos de utilização dos modelos de linguagem (LLM) e outras funcionalidades pagas do sistema.</p>
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i data-feather="plus-circle"></i>
                    Adicionar Créditos
                </h3>
            </div>
            <div class="card-body">
                <form id="add-credits-form" class="form">
                    <div class="form-group">
                        <label for="credit-amount" class="label">
                            <i data-feather="dollar-sign"></i>
                            Valor da Recarga (BRL)
                        </label>
                        <input type="number" id="credit-amount" class="input" min="10.00" step="0.01" placeholder="Ex: 50.00" required>
                        <p class="form-text">Valor mínimo de recarga: R$ 10,00.</p>
                    </div>
                    <div id="add-credits-feedback"></div>
                    <button type="submit" class="btn btn-primary">
                        <i data-feather="arrow-right-circle"></i>
                        <span>Prosseguir para Pagamento</span>
                    </button>
                </form>
                <div id="payment-area" class="payment-area">
                    <!-- QR Code PIX ou feedback do Mercado Pago será exibido aqui -->
                </div>
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i data-feather="list"></i>
                    Histórico de Transações
                </h3>
            </div>
            <div class="card-body">
                <div id="wallet-history-container" class="table-container">
                    <div class="loading-wrapper">
                        <div class="spinner"></div>
                    </div>
                </div>
                <div id="wallet-history-pagination" class="pagination-controls hidden">
                    <!-- Controles de paginação serão adicionados aqui -->
                </div>
            </div>
        </div>
        </div>
    `;
    console.log('wallet.js: HTML da página da Carteira renderizado.');

    document.getElementById('add-credits-form').addEventListener('submit', handleAddCreditsSubmit);
    
    await fetchWalletData(); // Carrega saldo e histórico
    checkMercadoPagoStatus(); // Verifica se há status de pagamento do MP na URL

    if (typeof feather !== 'undefined') {
        feather.replace();
    }
    console.log('wallet.js: Página da Carteira carregada e listeners configurados.');
}

async function fetchWalletData() {
    await fetchWalletBalance();
    await fetchWalletHistory();
}

async function fetchWalletBalance() {
    console.log('wallet.js: Buscando saldo da carteira...');
    const balanceDisplay = document.getElementById('wallet-balance-display');
    try {
        const response = await getWalletBalance();
        balanceDisplay.textContent = `R$ ${parseFloat(response.balance).toFixed(2).replace('.', ',')}`;
        console.log('wallet.js: Saldo da carteira carregado:', response.balance);
    } catch (error) {
        console.error('wallet.js: Erro ao buscar saldo da carteira:', error);
        balanceDisplay.textContent = 'Erro ao carregar saldo.';
        balanceDisplay.classList.add('error-message');
    }
}

async function fetchWalletHistory(offset = 0, limit = 10) {
    console.log(`wallet.js: Buscando histórico da carteira (offset: ${offset}, limit: ${limit})...`);
    const historyContainer = document.getElementById('wallet-history-container');
    const paginationContainer = document.getElementById('wallet-history-pagination');
    historyContainer.innerHTML = `<div class="spinner-container"><div class="loading-spinner"></div></div>`;
    paginationContainer.style.display = 'none';

    try {
        const response = await getWalletHistory({ limit, offset });
        console.log('wallet.js: Histórico da carteira recebido:', response);
        historyContainer.innerHTML = ''; // Limpa o spinner

        if (response.transactions && response.transactions.length > 0) {
            const table = createElement('table', { className: 'table' });
            const thead = createElement('thead', {}, createElement('tr', {}, [
                createElement('th', {}, 'Data'),
                createElement('th', {}, 'Tipo'),
                createElement('th', {}, 'Descrição'),
                createElement('th', {style: 'text-align: right;'}, 'Valor (R$)'),
                createElement('th', {}, 'Status'),
                createElement('th', {}, 'ID Externo')
            ]));
            table.appendChild(thead);

            const tbody = createElement('tbody');
            response.transactions.forEach(tx => {
                const metadataInfo = tx.metadata ? JSON.stringify(tx.metadata) : '';
                const descriptionText = tx.description || (tx.type === 'bonus' ? `Bônus (${metadataInfo})` : 'N/A');
                
                let amountClass = '';
                if (tx.type === 'credit' || tx.type === 'bonus' || tx.type === 'initial') {
                    amountClass = 'text-success';
                } else if (tx.type === 'debit') {
                    amountClass = 'text-error';
                }

                tbody.appendChild(createElement('tr', {}, [
                    createElement('td', {}, formatTimestamp(tx.created_at)),
                    createElement('td', {}, getTransactionTypeName(tx.type)), // Traduzido
                    createElement('td', {}, descriptionText),
                    createElement('td', { className: amountClass, style: 'text-align: right; font-weight: bold;' }, parseFloat(tx.amount_brl).toFixed(2).replace('.', ',')),
                    createElement('td', {}, getTransactionStatusName(tx.status)), // Traduzido
                    createElement('td', {}, tx.transaction_id_provider || 'N/A')
                ]));
            });
            table.appendChild(tbody);
            historyContainer.appendChild(table);

            renderPagination(response.total_count, limit, offset, paginationContainer, fetchWalletHistory);
            paginationContainer.style.display = 'flex';
        } else {
            historyContainer.innerHTML = '<p class="text-center">Nenhuma transação encontrada.</p>';
        }
        console.log('wallet.js: Histórico da carteira renderizado.');
    } catch (error) {
        console.error('wallet.js: Erro ao buscar histórico da carteira:', error);
        historyContainer.innerHTML = `<div class="error-message">Erro ao carregar histórico.</div>`;
    }
}

function renderPagination(totalItems, limit, currentOffset, container, fetchFunction) {
    container.innerHTML = '';
    const totalPages = Math.ceil(totalItems / limit);
    const currentPage = Math.floor(currentOffset / limit) + 1;

    if (totalPages <= 1) return;

    const paginationInfo = createElement('div', { className: 'pagination-info' }, 
        `Página ${currentPage} de ${totalPages} (Total: ${totalItems})`
    );
    container.appendChild(paginationInfo);

    const linksContainer = createElement('div', { className: 'pagination-links' });

    // Botão Anterior
    const prevBtn = createElement('button', {
        className: 'btn btn-secondary',
        disabled: currentPage === 1
    }, 'Anterior');
    prevBtn.addEventListener('click', () => fetchFunction(Math.max(0, currentOffset - limit), limit));
    linksContainer.appendChild(prevBtn);

    // Botão Próximo
    const nextBtn = createElement('button', {
        className: 'btn btn-secondary',
        disabled: currentPage === totalPages
    }, 'Próximo');
    nextBtn.addEventListener('click', () => fetchFunction(currentOffset + limit, limit));
    linksContainer.appendChild(nextBtn);
    
    container.appendChild(linksContainer);
}


async function handleAddCreditsSubmit(event) {
    event.preventDefault();
    console.log('wallet.js: Formulário de adicionar créditos submetido.');
    const feedbackContainer = document.getElementById('add-credits-feedback');
    const paymentArea = document.getElementById('payment-area');
    const submitBtn = event.currentTarget.querySelector('button[type="submit"]');
    
    setLoadingState(submitBtn, true);
    clearFeedback(feedbackContainer);
    paymentArea.innerHTML = ''; // Limpa área de pagamento

    const amount = document.getElementById('credit-amount').value;
    if (parseFloat(amount) < 10.00) {
        showFeedback(feedbackContainer, 'O valor mínimo para recarga é R$ 10,00.', 'error');
        setLoadingState(submitBtn, false);
        return;
    }

    try {
        const response = await initiateAddCredit(parseFloat(amount));
        console.log('wallet.js: Resposta da iniciação de pagamento:', response);
        if (response.success && response.data && response.data.init_point) {
            showFeedback(feedbackContainer, 'Você será redirecionado para o Mercado Pago para concluir o pagamento.', 'info');
            // Adicionar um pequeno delay antes de redirecionar para o usuário ler a mensagem
            setTimeout(() => {
                window.location.href = response.data.init_point;
            }, 2000);
        } else {
            throw new Error(response.message || 'Falha ao iniciar o pagamento.');
        }
    } catch (error) {
        console.error('wallet.js: Erro ao iniciar adição de créditos:', error);
        showFeedback(feedbackContainer, error.message || 'Erro ao iniciar processo de pagamento.', 'error');
        setLoadingState(submitBtn, false);
    }
    // O setLoadingState(submitBtn, false) será chamado no finally do redirect ou no catch.
    // Se houver redirect, o estado do botão não importa mais naquela página.
}

function checkMercadoPagoStatus() {
    const urlParams = new URLSearchParams(window.location.search);
    const mpStatus = urlParams.get('mp_status');
    const externalRef = urlParams.get('ext_ref'); // Para rastreamento futuro, se necessário
    const feedbackContainer = document.getElementById('add-credits-feedback'); // Usar o feedback da seção de adicionar créditos

    if (mpStatus && feedbackContainer) {
        let message = '';
        let type = 'info';

        if (mpStatus === 'approved') {
            message = 'Pagamento aprovado! Seus créditos serão adicionados em breve.';
            type = 'success';
            fetchWalletBalance(); // Atualiza o saldo imediatamente
            fetchWalletHistory(); // Atualiza o histórico
        } else if (mpStatus === 'pending') {
            message = 'Seu pagamento está pendente. Aguarde a confirmação.';
            type = 'warning';
        } else if (mpStatus === 'failure' || mpStatus === 'rejected') {
            message = 'Seu pagamento foi recusado. Por favor, tente novamente ou use outro método.';
            type = 'error';
        }
        
        if (message) {
            showFeedback(feedbackContainer, message, type);
        }

        // Limpar parâmetros da URL para não mostrar a mensagem novamente no refresh
        if (window.history.replaceState) {
            const cleanURL = window.location.protocol + "//" + window.location.host + window.location.pathname + window.location.hash.split('?')[0];
            window.history.replaceState({path:cleanURL},'',cleanURL);
        }
    }
}
