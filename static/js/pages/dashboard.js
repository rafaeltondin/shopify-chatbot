// static/js/pages/dashboard.js
import { getDashboardStats, getDashboardFunnel, getQueueStatus, pauseQueue, resumeQueue, clearAllHistory, getWalletBalance, getAiQueueOnlyStatus, toggleAiQueueOnly, getProspectsList, getDashboardAnalytics, getProspectProfilePicture, getSalesFlowConfig, toggleProspectLLMPause, getProspectHistory, getTagDefinitions, getFunnelsList, getFunnel } from '../api.js';
import { showFeedback, clearFeedback, setLoadingState, formatTimestamp, formatJidToDisplay, createElement, getStatusName, showToast, showModal, hideModal } from '../utils.js';

const INITIAL_ITEMS_PER_COLUMN = 10;
const ITEMS_PER_LOAD_MORE = 10;
let kanbanColumnState = {}; // Ex: { 1: { offset: 0, totalKnown: 0, isLoading: false, allLoaded: false }, ... }

// KANBAN_COLUMN_IDS será populado dinamicamente baseado no Sales Flow
let KANBAN_COLUMN_IDS = [];

// Mapa de stage_number para nome do estágio (objetivo do funil)
let salesFlowStagesMap = {};

// Cache de fotos de perfil para evitar requisições repetidas
const profilePictureCache = new Map();

// Cache de definições de tags para exibir cores corretas
let tagDefinitionsCache = {};

// Lista de funis disponíveis para o seletor
let availableFunnels = [];

// Funil atualmente selecionado no Kanban
let currentKanbanFunnelId = null;

// Busca foto de perfil do WhatsApp e atualiza o avatar
async function fetchProfilePicture(jid, avatarElement) {
    // Verificar cache primeiro
    if (profilePictureCache.has(jid)) {
        const cachedUrl = profilePictureCache.get(jid);
        if (cachedUrl) {
            applyProfilePicture(avatarElement, cachedUrl);
        }
        return;
    }

    try {
        const response = await getProspectProfilePicture(jid);
        const profileUrl = response?.data?.profile_picture_url;

        // Cachear resultado (mesmo se null)
        profilePictureCache.set(jid, profileUrl || null);

        if (profileUrl) {
            applyProfilePicture(avatarElement, profileUrl);
        }
    } catch (error) {
        console.debug(`dashboard.js: Erro ao buscar foto de perfil para ${jid}:`, error);
        profilePictureCache.set(jid, null);
    }
}

// Aplica a foto de perfil ao elemento avatar
function applyProfilePicture(avatarElement, imageUrl) {
    if (!avatarElement || !imageUrl) return;

    const img = document.createElement('img');
    img.src = imageUrl;
    img.alt = 'Foto de perfil';
    img.className = 'kanban-card-avatar-img';

    img.onload = () => {
        avatarElement.classList.add('has-photo');
        avatarElement.appendChild(img);
    };

    img.onerror = () => {
        console.debug('dashboard.js: Falha ao carregar imagem de perfil');
    };
} 

// Função auxiliar para obter o nome da coluna baseado no Sales Flow dinâmico
function getKanbanColumnName(columnId) {
    if (columnId === 'scheduled') {
        return 'Agendamentos';
    }
    // Usa o mapa do Sales Flow para obter o nome do estágio
    const stageInfo = salesFlowStagesMap[columnId];
    if (stageInfo) {
        return stageInfo.name;
    }
    // Fallback para estágios não mapeados
    return `Estágio ${columnId}`;
}

// Função auxiliar para obter o nome do estágio (usado em analytics)
function getStageName(stageNumber) {
    const stageInfo = salesFlowStagesMap[stageNumber];
    if (stageInfo) {
        return stageInfo.name;
    }
    return `Estágio ${stageNumber}`;
}

// Carrega as etapas do funil de vendas e configura as colunas do Kanban
async function loadSalesFlowStages() {
    console.log('dashboard.js: Carregando etapas do funil de vendas...');
    try {
        const config = await getSalesFlowConfig();
        const stages = config.stages || [];

        // Limpa e reconstrói o mapa de estágios
        salesFlowStagesMap = {};
        KANBAN_COLUMN_IDS = [];

        // Ordena os estágios por stage_number
        stages.sort((a, b) => a.stage_number - b.stage_number);

        // Popula o mapa e os IDs das colunas
        stages.forEach(stage => {
            const stageNumber = stage.stage_number;
            salesFlowStagesMap[stageNumber] = {
                name: stage.objective || `Estágio ${stageNumber}`,
                trigger: stage.trigger_description || ''
            };
            KANBAN_COLUMN_IDS.push(stageNumber);
        });

        // Sempre adiciona a coluna de Agendamentos no final
        KANBAN_COLUMN_IDS.push('scheduled');

        console.log('dashboard.js: Etapas do funil carregadas:', salesFlowStagesMap);
        console.log('dashboard.js: IDs das colunas Kanban:', KANBAN_COLUMN_IDS);

        return { stages, columnIds: KANBAN_COLUMN_IDS };
    } catch (error) {
        console.error('dashboard.js: Erro ao carregar etapas do funil. Usando configuração padrão.', error);
        // Fallback para configuração padrão caso não haja funil configurado
        salesFlowStagesMap = {
            1: { name: 'Novo', trigger: '' },
            2: { name: 'Qualificação', trigger: '' },
            3: { name: 'Proposta', trigger: '' },
            4: { name: 'Negociação', trigger: '' },
            5: { name: 'Fechamento', trigger: '' }
        };
        KANBAN_COLUMN_IDS = [1, 2, 3, 4, 5, 'scheduled'];
        return { stages: [], columnIds: KANBAN_COLUMN_IDS };
    }
}

// Carrega as definições de tags para exibir com cores corretas
async function loadTagDefinitions() {
    console.log('dashboard.js: Carregando definições de tags...');
    try {
        const response = await getTagDefinitions();
        const definitions = response.definitions || [];
        // Criar cache com nome da tag como chave
        tagDefinitionsCache = {};
        definitions.forEach(def => {
            tagDefinitionsCache[def.name.toLowerCase()] = {
                color: def.color || '#3B82F6',
                description: def.description || ''
            };
        });
        console.log('dashboard.js: Definições de tags carregadas:', Object.keys(tagDefinitionsCache).length);
    } catch (error) {
        console.error('dashboard.js: Erro ao carregar definições de tags:', error);
        tagDefinitionsCache = {};
    }
}

// Obtém a cor de uma tag baseado no cache de definições
function getTagColor(tagName) {
    const normalizedName = tagName.toLowerCase();
    if (tagDefinitionsCache[normalizedName]) {
        return tagDefinitionsCache[normalizedName].color;
    }
    // Cor padrão se não encontrar definição
    return '#6B7280';
}

// Gera o HTML das colunas do Kanban dinamicamente
function generateKanbanColumnsHtml() {
    return KANBAN_COLUMN_IDS.map(columnId => `
        <div class="kanban-column" data-column-id="${columnId}">
            <div class="kanban-column-header">
                <h4 class="kanban-column-title">${getKanbanColumnName(columnId)}</h4>
                <span class="kanban-column-count" id="column-count-${columnId}">0</span>
            </div>
            <div class="kanban-cards" id="kanban-cards-${columnId}">
                <div class="spinner-container"><div class="loading-spinner"></div></div>
            </div>
            <button class="btn btn-ghost w-full mt-3 load-more-btn" id="load-more-${columnId}" style="display: none;">Carregar Mais</button>
        </div>
    `).join('');
}


function calculateAndFormatPercentage(stage, total_in_funnel) {
    if (stage.percentage_of_total !== undefined && stage.percentage_of_total !== null && !isNaN(parseFloat(stage.percentage_of_total))) {
        return parseFloat(stage.percentage_of_total).toFixed(1);
    }
    if (total_in_funnel > 0 && stage.count !== undefined && stage.count !== null) {
        const percentage = (stage.count / total_in_funnel) * 100;
        return percentage.toFixed(1);
    }
    return 'N/A';
}

export async function loadDashboardPage(container) {
    console.log('dashboard.js: Carregando página do Dashboard...');

    // Carrega as etapas do funil de vendas e definições de tags dinamicamente antes de renderizar
    await Promise.all([
        loadSalesFlowStages(),
        loadTagDefinitions()
    ]);

    let aiQueueOnlyStatus = false;
    try {
        const response = await getAiQueueOnlyStatus();
        aiQueueOnlyStatus = response.data.enabled;
    } catch (e) {
        console.error("dashboard.js: Erro ao buscar status inicial de AI para fila:", e);
    }

    // --- Helper function to create modern KPI cards ---
    const createKpiCard = (id, icon, label, initialValue = '<div class="spinner"></div>', isHidden = false) => {
        return `
        <div class="kpi-card" id="${id}-card" ${isHidden ? 'style="display: none;"' : ''}>
            <div class="kpi-card-header">
                <div class="kpi-card-icon-wrapper">
                    <i data-feather="${icon}"></i>
                </div>
                <span class="kpi-card-label" id="label-${id}">${label}</span>
            </div>
            <div class="kpi-card-body">
                <div class="kpi-card-value" id="${id}-kpi">${initialValue}</div>
            </div>
        </div>
    `;
    }

    container.innerHTML = /*html*/`
        <div class="animate-fade-in">
            <header class="page-header">
                <h1 class="page-title">
                    <span class="icon-wrapper">
                        <i data-feather="home"></i>
                    </span>
                    Dashboard
                </h1>
                <p class="page-subtitle">Visão geral e estatísticas do seu fluxo de prospecção</p>
            </header>

            <!-- Kanban Board (PRIMEIRA SEÇÃO) -->
            <div class="card kanban-section">
                <div class="card-header">
                    <h3 class="card-title">
                        <i data-feather="columns"></i>
                        Funil de Vendas
                    </h3>
                    <div class="card-header-actions">
                        <div class="funnel-selector-wrapper">
                            <label for="kanban-funnel-select" class="funnel-selector-label">
                                <i data-feather="git-branch"></i>
                            </label>
                            <select id="kanban-funnel-select" class="select select-sm funnel-selector">
                                <option value="">Carregando funis...</option>
                            </select>
                        </div>
                    </div>
                </div>
                <div class="card-body kanban-body">
                    <div id="kanban-board" class="kanban-board">
                        ${generateKanbanColumnsHtml()}
                    </div>
                </div>
            </div>

            <!-- Advanced Analytics (SEGUNDA SEÇÃO) -->
            <div class="card analytics-section">
                <div class="card-header">
                    <h3 class="card-title">
                        <i data-feather="bar-chart-2"></i>
                        Análise Avançada do Funil
                    </h3>
                </div>
                <div class="card-body">
                    <div id="advanced-analytics-container">
                        <div class="loading-wrapper loading-wrapper-lg">
                            <div class="spinner spinner-lg"></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- KPIs Grid -->
            <div class="kpi-grid">
                ${createKpiCard('total-prospects', 'users', 'Total Geral de Prospects')}
                ${createKpiCard('active-prospects', 'user-check', 'Prospects Ativos')}
                ${createKpiCard('messages-sent', 'message-square', 'Mensagens Enviadas')}
                ${createKpiCard('wallet-balance', 'dollar-sign', 'Saldo da Carteira')}
                ${createKpiCard('llm-prompt-tokens', 'cpu', 'Tokens LLM')}
                ${createKpiCard('avg-interactions', 'repeat', 'Média de Interações')}
                ${createKpiCard('total-prospects-user-initiated', 'user-plus', 'Total Usuários', '<div class="spinner"></div>', true)}
                ${createKpiCard('active-prospects-user-initiated', 'user-minus', 'Usuários Ativos', '<div class="spinner"></div>', true)}
            </div>

            <!-- Controls Section -->
            <div class="controls-grid">
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">
                            <i data-feather="settings"></i>
                            Controles Gerais
                        </h3>
                    </div>
                    <div class="card-body">
                        <div class="form-group">
                            <label for="initiator-filter" class="label">
                                <i data-feather="filter"></i>
                                Filtrar por Iniciador
                            </label>
                            <select id="initiator-filter" class="select">
                                <option value="all">Todos</option>
                                <option value="user">Usuário</option>
                                <option value="llm_agent">Agente LLM</option>
                            </select>
                        </div>

                        <div class="form-group">
                            <label class="label">
                                <i data-feather="zap"></i>
                                Controle de IA
                            </label>
                            <div class="toggle-group">
                                <label class="toggle-switch">
                                    <input type="checkbox" id="toggle-ai-queue-only" ${aiQueueOnlyStatus ? 'checked' : ''}>
                                    <span class="toggle-slider"></span>
                                </label>
                                <span class="toggle-label">Ativar IA SOMENTE para leads da fila</span>
                            </div>
                            <p class="form-text">
                                Quando ativado, a IA responderá apenas leads da fila de prospecção.
                            </p>
                            <div id="ai-queue-only-feedback"></div>
                        </div>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">
                            <i data-feather="play-circle"></i>
                            Controle da Fila
                        </h3>
                    </div>
                    <div class="card-body">
                        <div id="queue-status-display" class="queue-status-display">
                            <div class="loading-wrapper">
                                <div class="spinner"></div>
                            </div>
                        </div>
                        <div class="btn-group">
                            <button id="pause-queue-btn" class="btn btn-secondary">
                                <i data-feather="pause"></i>
                                Pausar
                            </button>
                            <button id="resume-queue-btn" class="btn btn-primary">
                                <i data-feather="play"></i>
                                Retomar
                            </button>
                            <button id="export-queue-btn" class="btn btn-outline">
                                <i data-feather="download"></i>
                                Exportar
                            </button>
                        </div>
                        <div id="queue-feedback"></div>
                    </div>
                </div>
            </div>

            <!-- Funis Configurados -->
            <div class="card funnels-overview-section">
                <div class="card-header">
                    <h3 class="card-title">
                        <i data-feather="git-branch"></i>
                        Funis Configurados
                    </h3>
                    <div class="card-header-actions">
                        <a href="#sales-flow" class="btn btn-ghost btn-sm">
                            <i data-feather="settings"></i>
                            Gerenciar
                        </a>
                    </div>
                </div>
                <div class="card-body">
                    <div id="funnels-overview-container">
                        <div class="loading-wrapper">
                            <div class="spinner"></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Danger Zone -->
            <div class="card card-danger">
                <div class="card-header">
                    <h3 class="card-title danger-title">
                        <i data-feather="alert-triangle"></i>
                        Zona de Perigo
                    </h3>
                </div>
                <div class="card-body">
                    <p class="danger-description">
                        Esta ação removerá permanentemente todos os dados de leads, conversas e histórico do Redis.
                    </p>
                    <button id="clear-history-btn" class="btn btn-danger">
                        <i data-feather="trash-2"></i>
                        Limpar Histórico Completo
                    </button>
                    <div id="clear-history-feedback"></div>
                </div>
            </div>
        </div>
    `;
    console.log('dashboard.js: HTML do Dashboard reestruturado e renderizado.');

    // Carregar funis disponíveis para o seletor do Kanban PRIMEIRO
    await loadKanbanFunnelSelector();

    // CORREÇÃO: Carregar estágios do funil selecionado ANTES de carregar dados do kanban
    // Isso garante que KANBAN_COLUMN_IDS esteja populado corretamente com os estágios do funil correto
    if (currentKanbanFunnelId) {
        console.log(`dashboard.js: Carregando estágios do funil padrão: ${currentKanbanFunnelId}`);
        await loadSalesFlowStagesForFunnel(currentKanbanFunnelId);

        // Regenerar o HTML do Kanban com os estágios corretos do funil selecionado
        const kanbanBoard = document.getElementById('kanban-board');
        if (kanbanBoard) {
            console.log('dashboard.js: Regenerando HTML do Kanban com estágios do funil selecionado');
            kanbanBoard.innerHTML = generateKanbanColumnsHtml();
        }
    }

    // Carregar dados
    await fetchDashboardData();
    await fetchQueueStatus();
    await loadInitialKanbanData();
    await fetchAdvancedAnalytics();
    await fetchFunnelsOverview();
    console.log('dashboard.js: Dados iniciais do dashboard e fila carregados.');

    // Adicionar listener para o seletor de funil do Kanban
    const kanbanFunnelSelect = document.getElementById('kanban-funnel-select');
    if (kanbanFunnelSelect) {
        kanbanFunnelSelect.addEventListener('change', handleKanbanFunnelChange);
        console.log('dashboard.js: Event listener para "kanban-funnel-select" adicionado.');
    }

    // Adicionar listeners para os botões da fila
    document.getElementById('pause-queue-btn').addEventListener('click', handlePauseQueue);
    console.log('dashboard.js: Event listener para "pause-queue-btn" adicionado.');
    document.getElementById('resume-queue-btn').addEventListener('click', handleResumeQueue);
    console.log('dashboard.js: Event listener para "resume-queue-btn" adicionado.');
    document.getElementById('export-queue-btn').addEventListener('click', handleExportQueue); // Novo listener
    console.log('dashboard.js: Event listener para "export-queue-btn" adicionado.');

    // Adicionar listener para o botão de limpar histórico
    document.getElementById('clear-history-btn').addEventListener('click', handleClearHistory);
    console.log('dashboard.js: Event listener para "clear-history-btn" adicionado.');

    // Adicionar listener para o filtro de iniciador
    const initiatorFilter = document.getElementById('initiator-filter');
    initiatorFilter.addEventListener('change', () => {
        fetchDashboardData();
        fetchAdvancedAnalytics();
    });
    console.log('dashboard.js: Event listener para "initiator-filter" adicionado.');

    // Adicionar listener para o novo toggle de IA
    const toggleAiQueueOnlyEl = document.getElementById('toggle-ai-queue-only');
    if (toggleAiQueueOnlyEl) {
        toggleAiQueueOnlyEl.addEventListener('change', handleToggleAiQueueOnly);
        console.log('dashboard.js: Event listener para "toggle-ai-queue-only" adicionado.');
    } else {
        console.error('dashboard.js: Elemento #toggle-ai-queue-only não encontrado.');
    }

    if (typeof feather !== 'undefined') {
        // Re-renderiza todos os ícones dinamicamente adicionados
        // fetchDashboardData e loadDashboardPage já disparam renderização, mas para o toggle, pode ser necessário de novo.
        // Ou garantir que showModal, hideModal e createElement usem replaceFeatherIcons.
        // Para este caso, vamos garantir que o HTML do dashboard já tenha os atributos data-feather.
        // Uma chamada extra aqui não faz mal, mas o ideal é que seja feita após carregar o conteúdo principal.
        // Como o initial HTML é preenchido no começo, e o fetchDashboardData carrega mais elementos,
        // o replace feather lá é mais crítico. Aqui é só para garantir que nada foi perdido.
        feather.replace();
        console.log('dashboard.js: Feather icons re-renderizados para o novo toggle.');
    }


    console.log('dashboard.js: Página do Dashboard carregada e event listeners configurados.');
}

async function fetchDashboardData() {
    console.log('dashboard.js: fetchDashboardData - Buscando dados do dashboard...');
    const initiatorFilterElement = document.getElementById('initiator-filter');
    const selectedInitiator = initiatorFilterElement ? initiatorFilterElement.value : 'all';
    // Se 'all', passamos null para a API, pois ela espera null ou os valores do enum 'user'/'llm_agent'
    const apiInitiatorParam = selectedInitiator === 'all' ? null : selectedInitiator;
    console.log(`dashboard.js: fetchDashboardData - Filtro de iniciador selecionado: ${selectedInitiator}, Parâmetro API: ${apiInitiatorParam}`);

    // Atualizar rótulos dos KPIs
    const labelTotalProspects = document.getElementById('label-total-prospects');
    const labelActiveProspects = document.getElementById('label-active-prospects');
    const userInitiatedTotalCard = document.getElementById('total-prospects-user-initiated-card');
    const userInitiatedActiveCard = document.getElementById('active-prospects-user-initiated-card');

    if (labelTotalProspects && labelActiveProspects) {
        if (selectedInitiator === 'user') {
            labelTotalProspects.textContent = 'Total de Usuários (Iniciaram)';
            labelActiveProspects.textContent = 'Usuários Ativos (Iniciaram)';
            userInitiatedTotalCard.style.display = 'none';
            userInitiatedActiveCard.style.display = 'none';
        } else if (selectedInitiator === 'llm_agent') {
            labelTotalProspects.textContent = 'Total Agente LLM (Iniciou)';
            labelActiveProspects.textContent = 'Ativos Agente LLM (Iniciou)';
            userInitiatedTotalCard.style.display = 'none';
            userInitiatedActiveCard.style.display = 'none';
        } else { // 'all'
            labelTotalProspects.textContent = 'Total Geral de Prospects';
            labelActiveProspects.textContent = 'Prospects Ativos (Geral)';
            userInitiatedTotalCard.style.display = 'flex'; // ou 'block' dependendo do seu CSS de .summary-card
            userInitiatedActiveCard.style.display = 'flex'; // ou 'block'
        }
    }

    try {
        const stats = await getDashboardStats(apiInitiatorParam);
        console.log('dashboard.js: fetchDashboardData - Estatísticas recebidas:', stats);
        document.getElementById('total-prospects-kpi').textContent = stats.total_prospects;
        document.getElementById('active-prospects-kpi').textContent = stats.active_prospects;
        // messages_sent já virá filtrado (ou total) da API
        document.getElementById('messages-sent-kpi').textContent = stats.messages_sent !== null ? stats.messages_sent : 'N/A';
        
        // Preencher KPIs de Tokens LLM e Custo Estimado (já vêm filtrados ou totais da API)
        const promptTokens = stats.total_prompt_tokens || 0;
        document.getElementById('llm-prompt-tokens-kpi').textContent = promptTokens.toLocaleString();

        // Média de Interações
        let avgInteractions = "N/A";
        if (stats.messages_sent !== null && stats.messages_sent > 0) {
            if (stats.active_prospects > 0) {
                avgInteractions = (stats.messages_sent / stats.active_prospects).toFixed(1);
            } else if (stats.total_prospects > 0) { // Se não há ativos, mas há total de prospects
                avgInteractions = (stats.messages_sent / stats.total_prospects).toFixed(1); // Usa total_prospects como denominador
            } else {
                avgInteractions = "0.0"; // Mensagens enviadas, mas sem prospects ativos ou totais (caso estranho)
            }
        } else if (stats.messages_sent === 0) { // Se nenhuma mensagem foi enviada
            avgInteractions = "0.0";
        }
        // Se stats.messages_sent é null, permanece "N/A"
        document.getElementById('avg-interactions-kpi').textContent = avgInteractions;
        
        // Buscar e exibir saldo da carteira
        try {
            const walletBalanceResponse = await getWalletBalance();
            document.getElementById('wallet-balance-kpi').textContent = 
                `R$ ${parseFloat(walletBalanceResponse.balance).toFixed(2).replace('.', ',')}`;
        } catch (error) {
            console.error('dashboard.js: Erro ao buscar saldo da carteira:', error);
            document.getElementById('wallet-balance-kpi').textContent = 'Erro';
        }
        console.log('dashboard.js: fetchDashboardData - Estatísticas do dashboard e saldo da carteira atualizados na UI.');

        // Preencher os cards específicos de "Usuário Iniciou" se o filtro for "all"
        if (selectedInitiator === 'all') {
            document.getElementById('total-prospects-user-initiated-kpi').textContent = stats.total_prospects_user_initiated;
            document.getElementById('active-prospects-user-initiated-kpi').textContent = stats.active_prospects_user_initiated;
        }
        
        if (typeof feather !== 'undefined') {
            feather.replace(); // Ensure icons are rendered for dynamically added elements
            console.log('dashboard.js: fetchDashboardData - Feather icons re-renderizados.');
        }

    } catch (error) {
        console.error('dashboard.js: fetchDashboardData - Erro ao buscar dados do dashboard:', error);
        // Verificar se os elementos ainda existem antes de modificar (página pode ter sido trocada)
        const kpiGrid = document.getElementById('dashboard-kpi-grid');
        const funnelContainer = document.getElementById('funnel-stages-container');
        if (kpiGrid) {
            kpiGrid.innerHTML = `<div class="error-message summary-value error">Erro ao carregar estatísticas.</div>`;
        }
        if (funnelContainer) {
            funnelContainer.innerHTML = `<div class="error-message">Erro ao carregar funil.</div>`;
        }
    }
}

async function fetchAdvancedAnalytics() {
    console.log('dashboard.js: fetchAdvancedAnalytics - Buscando dados de análise avançada...');
    const analyticsContainer = document.getElementById('advanced-analytics-container');
    const initiatorFilterElement = document.getElementById('initiator-filter');
    const selectedInitiator = initiatorFilterElement ? initiatorFilterElement.value : 'all';
    const apiInitiatorParam = selectedInitiator === 'all' ? null : selectedInitiator;

    try {
        const analytics = await getDashboardAnalytics(apiInitiatorParam);
        console.log('dashboard.js: fetchAdvancedAnalytics - Dados recebidos:', analytics);

        // Main container with animations
        const mainContainer = createElement('div', { className: 'analytics-container animate-fade-in' });

        // ========== FUNNEL SUMMARY SECTION ==========
        const funnelSummary = createFunnelSummarySection(analytics);
        mainContainer.appendChild(funnelSummary);

        // ========== MAIN ANALYTICS GRID ==========
        const gridContainer = createElement('div', { className: 'analytics-grid' });

        // Column 1: Conversion Rates with Premium Design
        const conversionCol = createConversionRatesSection(analytics);
        gridContainer.appendChild(conversionCol);

        // Column 2: Average Time in Stage with Premium Design
        const avgTimeCol = createAvgTimeSection(analytics);
        gridContainer.appendChild(avgTimeCol);

        mainContainer.appendChild(gridContainer);

        // ========== INSIGHTS SECTION ==========
        const insightsSection = createInsightsSection(analytics);
        mainContainer.appendChild(insightsSection);

        analyticsContainer.innerHTML = ''; // Clear spinner
        analyticsContainer.appendChild(mainContainer);

        // Apply stagger animations
        applyStaggerAnimations(analyticsContainer);

        if (typeof feather !== 'undefined') {
            feather.replace();
        }

    } catch (error) {
        console.error('dashboard.js: fetchAdvancedAnalytics - Erro ao buscar dados:', error);
        analyticsContainer.innerHTML = `
            <div class="analytics-empty-state">
                <i data-feather="bar-chart-2" class="analytics-empty-icon"></i>
                <h4 class="analytics-empty-title">Erro ao carregar análises</h4>
                <p class="analytics-empty-text">Não foi possível obter os dados de análise. Tente novamente mais tarde.</p>
            </div>
        `;
        if (typeof feather !== 'undefined') {
            feather.replace();
        }
    }
}

// ========== PREMIUM ANALYTICS HELPER FUNCTIONS ==========

function createFunnelSummarySection(analytics) {
    const section = createElement('div', { className: 'stats-grid mb-6' });

    // Calculate summary stats
    const totalConversions = analytics.conversion_rates.reduce((sum, r) => sum + r.to_count, 0);
    const avgConversionRate = analytics.conversion_rates.length > 0
        ? (analytics.conversion_rates.reduce((sum, r) => sum + parseFloat(r.conversion_rate), 0) / analytics.conversion_rates.length).toFixed(1)
        : '0.0';
    const totalStages = analytics.conversion_rates.length;
    const bestConversion = analytics.conversion_rates.length > 0
        ? Math.max(...analytics.conversion_rates.map(r => parseFloat(r.conversion_rate)))
        : 0;

    const stats = [
        { label: 'Taxa Média', value: `${avgConversionRate}%`, icon: 'percent', color: 'primary' },
        { label: 'Total Conversões', value: totalConversions.toLocaleString(), icon: 'users', color: 'secondary' },
        { label: 'Etapas do Funil', value: totalStages, icon: 'git-branch', color: 'accent' },
        { label: 'Melhor Taxa', value: `${bestConversion.toFixed(1)}%`, icon: 'award', color: 'success' }
    ];

    stats.forEach((stat, index) => {
        const statItem = createElement('div', {
            className: `stat-item animate-fade-in-up stagger-${index + 1}`
        }, [
            createElement('div', { className: 'stat-header flex items-center justify-between mb-2' }, [
                createElement('span', { className: 'stat-label' }, stat.label),
                createElement('div', {
                    className: `stat-icon-wrapper`,
                    style: `background: var(--gradient-${stat.color === 'primary' ? 'primary' : stat.color === 'secondary' ? 'secondary' : stat.color === 'accent' ? 'accent' : 'primary'}); width: 32px; height: 32px; border-radius: var(--radius-md); display: flex; align-items: center; justify-content: center;`
                }, [
                    createElement('i', { 'data-feather': stat.icon, style: 'width: 16px; height: 16px; color: var(--black);' })
                ])
            ]),
            createElement('div', { className: 'stat-value gradient-text' }, stat.value)
        ]);
        section.appendChild(statItem);
    });

    return section;
}

function createConversionRatesSection(analytics) {
    const conversionCol = createElement('div', { className: 'analytics-section shine' });

    // Header with icon
    const header = createElement('h4', { className: 'analytics-title' }, [
        createElement('i', { 'data-feather': 'trending-up' }),
        createElement('span', {}, 'Taxas de Conversão'),
        createElement('span', {
            className: 'badge badge-primary ml-auto',
            style: 'margin-left: auto;'
        }, `${analytics.conversion_rates.length} etapas`)
    ]);
    conversionCol.appendChild(header);

    if (analytics.conversion_rates.length > 0) {
        const conversionList = createElement('div', { className: 'analytics-list' });

        analytics.conversion_rates.forEach((rate, index) => {
            const percentage = parseFloat(rate.conversion_rate);
            const chartColor = `chart-${(index % 5) + 1}`;

            // Determine status based on conversion rate
            let statusClass = 'neutral';
            let statusIcon = 'minus';
            if (percentage >= 50) {
                statusClass = 'positive';
                statusIcon = 'trending-up';
            } else if (percentage < 20) {
                statusClass = 'negative';
                statusIcon = 'trending-down';
            }

            const item = createElement('div', {
                className: `analytics-item animate-slide-in-left stagger-${index + 1}`
            }, [
                createElement('div', { className: 'analytics-item-label' }, [
                    createElement('div', { className: 'flex items-center gap-2 mb-1' }, [
                        createElement('span', {
                            className: 'funnel-stage-number',
                            style: 'width: 28px; height: 28px; font-size: var(--font-size-sm);'
                        }, `${index + 1}`),
                        createElement('span', { className: 'main-text' },
                            `${getStageName(rate.from_stage)} → ${getStageName(rate.to_stage)}`)
                    ]),
                    createElement('div', { className: 'sub-text' }, [
                        createElement('i', { 'data-feather': 'users', style: 'width: 12px; height: 12px;' }),
                        ` ${rate.to_count} de ${rate.from_count} prospects`
                    ])
                ]),
                createElement('div', { className: 'analytics-item-value' }, [
                    createElement('div', { className: 'flex items-center gap-2' }, [
                        createElement('span', {
                            className: `metric-card-trend ${statusClass}`,
                            style: 'padding: 2px 6px;'
                        }, [
                            createElement('i', { 'data-feather': statusIcon, style: 'width: 12px; height: 12px;' })
                        ]),
                        createElement('span', { className: 'main-value' }, `${rate.conversion_rate}%`)
                    ]),
                    createElement('div', { className: 'conversion-bar-bg', style: 'width: 120px; margin-top: 8px;' }, [
                        createElement('div', {
                            className: `bar-chart-fill ${chartColor}`,
                            style: `width: ${Math.min(percentage, 100)}%; height: 100%; border-radius: var(--radius-full);`
                        })
                    ])
                ])
            ]);
            conversionList.appendChild(item);
        });
        conversionCol.appendChild(conversionList);

        // Add summary insight
        const bestRate = analytics.conversion_rates.reduce((max, r) =>
            parseFloat(r.conversion_rate) > parseFloat(max.conversion_rate) ? r : max, analytics.conversion_rates[0]);

        if (bestRate) {
            const insight = createElement('div', { className: 'insight-card mt-4' }, [
                createElement('div', { className: 'insight-card-icon' }, [
                    createElement('i', { 'data-feather': 'zap' })
                ]),
                createElement('div', { className: 'insight-card-content' }, [
                    createElement('div', { className: 'insight-card-title' }, 'Melhor Conversão'),
                    createElement('div', { className: 'insight-card-text' },
                        `A transição ${getStageName(bestRate.from_stage)} → ${getStageName(bestRate.to_stage)} tem a melhor taxa (${bestRate.conversion_rate}%)`)
                ])
            ]);
            conversionCol.appendChild(insight);
        }
    } else {
        conversionCol.appendChild(createEmptyAnalyticsState('trending-up', 'Sem dados de conversão', 'Adicione prospects ao funil para ver as taxas de conversão.'));
    }

    return conversionCol;
}

function createAvgTimeSection(analytics) {
    const avgTimeCol = createElement('div', { className: 'analytics-section shine' });

    // Header with icon
    const header = createElement('h4', { className: 'analytics-title' }, [
        createElement('i', { 'data-feather': 'clock' }),
        createElement('span', {}, 'Tempo Médio por Estágio'),
        createElement('span', {
            className: 'badge badge-secondary ml-auto',
            style: 'margin-left: auto;'
        }, `${analytics.avg_time_in_stage.length} estágios`)
    ]);
    avgTimeCol.appendChild(header);

    if (analytics.avg_time_in_stage.length > 0) {
        const avgTimeList = createElement('div', { className: 'analytics-list' });

        // Find max duration for relative bar sizing
        const maxDuration = Math.max(...analytics.avg_time_in_stage.map(s => s.avg_duration_seconds));

        analytics.avg_time_in_stage.forEach((stage, index) => {
            const duration = formatDuration(stage.avg_duration_seconds);
            const relativeWidth = maxDuration > 0 ? (stage.avg_duration_seconds / maxDuration) * 100 : 0;
            const chartColor = `chart-${(index % 5) + 1}`;

            const item = createElement('div', {
                className: `analytics-item animate-slide-in-right stagger-${index + 1}`
            }, [
                createElement('div', { className: 'analytics-item-label' }, [
                    createElement('div', { className: 'flex items-center gap-3' }, [
                        createElement('div', {
                            className: 'duration-display-icon',
                            style: `background: var(--gradient-chart-${(index % 5) + 1});`
                        }, [
                            createElement('i', { 'data-feather': 'activity', style: 'width: 16px; height: 16px; color: var(--black);' })
                        ]),
                        createElement('div', {}, [
                            createElement('span', { className: 'main-text' }, getStageName(stage.stage)),
                            createElement('div', { className: 'sub-text' }, 'Permanência média')
                        ])
                    ])
                ]),
                createElement('div', { className: 'analytics-item-value', style: 'min-width: 140px;' }, [
                    createElement('div', { className: 'duration-display', style: 'padding: 8px 12px; background: var(--dark-5);' }, [
                        createElement('span', { className: 'duration-display-value' }, duration.formatted),
                        createElement('span', { className: 'duration-display-label' }, duration.unit)
                    ]),
                    createElement('div', { className: 'conversion-bar-bg', style: 'width: 100%; margin-top: 8px;' }, [
                        createElement('div', {
                            className: `bar-chart-fill ${chartColor}`,
                            style: `width: ${relativeWidth}%; height: 100%; border-radius: var(--radius-full);`
                        })
                    ])
                ])
            ]);
            avgTimeList.appendChild(item);
        });
        avgTimeCol.appendChild(avgTimeList);

        // Add summary insight
        const longestStage = analytics.avg_time_in_stage.reduce((max, s) =>
            s.avg_duration_seconds > max.avg_duration_seconds ? s : max, analytics.avg_time_in_stage[0]);

        if (longestStage) {
            const insight = createElement('div', { className: 'insight-card mt-4', style: 'background: linear-gradient(135deg, rgba(var(--chart-7-rgb), 0.1) 0%, transparent 100%); border-color: rgba(var(--chart-7-rgb), 0.2);' }, [
                createElement('div', { className: 'insight-card-icon', style: 'background: linear-gradient(135deg, var(--chart-7), var(--chart-2));' }, [
                    createElement('i', { 'data-feather': 'alert-circle' })
                ]),
                createElement('div', { className: 'insight-card-content' }, [
                    createElement('div', { className: 'insight-card-title', style: 'color: var(--chart-7);' }, 'Estágio Mais Longo'),
                    createElement('div', { className: 'insight-card-text' },
                        `${getStageName(longestStage.stage)} tem o maior tempo médio de permanência (${formatDuration(longestStage.avg_duration_seconds).full})`)
                ])
            ]);
            avgTimeCol.appendChild(insight);
        }
    } else {
        avgTimeCol.appendChild(createEmptyAnalyticsState('clock', 'Sem dados de tempo', 'Dados de tempo serão exibidos quando houver movimentações no funil.'));
    }

    return avgTimeCol;
}

function createInsightsSection(analytics) {
    const section = createElement('div', { className: 'card mt-6 animate-fade-in-up' });

    // Card header
    const header = createElement('div', { className: 'card-header' }, [
        createElement('h3', { className: 'card-title' }, [
            createElement('i', { 'data-feather': 'lightbulb' }),
            'Insights e Recomendações'
        ])
    ]);
    section.appendChild(header);

    const body = createElement('div', { className: 'card-body' });
    const insightsGrid = createElement('div', { className: 'grid gap-4', style: 'display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: var(--space-4);' });

    // Generate dynamic insights based on data
    const insights = generateInsights(analytics);

    insights.forEach((insight, index) => {
        const card = createElement('div', {
            className: `insight-card animate-fade-in stagger-${index + 1}`,
            style: insight.style || ''
        }, [
            createElement('div', { className: 'insight-card-icon', style: insight.iconStyle || '' }, [
                createElement('i', { 'data-feather': insight.icon })
            ]),
            createElement('div', { className: 'insight-card-content' }, [
                createElement('div', { className: 'insight-card-title', style: insight.titleStyle || '' }, insight.title),
                createElement('div', { className: 'insight-card-text' }, insight.text)
            ])
        ]);
        insightsGrid.appendChild(card);
    });

    body.appendChild(insightsGrid);
    section.appendChild(body);

    return section;
}

function generateInsights(analytics) {
    const insights = [];

    // Conversion rate insights
    if (analytics.conversion_rates.length > 0) {
        const avgRate = analytics.conversion_rates.reduce((sum, r) => sum + parseFloat(r.conversion_rate), 0) / analytics.conversion_rates.length;

        if (avgRate < 30) {
            insights.push({
                icon: 'alert-triangle',
                title: 'Taxa de Conversão Baixa',
                text: `A taxa média de ${avgRate.toFixed(1)}% indica oportunidades de melhoria no funil.`,
                style: 'background: linear-gradient(135deg, rgba(var(--warning-rgb), 0.1) 0%, transparent 100%); border-color: rgba(var(--warning-rgb), 0.2);',
                iconStyle: 'background: linear-gradient(135deg, var(--warning), var(--warning-dark));',
                titleStyle: 'color: var(--warning);'
            });
        } else if (avgRate >= 50) {
            insights.push({
                icon: 'award',
                title: 'Excelente Performance',
                text: `A taxa média de ${avgRate.toFixed(1)}% está acima da média do mercado. Continue assim!`,
                style: 'background: linear-gradient(135deg, rgba(var(--success-rgb), 0.1) 0%, transparent 100%); border-color: rgba(var(--success-rgb), 0.2);',
                iconStyle: 'background: linear-gradient(135deg, var(--success), var(--success-dark));',
                titleStyle: 'color: var(--success);'
            });
        }

        // Find bottleneck
        const worstRate = analytics.conversion_rates.reduce((min, r) =>
            parseFloat(r.conversion_rate) < parseFloat(min.conversion_rate) ? r : min, analytics.conversion_rates[0]);

        if (parseFloat(worstRate.conversion_rate) < 30) {
            insights.push({
                icon: 'target',
                title: 'Ponto de Atenção',
                text: `A transição ${getStageName(worstRate.from_stage)} → ${getStageName(worstRate.to_stage)} precisa de atenção (${worstRate.conversion_rate}%).`,
                style: 'background: linear-gradient(135deg, rgba(var(--error-rgb), 0.1) 0%, transparent 100%); border-color: rgba(var(--error-rgb), 0.2);',
                iconStyle: 'background: linear-gradient(135deg, var(--error), var(--error-dark));',
                titleStyle: 'color: var(--error);'
            });
        }
    }

    // Time insights
    if (analytics.avg_time_in_stage.length > 0) {
        const totalTime = analytics.avg_time_in_stage.reduce((sum, s) => sum + s.avg_duration_seconds, 0);
        const avgTimeFormatted = formatDuration(totalTime / analytics.avg_time_in_stage.length);

        insights.push({
            icon: 'clock',
            title: 'Ciclo de Vendas',
            text: `O tempo médio por estágio é ${avgTimeFormatted.full}. Otimize os estágios mais longos.`,
            style: 'background: linear-gradient(135deg, rgba(var(--chart-7-rgb), 0.1) 0%, transparent 100%); border-color: rgba(var(--chart-7-rgb), 0.2);',
            iconStyle: 'background: linear-gradient(135deg, var(--chart-7), var(--secondary));',
            titleStyle: 'color: var(--chart-7);'
        });
    }

    // Default insight if no data
    if (insights.length === 0) {
        insights.push({
            icon: 'info',
            title: 'Colete Mais Dados',
            text: 'Continue trabalhando no funil para gerar insights personalizados baseados em seus dados.',
            style: '',
            iconStyle: '',
            titleStyle: ''
        });
    }

    return insights;
}

function createEmptyAnalyticsState(icon, title, text) {
    return createElement('div', { className: 'analytics-empty-state', style: 'padding: var(--space-8);' }, [
        createElement('i', { 'data-feather': icon, class: 'analytics-empty-icon' }),
        createElement('h4', { className: 'analytics-empty-title' }, title),
        createElement('p', { className: 'analytics-empty-text' }, text)
    ]);
}

function formatDuration(seconds) {
    if (seconds < 60) {
        return { formatted: Math.round(seconds), unit: 'seg', full: `${Math.round(seconds)} segundos` };
    } else if (seconds < 3600) {
        const mins = Math.round(seconds / 60);
        return { formatted: mins, unit: 'min', full: `${mins} minutos` };
    } else if (seconds < 86400) {
        const hours = (seconds / 3600).toFixed(1);
        return { formatted: hours, unit: 'hrs', full: `${hours} horas` };
    } else {
        const days = (seconds / 86400).toFixed(1);
        return { formatted: days, unit: 'dias', full: `${days} dias` };
    }
}

function applyStaggerAnimations(container) {
    const items = container.querySelectorAll('[class*="stagger-"]');
    items.forEach((item, index) => {
        item.style.animationDelay = `${index * 0.05}s`;
    });
}

async function fetchQueueStatus() {
    console.log('dashboard.js: fetchQueueStatus - Buscando status da fila...');
    const queueStatusDisplay = document.getElementById('queue-status-display');

    // Verificar se os elementos ainda existem (página pode ter sido trocada)
    if (!queueStatusDisplay) {
        console.log('dashboard.js: fetchQueueStatus - Elemento queue-status-display não encontrado. Página provavelmente foi trocada.');
        return;
    }

    try {
        const status = await getQueueStatus();
        console.log('dashboard.js: fetchQueueStatus - Status da fila recebido:', status);

        // Re-verificar após await pois a página pode ter sido trocada durante a requisição
        if (!document.getElementById('queue-status-display')) {
            console.log('dashboard.js: fetchQueueStatus - Página foi trocada durante requisição. Abortando atualização da UI.');
            return;
        }

        queueStatusDisplay.innerHTML = `
            <div class="queue-status-items">
                <div class="queue-status-item">
                    <span class="queue-status-label">Tamanho da fila</span>
                    <span class="queue-status-value">${status.queue_size}</span>
                </div>
                <div class="queue-status-item">
                    <span class="queue-status-label">Status</span>
                    <span class="badge ${status.is_paused ? 'badge-warning' : 'badge-success'}">
                        ${status.is_paused ? 'Pausada' : 'Processando'}
                    </span>
                </div>
            </div>
        `;

        const pauseBtn = document.getElementById('pause-queue-btn');
        const resumeBtn = document.getElementById('resume-queue-btn');
        if (pauseBtn) pauseBtn.disabled = status.is_paused;
        if (resumeBtn) resumeBtn.disabled = !status.is_paused;
        console.log('dashboard.js: fetchQueueStatus - Status da fila atualizado na UI.');
    } catch (error) {
        console.error('dashboard.js: fetchQueueStatus - Erro ao buscar status da fila:', error);

        // Re-verificar elementos após catch
        const queueStatusDisplayAfterError = document.getElementById('queue-status-display');
        const pauseBtnAfterError = document.getElementById('pause-queue-btn');
        const resumeBtnAfterError = document.getElementById('resume-queue-btn');

        if (queueStatusDisplayAfterError) {
            queueStatusDisplayAfterError.innerHTML = `<div class="alert alert-error">Erro ao carregar status da fila.</div>`;
        }
        if (pauseBtnAfterError) pauseBtnAfterError.disabled = true;
        if (resumeBtnAfterError) resumeBtnAfterError.disabled = true;
    }
}

async function handlePauseQueue() {
    console.log('dashboard.js: handlePauseQueue - Tentando pausar fila...');
    const feedbackContainer = document.getElementById('queue-feedback');
    const pauseBtn = document.getElementById('pause-queue-btn');
    setLoadingState(pauseBtn, true);
    clearFeedback(feedbackContainer);
    try {
        const response = await pauseQueue();
        console.log('dashboard.js: handlePauseQueue - Resposta de pauseQueue:', response);
        showToast(response.message, 'success');
        await fetchQueueStatus(); // Atualiza o status após a ação
        console.log('dashboard.js: handlePauseQueue - Fila pausada com sucesso e status atualizado.');
    } catch (error) {
        console.error('dashboard.js: handlePauseQueue - Erro ao pausar fila:', error);
        showToast(error.message || 'Erro ao pausar a fila.', 'error');
    } finally {
        setLoadingState(pauseBtn, false);
        console.log('dashboard.js: handlePauseQueue - Estado de loading do botão de pausar removido.');
    }
}

async function handleResumeQueue() {
    console.log('dashboard.js: handleResumeQueue - Tentando retomar fila...');
    const feedbackContainer = document.getElementById('queue-feedback');
    const resumeBtn = document.getElementById('resume-queue-btn');
    setLoadingState(resumeBtn, true);
    clearFeedback(feedbackContainer);
    try {
        const response = await resumeQueue();
        console.log('dashboard.js: handleResumeQueue - Resposta de resumeQueue:', response);
        showToast(response.message, 'success');
        await fetchQueueStatus(); // Atualiza o status após a ação
        console.log('dashboard.js: handleResumeQueue - Fila retomada com sucesso e status atualizado.');
    } catch (error) {
        console.error('dashboard.js: handleResumeQueue - Erro ao retomar fila:', error);
        showToast(error.message || 'Erro ao retomar a fila.', 'error');
    } finally {
        setLoadingState(resumeBtn, false);
        console.log('dashboard.js: handleResumeQueue - Estado de loading do botão de retomar removido.');
    }
}

async function handleToggleAiQueueOnly(event) {
    const isEnabled = event.target.checked;
    console.log(`dashboard.js: Toggle 'AI para fila de prospecção' clicado. Novo estado: ${isEnabled}`);
    const feedbackContainer = document.getElementById('ai-queue-only-feedback');
    const toggleEl = document.getElementById('toggle-ai-queue-only');
    setLoadingState(toggleEl, true); // Visualmente desabilita o toggle durante a requisição
    clearFeedback(feedbackContainer);

    try {
        const response = await toggleAiQueueOnly(isEnabled);
        showToast(response.message, 'success');
        console.log('dashboard.js: Configuração de AI para fila salva com sucesso.');
        // Nenhuma necessidade de re-renderizar, a UI já reflete o estado do toggle.
        // Apenas para garantir, o estado do 'checked' pode ser atualizado a partir da resposta,
        // mas como a requisição POST apenas confirma o que foi enviado, geralmente não é necessário.
        toggleEl.checked = response.data.enabled;
    } catch (error) {
        console.error('dashboard.js: Erro ao salvar configuração de AI para fila:', error);
        showToast(error.message || 'Erro ao salvar configuração de IA.', 'error');
        toggleEl.checked = !isEnabled; // Reverte o estado do toggle em caso de erro
    } finally {
        setLoadingState(toggleEl, false);
    }
}

async function handleClearHistory() {
    console.log('dashboard.js: handleClearHistory - Botão Limpar Histórico clicado.');
    const feedbackContainer = document.getElementById('clear-history-feedback');
    const clearBtn = document.getElementById('clear-history-btn');
    clearFeedback(feedbackContainer);

    const confirmation = confirm("ATENÇÃO: Esta ação é irreversível e limpará TODO o histórico de prospects, conversas e dados do Redis. Deseja continuar?");
    console.log('dashboard.js: handleClearHistory - Confirmação do usuário:', confirmation);

    if (confirmation) {
        setLoadingState(clearBtn, true);
        console.log('dashboard.js: handleClearHistory - Usuário confirmou. Chamando API para limpar histórico...');
        try {
            const response = await clearAllHistory(); // Esta função precisa ser criada em api.js
            console.log('dashboard.js: handleClearHistory - Resposta da API clearAllHistory:', response);
            showToast(response.message || 'Histórico limpo com sucesso!', 'success');
            await fetchDashboardData(); // Atualiza os KPIs e funil
            await fetchQueueStatus();   // Atualiza o status da fila (pode não ser diretamente afetado, mas bom para consistência)
            console.log('dashboard.js: handleClearHistory - Histórico limpo e dados do dashboard atualizados.');
        } catch (error) {
            console.error('dashboard.js: handleClearHistory - Erro ao limpar histórico:', error);
            showToast(error.message || 'Erro ao limpar o histórico.', 'error');
        } finally {
            setLoadingState(clearBtn, false);
            console.log('dashboard.js: handleClearHistory - Estado de loading do botão de limpar histórico removido.');
        }
    } else {
        console.log('dashboard.js: handleClearHistory - Usuário cancelou a limpeza do histórico.');
        showToast('Limpeza de histórico cancelada.', 'info');
    }
}

async function handleExportQueue() {
    console.log('dashboard.js: handleExportQueue - Tentando exportar fila...');
    const feedbackContainer = document.getElementById('queue-feedback');
    const exportBtn = document.getElementById('export-queue-btn');
    setLoadingState(exportBtn, true);
    clearFeedback(feedbackContainer);

    try {
        // A chamada direta para a URL de exportação fará o download
        // Não precisamos de uma função específica em api.js se for um GET simples
        // que retorna um arquivo.
        const exportUrl = '/api/queue/export-csv';
        
        // Para forçar o download, podemos criar um link temporário e clicar nele,
        // ou usar window.location.href se o backend estiver configurado corretamente
        // com Content-Disposition: attachment.
        
        // Abordagem 1: window.location.href (mais simples se o backend estiver correto)
        // window.location.href = exportUrl;
        // showFeedback(feedbackContainer, 'Download da fila iniciado...', 'info');

        // Abordagem 2: Fetch e download manual (mais controle sobre feedback e erros)
        const response = await fetch(exportUrl, {
            method: 'GET',
            headers: {
                // Adicionar token de autenticação se necessário para este endpoint
                'Authorization': `Bearer ${localStorage.getItem('innovaFluxoAuthToken')}`
            }
        });

        if (response.status === 404) {
            const errorData = await response.json().catch(() => ({ detail: 'A fila está vazia. Nenhum prospect para exportar.' }));
            showToast(errorData.detail, 'info'); // Usar 'info' para fila vazia
            console.log('dashboard.js: handleExportQueue - Fila vazia (404).');
            setLoadingState(exportBtn, false); // Certificar que o botão é reativado
            return; // Interrompe a execução aqui
        } else if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'Erro desconhecido ao exportar fila.' }));
            throw new Error(errorData.detail || `Erro ${response.status} ao exportar fila.`);
        }

        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        // Tenta obter o nome do arquivo do header Content-Disposition
        const disposition = response.headers.get('content-disposition');
        let filename = 'fila_prospects.csv'; // Nome padrão
        if (disposition && disposition.indexOf('attachment') !== -1) {
            const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
            const matches = filenameRegex.exec(disposition);
            if (matches != null && matches[1]) {
                filename = matches[1].replace(/['"]/g, '');
            }
        }
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(downloadUrl); // Libera o objeto URL

        showToast('Fila exportada com sucesso!', 'success');
        console.log('dashboard.js: handleExportQueue - Fila exportada com sucesso.');

    } catch (error) {
        console.error('dashboard.js: handleExportQueue - Erro ao exportar fila:', error);
        showToast(error.message || 'Erro ao exportar a fila.', 'error');
    } finally {
        setLoadingState(exportBtn, false);
    }
}

// ========== FUNNELS OVERVIEW SECTION ==========

async function fetchFunnelsOverview() {
    const startTime = Date.now();
    const requestId = `funnels_overview_${startTime}`;

    console.log(`[${new Date().toISOString()}] [FETCH_FUNNELS_OVERVIEW] [${requestId}] Iniciando busca de funis configurados`);

    const container = document.getElementById('funnels-overview-container');
    if (!container) {
        console.warn(`[${new Date().toISOString()}] [FETCH_FUNNELS_OVERVIEW] [${requestId}] Container não encontrado`);
        return;
    }

    try {
        const response = await getFunnelsList(true); // Incluir inativos para mostrar todos
        const funnels = response.funnels || [];

        console.log(`[${new Date().toISOString()}] [FETCH_FUNNELS_OVERVIEW] [${requestId}] Sucesso - ${funnels.length} funis encontrados`, {
            duration: `${Date.now() - startTime}ms`
        });

        if (funnels.length === 0) {
            container.innerHTML = `
                <div class="funnels-empty-state">
                    <i data-feather="git-branch" class="funnels-empty-icon"></i>
                    <h4 class="funnels-empty-title">Nenhum funil configurado</h4>
                    <p class="funnels-empty-text">Configure seu primeiro funil de vendas para organizar seus prospects.</p>
                    <a href="#sales-flow" class="btn btn-primary btn-sm">
                        <i data-feather="plus"></i>
                        Criar Funil
                    </a>
                </div>
            `;
        } else {
            container.innerHTML = '';
            const funnelsGrid = createElement('div', { className: 'funnels-overview-grid' });

            funnels.forEach((funnel, index) => {
                // Usar stages_count da API (não stages.length)
                const stagesCount = funnel.stages_count || 0;
                const isDefault = funnel.is_default;
                const isActive = funnel.is_active !== false;

                const funnelCard = createElement('div', {
                    className: `funnel-overview-card animate-fade-in-up ${!isActive ? 'is-inactive' : ''} ${isDefault ? 'is-default' : ''}`,
                    style: `animation-delay: ${index * 0.05}s`
                }, [
                    createElement('div', { className: 'funnel-card-header' }, [
                        createElement('div', { className: 'funnel-card-icon' }, [
                            createElement('i', { 'data-feather': 'git-branch' })
                        ]),
                        createElement('div', { className: 'funnel-card-badges' }, [
                            isDefault ? createElement('span', { className: 'badge badge-primary badge-sm' }, '⭐ Padrão') : null,
                            !isActive ? createElement('span', { className: 'badge badge-warning badge-sm' }, 'Inativo') : null
                        ].filter(Boolean))
                    ]),
                    createElement('div', { className: 'funnel-card-body' }, [
                        createElement('h4', { className: 'funnel-card-name' }, funnel.name || 'Sem nome'),
                        funnel.description ? createElement('p', { className: 'funnel-card-description' }, funnel.description) : null,
                        createElement('div', { className: 'funnel-card-stats' }, [
                            createElement('div', { className: 'funnel-stat' }, [
                                createElement('i', { 'data-feather': 'layers' }),
                                createElement('span', {}, `${stagesCount} ${stagesCount === 1 ? 'etapa' : 'etapas'}`)
                            ])
                        ])
                    ].filter(Boolean))
                ]);

                funnelsGrid.appendChild(funnelCard);
            });

            container.appendChild(funnelsGrid);
        }

        if (typeof feather !== 'undefined') {
            feather.replace();
        }

    } catch (error) {
        console.error(`[${new Date().toISOString()}] [FETCH_FUNNELS_OVERVIEW] [${requestId}] ERRO`, {
            duration: `${Date.now() - startTime}ms`,
            error: error.message
        });

        container.innerHTML = `
            <div class="funnels-error-state">
                <i data-feather="alert-circle" class="funnels-error-icon"></i>
                <p class="funnels-error-text">Erro ao carregar funis configurados.</p>
                <button class="btn btn-ghost btn-sm" onclick="fetchFunnelsOverview()">
                    <i data-feather="refresh-cw"></i>
                    Tentar novamente
                </button>
            </div>
        `;

        if (typeof feather !== 'undefined') {
            feather.replace();
        }
    }
}

// Exportar para uso global (retry button)
window.fetchFunnelsOverview = fetchFunnelsOverview;

// ========== KANBAN FUNNEL SELECTOR ==========

async function loadKanbanFunnelSelector() {
    console.log('[KANBAN_FUNNEL_SELECTOR] Carregando funis disponíveis para o seletor');

    const select = document.getElementById('kanban-funnel-select');
    if (!select) {
        console.warn('[KANBAN_FUNNEL_SELECTOR] Seletor não encontrado');
        return;
    }

    try {
        const response = await getFunnelsList(false); // Apenas funis ativos
        availableFunnels = response.funnels || [];

        console.log(`[KANBAN_FUNNEL_SELECTOR] ${availableFunnels.length} funis carregados`);

        // Limpar e preencher o select
        select.innerHTML = '';

        if (availableFunnels.length === 0) {
            select.innerHTML = '<option value="">Nenhum funil configurado</option>';
            return;
        }

        // Encontrar o funil padrão
        const defaultFunnel = availableFunnels.find(f => f.is_default);

        availableFunnels.forEach(funnel => {
            const option = document.createElement('option');
            option.value = funnel.funnel_id;
            option.textContent = funnel.name + (funnel.is_default ? ' ⭐' : '');
            select.appendChild(option);
        });

        // Selecionar o funil padrão
        if (defaultFunnel) {
            select.value = defaultFunnel.funnel_id;
            currentKanbanFunnelId = defaultFunnel.funnel_id;
        } else if (availableFunnels.length > 0) {
            select.value = availableFunnels[0].funnel_id;
            currentKanbanFunnelId = availableFunnels[0].funnel_id;
        }

        console.log(`[KANBAN_FUNNEL_SELECTOR] Funil selecionado: ${currentKanbanFunnelId}`);

    } catch (error) {
        console.error('[KANBAN_FUNNEL_SELECTOR] Erro ao carregar funis:', error);
        select.innerHTML = '<option value="">Erro ao carregar funis</option>';
    }
}

async function handleKanbanFunnelChange(event) {
    const newFunnelId = event.target.value;

    if (!newFunnelId || newFunnelId === currentKanbanFunnelId) {
        return;
    }

    console.log(`[KANBAN_FUNNEL_CHANGE] Mudando de '${currentKanbanFunnelId}' para '${newFunnelId}'`);

    currentKanbanFunnelId = newFunnelId;

    // Mostrar loading no Kanban
    const kanbanBoard = document.getElementById('kanban-board');
    if (kanbanBoard) {
        kanbanBoard.innerHTML = `
            <div class="loading-wrapper loading-wrapper-lg">
                <div class="spinner spinner-lg"></div>
                <p class="text-muted mt-3">Carregando funil...</p>
            </div>
        `;
    }

    try {
        // Carregar as etapas do novo funil
        await loadSalesFlowStagesForFunnel(newFunnelId);

        // Regenerar o HTML do Kanban
        if (kanbanBoard) {
            kanbanBoard.innerHTML = generateKanbanColumnsHtml();
        }

        // Recarregar os dados do Kanban
        await loadInitialKanbanData();

        // Atualizar analytics para o novo funil
        await fetchAdvancedAnalytics();

        if (typeof feather !== 'undefined') {
            feather.replace();
        }

        showToast(`Visualizando funil: ${availableFunnels.find(f => f.funnel_id === newFunnelId)?.name || newFunnelId}`, 'success');

    } catch (error) {
        console.error('[KANBAN_FUNNEL_CHANGE] Erro ao mudar funil:', error);
        showToast('Erro ao carregar funil selecionado', 'error');

        // Restaurar kanban com mensagem de erro
        if (kanbanBoard) {
            kanbanBoard.innerHTML = `
                <div class="analytics-empty-state">
                    <i data-feather="alert-circle" class="analytics-empty-icon"></i>
                    <h4>Erro ao carregar funil</h4>
                    <p>Não foi possível carregar as etapas do funil selecionado.</p>
                </div>
            `;
        }

        if (typeof feather !== 'undefined') {
            feather.replace();
        }
    }
}

async function loadSalesFlowStagesForFunnel(funnelId) {
    console.log(`[LOAD_FUNNEL_STAGES] Carregando etapas do funil '${funnelId}'`);

    try {
        const funnel = await getFunnel(funnelId);
        const stages = funnel.stages || [];

        // Limpa e reconstrói o mapa de estágios
        salesFlowStagesMap = {};
        KANBAN_COLUMN_IDS = [];

        // Ordena os estágios por stage_number
        stages.sort((a, b) => a.stage_number - b.stage_number);

        // Popula o mapa e os IDs das colunas
        stages.forEach(stage => {
            const stageNumber = stage.stage_number;
            salesFlowStagesMap[stageNumber] = {
                name: stage.objective || `Estágio ${stageNumber}`,
                trigger: stage.trigger_description || ''
            };
            KANBAN_COLUMN_IDS.push(stageNumber);
        });

        // Sempre adiciona a coluna de Agendamentos no final
        KANBAN_COLUMN_IDS.push('scheduled');

        console.log(`[LOAD_FUNNEL_STAGES] Carregadas ${stages.length} etapas para funil '${funnelId}'`);
        console.log('[LOAD_FUNNEL_STAGES] IDs das colunas Kanban:', KANBAN_COLUMN_IDS);

        return { stages, columnIds: KANBAN_COLUMN_IDS };

    } catch (error) {
        console.error(`[LOAD_FUNNEL_STAGES] Erro ao carregar funil '${funnelId}':`, error);
        throw error;
    }
}

function initializeKanbanColumnState() {
    kanbanColumnState = {};
    KANBAN_COLUMN_IDS.forEach(columnId => {
        kanbanColumnState[columnId] = { offset: 0, totalKnown: 0, isLoading: false, allLoaded: false };
    });
    console.log('dashboard.js: Estado das colunas Kanban inicializado/resetado:', kanbanColumnState);
}

async function loadInitialKanbanData() {
    console.log('dashboard.js: Carregando dados iniciais do Kanban para todas as colunas...');
    initializeKanbanColumnState();

    const loadPromises = KANBAN_COLUMN_IDS.map(columnId => {
        let apiParams = {
            limit: INITIAL_ITEMS_PER_COLUMN,
            offset: 0,
            status: columnId === 'scheduled' ? 'scheduled' : 'active',
        };
        if (columnId !== 'scheduled' && columnId != null) {
            apiParams.stage = columnId;
        }
        // CORREÇÃO: Filtrar prospects pelo funil selecionado
        if (currentKanbanFunnelId) {
            apiParams.funnel_id = currentKanbanFunnelId;
        }
        const filteredParams = Object.fromEntries(Object.entries(apiParams).filter(([_, v]) => v != null && v !== ''));
        return fetchAndRenderColumnData(columnId, filteredParams, false);
    });

    try {
        await Promise.all(loadPromises);
        console.log('dashboard.js: Todos os dados iniciais das colunas Kanban foram carregados (ou tentativas concluídas).');
    } catch (error) {
        console.error('dashboard.js: Erro ao carregar dados iniciais de uma ou mais colunas Kanban:', error);
    }
}

async function fetchAndRenderColumnData(columnId, apiParams, append = false) {
    console.log(`dashboard.js: Buscando dados para coluna ${columnId}, params: ${JSON.stringify(apiParams)}, append: ${append}`);
    const columnState = kanbanColumnState[columnId];
    if (!columnState) {
        console.error(`dashboard.js: Estado não inicializado para coluna ${columnId}.`);
        return;
    }
    if (columnState.isLoading || (columnState.allLoaded && append)) {
        console.log(`dashboard.js: Coluna ${columnId} já está carregando ou todos os itens foram carregados. Abortando.`);
        return;
    }

    columnState.isLoading = true;
    const columnCardsContainer = document.getElementById(`kanban-cards-${columnId}`);
    const loadMoreBtn = document.getElementById(`load-more-${columnId}`);
    const columnCountSpan = document.getElementById(`column-count-${columnId}`);

    if (!columnCardsContainer) {
        console.error(`dashboard.js: Container de cards para coluna ${columnId} não encontrado.`);
        columnState.isLoading = false;
        return;
    }

    if (!append) {
        columnCardsContainer.innerHTML = `
            <div class="loading-wrapper">
                <div class="spinner"></div>
            </div>
        `;
    } else if (loadMoreBtn) {
        setLoadingState(loadMoreBtn, true);
    }

    try {
        const response = await getProspectsList(apiParams);
        console.log(`dashboard.js: Dados recebidos para coluna ${columnId}:`, response);

        if (!append) {
            columnCardsContainer.innerHTML = ''; 
        }

        renderColumnCards(columnId, response.prospects, append);

        columnState.offset = apiParams.offset + response.prospects.length;
        columnState.totalKnown = response.total_count;
        columnState.allLoaded = columnState.offset >= columnState.totalKnown;
        if (columnCountSpan) {
            columnCountSpan.textContent = response.total_count.toLocaleString();
        }

    } catch (error) {
        console.error(`dashboard.js: Erro ao buscar dados para coluna ${columnId}:`, error);
        if (!append) {
            columnCardsContainer.innerHTML = `<div class="alert alert-error">Erro ao carregar.</div>`;
        } else {
            showToast(`Erro ao carregar mais para ${getKanbanColumnName(columnId)}.`, 'error');
        }
    } finally {
        columnState.isLoading = false;
        if (loadMoreBtn) setLoadingState(loadMoreBtn, false);
        updateLoadMoreButton(columnId);
    }
}

function renderColumnCards(columnId, prospects, append) {
    console.log(`dashboard.js: Renderizando ${prospects.length} cards para coluna ${columnId}, append: ${append}`);
    const columnCardsContainer = document.getElementById(`kanban-cards-${columnId}`);
    if (!columnCardsContainer) return;

    if (!append) {
        columnCardsContainer.innerHTML = ''; 
    }

    if (prospects.length === 0 && !append && columnCardsContainer.innerHTML === '') {
        columnCardsContainer.innerHTML = `
            <div class="empty-state">
                <i data-feather="user-x" class="empty-state-icon"></i>
                <p class="empty-state-text">Nenhum prospect aqui</p>
            </div>
        `;
        return;
    }

    prospects.forEach(prospect => {
        const displayName = prospect.name || formatJidToDisplay(prospect.jid);
        const initial = (displayName || 'U').charAt(0).toUpperCase();

        // Criar elemento avatar com fallback para inicial
        const avatarElement = createElement('div', { className: 'kanban-card-avatar', 'data-jid': prospect.jid }, [
            createElement('div', { className: 'kanban-card-avatar-fallback' }, initial)
        ]);

        // Buscar foto de perfil de forma assíncrona
        fetchProfilePicture(prospect.jid, avatarElement);

        // Criar elementos de tags do prospect
        const prospectTags = prospect.tags || [];
        const tagsElements = prospectTags.slice(0, 3).map(tagName => {
            const tagColor = getTagColor(tagName);
            return createElement('span', {
                className: 'kanban-card-tag',
                style: `background-color: ${tagColor}20; color: ${tagColor}; border-color: ${tagColor}40;`
            }, tagName);
        });

        // Se houver mais de 3 tags, mostrar contador
        if (prospectTags.length > 3) {
            tagsElements.push(createElement('span', {
                className: 'kanban-card-tag kanban-card-tag-more',
                title: prospectTags.slice(3).join(', ')
            }, `+${prospectTags.length - 3}`));
        }

        // Criar container de tags (vazio se não houver tags)
        const tagsContainer = prospectTags.length > 0
            ? createElement('div', { className: 'kanban-card-tags' }, tagsElements)
            : null;

        const cardBodyChildren = [
            createElement('p', { className: 'kanban-card-detail' }, [
                createElement('i', { 'data-feather': 'phone' }),
                formatJidToDisplay(prospect.jid)
            ]),
            createElement('p', { className: 'kanban-card-detail' }, [
                createElement('i', { 'data-feather': 'info' }),
                `Status: ${getStatusName(prospect.status)}`
            ])
        ];

        // Adicionar tags ao body se existirem
        if (tagsContainer) {
            cardBodyChildren.push(tagsContainer);
        }

        const card = createElement('div', {
            className: 'kanban-card',
            'data-jid': prospect.jid
        }, [
            createElement('div', { className: 'kanban-card-header' }, [
                avatarElement,
                createElement('h5', {
                    className: 'kanban-card-title'
                }, displayName),
                createElement('span', { className: `llm-status-indicator ${prospect.llm_paused ? 'is-paused' : 'is-active'}` })
            ]),
            createElement('div', { className: 'kanban-card-body' }, cardBodyChildren),
            createElement('div', { className: 'kanban-card-footer' }, [
                createElement('p', { className: 'kanban-card-detail' }, [
                    createElement('i', { 'data-feather': 'clock' }),
                    prospect.last_interaction_at ? formatTimestamp(prospect.last_interaction_at) : 'Sem interação'
                ]),
                createElement('div', { className: 'kanban-card-actions' }, [
                    createElement('button', {
                        className: `btn btn-icon btn-sm toggle-llm-btn ${prospect.llm_paused ? 'btn-success' : 'btn-warning'}`,
                        title: prospect.llm_paused ? 'Reativar LLM' : 'Pausar LLM',
                        dataset: { jid: prospect.jid, llmPaused: prospect.llm_paused.toString() }
                    }, [createElement('i', { 'data-feather': prospect.llm_paused ? 'play' : 'pause' })]),
                    createElement('button', {
                        className: 'btn btn-icon btn-sm btn-secondary view-history-btn',
                        title: 'Ver Conversa',
                        dataset: { jid: prospect.jid }
                    }, [createElement('i', { 'data-feather': 'message-circle' })])
                ])
            ])
        ]);
        columnCardsContainer.appendChild(card);
    });

    // Adicionar event listeners para botões de ação
    columnCardsContainer.querySelectorAll('.toggle-llm-btn:not(.listener-added)').forEach(button => {
        button.addEventListener('click', handleToggleLLM);
        button.classList.add('listener-added');
    });

    columnCardsContainer.querySelectorAll('.view-history-btn:not(.listener-added)').forEach(button => {
        button.addEventListener('click', handleViewHistory);
        button.classList.add('listener-added');
    });

    if (typeof feather !== 'undefined') {
        feather.replace();
    }
}

function updateLoadMoreButton(columnId) {
    const columnState = kanbanColumnState[columnId];
    const columnCardsContainer = document.getElementById(`kanban-cards-${columnId}`);

    if (!columnCardsContainer || !columnState) {
        console.warn(`dashboard.js: updateLoadMoreButton - Não foi possível encontrar o container de cards ou o estado da coluna para ${columnId}.`);
        return;
    }
    
    const existingBtn = columnCardsContainer.parentNode.querySelector(`#load-more-${columnId}`);
    if (existingBtn) {
        existingBtn.removeEventListener('click', () => loadMoreForColumn(columnId)); 
        existingBtn.remove();
    }
    
    if (!columnState.allLoaded && !columnState.isLoading && columnState.totalKnown > columnState.offset) {
        const newLoadMoreBtn = createElement('button', {
            className: 'btn btn-ghost w-full mt-3 load-more-btn',
            id: `load-more-${columnId}`
        }, [
            createElement('i', { 'data-feather': 'plus' }),
            ` Carregar Mais (${columnState.totalKnown - columnState.offset})`
        ]);
        
        newLoadMoreBtn.addEventListener('click', () => loadMoreForColumn(columnId));
        columnCardsContainer.parentNode.appendChild(newLoadMoreBtn);
        
        // Re-render feather icons
        if (typeof feather !== 'undefined') {
            feather.replace();
        }
        
        console.log(`dashboard.js: Botão "Carregar Mais" atualizado/adicionado para coluna ${columnId}.`);
    } else {
        console.log(`dashboard.js: Botão "Carregar Mais" não necessário ou removido para coluna ${columnId}. AllLoaded: ${columnState.allLoaded}, IsLoading: ${columnState.isLoading}`);
    }
}


async function loadMoreForColumn(columnId) {
    console.log(`dashboard.js: Carregando mais prospects para coluna ${columnId}...`);
    const columnState = kanbanColumnState[columnId];
    if (columnState && !columnState.isLoading && !columnState.allLoaded) {
        let apiParams = {
            limit: ITEMS_PER_LOAD_MORE,
            offset: columnState.offset,
            status: columnId === 'scheduled' ? 'scheduled' : 'active',
        };
        if (columnId !== 'scheduled' && columnId != null) {
            apiParams.stage = columnId;
        }
        // CORREÇÃO: Filtrar prospects pelo funil selecionado
        if (currentKanbanFunnelId) {
            apiParams.funnel_id = currentKanbanFunnelId;
        }
        const filteredParams = Object.fromEntries(Object.entries(apiParams).filter(([_, v]) => v != null && v !== ''));
        await fetchAndRenderColumnData(columnId, filteredParams, true);
    }
}

// Handler para toggle de LLM pause
async function handleToggleLLM(event) {
    event.stopPropagation();
    const button = event.currentTarget;
    const jid = button.dataset.jid;
    const currentLlmPaused = button.dataset.llmPaused === 'true';
    const newLlmPausedState = !currentLlmPaused;

    console.log(`dashboard.js: ${newLlmPausedState ? 'Pausando' : 'Reativando'} LLM para JID: ${jid}`);

    // Desabilitar botão durante a requisição
    button.disabled = true;

    try {
        await toggleProspectLLMPause(jid, newLlmPausedState);

        // Atualizar estado do botão
        button.dataset.llmPaused = newLlmPausedState.toString();
        button.title = newLlmPausedState ? 'Reativar LLM' : 'Pausar LLM';
        button.classList.toggle('btn-success', newLlmPausedState);
        button.classList.toggle('btn-warning', !newLlmPausedState);

        // Atualizar ícone
        const icon = button.querySelector('i');
        if (icon) {
            icon.setAttribute('data-feather', newLlmPausedState ? 'play' : 'pause');
            if (typeof feather !== 'undefined') {
                feather.replace();
            }
        }

        // Atualizar indicador de status no card
        const card = button.closest('.kanban-card');
        if (card) {
            const statusIndicator = card.querySelector('.llm-status-indicator');
            if (statusIndicator) {
                statusIndicator.classList.toggle('is-paused', newLlmPausedState);
                statusIndicator.classList.toggle('is-active', !newLlmPausedState);
            }
        }

        showToast(`LLM ${newLlmPausedState ? 'pausado' : 'reativado'} para ${formatJidToDisplay(jid)}`, 'success');
    } catch (error) {
        console.error(`dashboard.js: Erro ao ${newLlmPausedState ? 'pausar' : 'reativar'} LLM para ${jid}:`, error);
        showToast('Erro ao alterar estado do LLM', 'error');
    } finally {
        button.disabled = false;
    }
}

// Handler para visualizar histórico de conversa
async function handleViewHistory(event) {
    event.stopPropagation();
    const button = event.currentTarget;
    const jid = button.dataset.jid;

    console.log(`dashboard.js: Visualizando histórico para JID: ${jid}`);

    const historyModal = document.getElementById('prospect-history-modal');
    const historyContent = document.getElementById('prospect-history-content');
    const historyModalTitle = document.getElementById('history-modal-title');
    const historyModalBackdrop = document.getElementById('prospect-history-modal-backdrop');

    if (!historyModal || !historyContent || !historyModalTitle) {
        console.error('dashboard.js: Modal de histórico não encontrado');
        showToast('Erro ao abrir histórico', 'error');
        return;
    }

    // Mostrar modal com loading
    historyModalTitle.textContent = 'Histórico de Conversa';
    historyContent.innerHTML = `<div class="spinner-container"><div class="loading-spinner"></div></div>`;
    showModal('prospect-history-modal');

    try {
        const response = await getProspectHistory(jid);
        historyContent.innerHTML = '';

        const displayName = response.prospect?.name || formatJidToDisplay(jid);
        const initial = (displayName || 'U').charAt(0).toUpperCase();

        // Header com info do prospect
        const headerElement = createElement('div', { className: 'history-prospect-header' }, [
            createElement('div', { className: 'history-prospect-avatar', id: `history-avatar-${jid}` }, initial),
            createElement('div', { className: 'history-prospect-info' }, [
                createElement('h4', { className: 'history-prospect-name' }, displayName),
                createElement('span', { className: 'history-prospect-phone' }, [
                    createElement('i', { 'data-feather': 'phone' }),
                    formatJidToDisplay(jid)
                ])
            ])
        ]);
        historyContent.appendChild(headerElement);

        // Buscar foto de perfil
        fetchProfilePicture(jid, document.getElementById(`history-avatar-${jid}`));

        // Renderizar histórico
        if (!response.history || response.history.length === 0) {
            historyContent.appendChild(createElement('p', { className: 'text-center text-muted', style: 'padding: 2rem;' }, 'Nenhum histórico de conversa encontrado.'));
        } else {
            // Usa as mesmas classes do leads.js para consistência visual
            const messagesContainer = createElement('div', { className: 'history-messages' });

            response.history.forEach(item => {
                const isUser = item.role === 'user';
                const msgClass = isUser ? 'message-user' : 'message-assistant';
                const senderLabel = isUser ? 'Lead' : 'Agente';
                const timestamp = item.timestamp ? formatTimestamp(item.timestamp) : '';

                const messageDiv = createElement('div', { className: `history-message ${msgClass}` }, [
                    createElement('div', { className: 'message-header' }, [
                        createElement('span', { className: 'message-sender' }, senderLabel),
                        createElement('span', { className: 'message-time' }, timestamp)
                    ]),
                    createElement('div', { className: 'message-content' }, item.content || '')
                ]);
                messagesContainer.appendChild(messageDiv);
            });

            historyContent.appendChild(messagesContainer);

            // Scroll para o final
            setTimeout(() => {
                const historyList = historyContent.querySelector('.history-messages');
                if (historyList) {
                    historyList.scrollTop = historyList.scrollHeight;
                }
            }, 100);
        }

        if (typeof feather !== 'undefined') {
            feather.replace();
        }
    } catch (error) {
        console.error('dashboard.js: Erro ao carregar histórico:', error);
        historyContent.innerHTML = `<div class="error-message">Erro ao carregar histórico. Verifique o console para detalhes.</div>`;
    }
}
