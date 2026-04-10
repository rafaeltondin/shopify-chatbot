// static/js/pages/manageProspects.js
import { getProspectsList, getProspectHistory, toggleProspectLLMPause, getProspectProfilePicture, getSalesFlowConfig,
         getFunnelsList, updateProspectFunnel } from '../api.js';
import { showModal, hideModal, showFeedback, clearFeedback, setLoadingState, formatTimestamp, formatJidToDisplay, createElement, getStatusName } from '../utils.js';

// Funnel-related state
let availableFunnels = [];
let currentFunnelId = null; // The currently displayed funnel

const INITIAL_ITEMS_PER_COLUMN = 10;
const ITEMS_PER_LOAD_MORE = 10;
let kanbanColumnState = {}; // Ex: { 1: { offset: 0, totalKnown: 0, isLoading: false, allLoaded: false }, ... }

// KANBAN_COLUMN_IDS será populado dinamicamente baseado no Sales Flow
// Incluirá sempre a coluna 'scheduled' (Agendamentos)
let KANBAN_COLUMN_IDS = [];

// Mapa de stage_number para nome do estágio (objetivo do funil)
let salesFlowStagesMap = {};

// Cache de fotos de perfil para evitar requisições repetidas
const profilePictureCache = new Map();

// Busca foto de perfil do WhatsApp e atualiza o avatar
async function fetchProfilePicture(jid, avatarElement) {
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
        profilePictureCache.set(jid, profileUrl || null);
        if (profileUrl) {
            applyProfilePicture(avatarElement, profileUrl);
        }
    } catch (error) {
        console.debug(`manageProspects.js: Erro ao buscar foto de perfil para ${jid}:`, error);
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
        console.debug('manageProspects.js: Falha ao carregar imagem de perfil');
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

// Carrega as etapas do funil de vendas e configura as colunas do Kanban
async function loadSalesFlowStages() {
    console.log('manageProspects.js: Carregando etapas do funil de vendas...');
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

        console.log('manageProspects.js: Etapas do funil carregadas:', salesFlowStagesMap);
        console.log('manageProspects.js: IDs das colunas Kanban:', KANBAN_COLUMN_IDS);

        return { stages, columnIds: KANBAN_COLUMN_IDS };
    } catch (error) {
        console.error('manageProspects.js: Erro ao carregar etapas do funil. Usando configuração padrão.', error);
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

// Gera o HTML do select de filtro de estágios dinamicamente
function generateStageFilterOptions() {
    let optionsHtml = '<option value="">Todos os estágios</option>';
    KANBAN_COLUMN_IDS.forEach(columnId => {
        if (columnId !== 'scheduled') {
            const stageName = getKanbanColumnName(columnId);
            optionsHtml += `<option value="${columnId}">${stageName}</option>`;
        }
    });
    return optionsHtml;
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

function handleWebSocketMessage(event) {
    const { event: eventName, data } = event.detail;

    if (eventName === 'prospect_stage_updated') {
        console.log('WebSocket event received: prospect_stage_updated', data);
        const { jid, old_stage, new_stage } = data;

        // Find the card
        const card = document.querySelector(`.kanban-card[data-jid="${jid}"]`);

        if (card) {
            // Move card to the top of the new column
            const newColumn = document.getElementById(`kanban-cards-${new_stage}`);
            if (newColumn) {
                newColumn.prepend(card);
                // Add a temporary highlight to the moved card
                card.style.transition = 'background-color 0.5s ease';
                card.style.backgroundColor = 'var(--color-primary-50)';
                setTimeout(() => {
                    card.style.backgroundColor = ''; // Revert to default
                }, 2000);
            }
        }

        // Update column counts
        const oldColumnCount = document.getElementById(`column-count-${old_stage}`);
        if (oldColumnCount) {
            oldColumnCount.textContent = parseInt(oldColumnCount.textContent) - 1;
        }
        const newColumnCount = document.getElementById(`column-count-${new_stage}`);
        if (newColumnCount) {
            newColumnCount.textContent = parseInt(newColumnCount.textContent) + 1;
        }
    }
}

export async function loadManageProspectsPage(container) {
    console.log('manageProspects.js: Carregando página de Analisar Prospects...');
    document.addEventListener('websocket-message', handleWebSocketMessage);

    // Primeiro, mostra um loading enquanto carrega as etapas do funil
    container.innerHTML = `
        <div class="animate-fade-in">
            <header class="page-header">
                <h1 class="page-title">
                    <span class="icon-wrapper">
                        <i data-feather="users"></i>
                    </span>
                    Funil de Vendas
                </h1>
                <p class="page-subtitle">Visualize e gerencie todos os prospects no seu funil de vendas</p>
            </header>
            <div class="spinner-container" style="padding: 4rem;">
                <div class="loading-spinner"></div>
                <p class="text-muted mt-4">Carregando etapas do funil...</p>
            </div>
        </div>
    `;

    if (typeof feather !== 'undefined') {
        feather.replace();
    }

    // Carrega as etapas do funil de vendas e os funis disponíveis
    await Promise.all([
        loadSalesFlowStages(),
        loadAvailableFunnels()
    ]);

    // Agora renderiza a página com as colunas dinâmicas
    container.innerHTML = `
        <div class="animate-fade-in">
            <header class="page-header">
                <h1 class="page-title">
                    <span class="icon-wrapper">
                        <i data-feather="users"></i>
                    </span>
                    Funil de Vendas
                </h1>
                <p class="page-subtitle">Visualize e gerencie todos os prospects no seu funil de vendas</p>
            </header>

            <div class="card mb-8">
                <div class="card-header">
                    <h3 class="card-title">
                        <i data-feather="filter"></i>
                        Filtros de Busca
                    </h3>
                </div>
                <div class="card-body">
                    <form id="prospect-filters-form" class="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div class="form-group">
                            <label for="filter-stage" class="label">
                                <i data-feather="layers"></i>
                                Estágio
                            </label>
                            <select id="filter-stage" class="select">
                                ${generateStageFilterOptions()}
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="filter-jid" class="label">
                                <i data-feather="phone"></i>
                                Número/JID
                            </label>
                            <input type="text" id="filter-jid" class="input" placeholder="Buscar por número de telefone">
                        </div>
                        <div class="form-group">
                            <label class="label text-transparent">Ações</label>
                            <div class="flex gap-2">
                                <button type="submit" class="btn btn-primary">
                                    <i data-feather="search"></i>
                                    Buscar
                                </button>
                                <button type="button" id="clear-filters-btn" class="btn btn-outline">
                                    <i data-feather="x"></i>
                                    Limpar
                                </button>
                            </div>
                        </div>
                    </form>
                </div>
            </div>

        <div id="kanban-view" class="view-container">
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title"><i data-feather="columns"></i> Kanban de Prospects</h3>
                </div>
                <div class="card-body p-0 sm:p-2">
                    <div id="kanban-board" class="kanban-board">
                        ${generateKanbanColumnsHtml()}
                    </div>
                </div>
            </div>
        </div>
    `;
    console.log('manageProspects.js: Estrutura HTML da página de Analisar Prospects criada com visualização Kanban dinâmico.');

    document.getElementById('prospect-filters-form').addEventListener('submit', handleFilterSubmit);
    document.getElementById('clear-filters-btn').addEventListener('click', handleClearFilters);

    await loadInitialKanbanData();

    if (typeof feather !== 'undefined') {
        feather.replace();
    }
    console.log('manageProspects.js: Página de Analisar Prospects carregada e inicializada.');
}

function initializeKanbanColumnState() {
    kanbanColumnState = {};
    KANBAN_COLUMN_IDS.forEach(columnId => {
        kanbanColumnState[columnId] = { offset: 0, totalKnown: 0, isLoading: false, allLoaded: false };
    });
    console.log('manageProspects.js: Estado das colunas Kanban inicializado/resetado:', kanbanColumnState);
}

async function loadInitialKanbanData() {
    console.log('manageProspects.js: Carregando dados iniciais do Kanban para todas as colunas...');
    initializeKanbanColumnState(); 

    const jidFilter = document.getElementById('filter-jid').value.trim();
    const globalStageFilter = document.getElementById('filter-stage').value; 

    const loadPromises = KANBAN_COLUMN_IDS.map(columnId => {
        // Se um filtro global de estágio está ativo
        if (globalStageFilter) {
            // Se a coluna atual é um estágio numérico e não corresponde ao filtro, ou se é a coluna 'scheduled' e o filtro não é para 'scheduled' (improvável, mas para consistência)
            if ((typeof columnId === 'number' && parseInt(globalStageFilter) !== columnId) || 
                (columnId === 'scheduled' && globalStageFilter !== 'scheduled')) { // Adicionar uma opção "scheduled" ao filtro de estágio se necessário
                const columnCardsContainer = document.getElementById(`kanban-cards-${columnId}`);
                const columnCountSpan = document.getElementById(`column-count-${columnId}`);
                if (columnCardsContainer) columnCardsContainer.innerHTML = '<p class="text-muted text-center" style="font-size:0.9em;">Filtrado</p>';
                if (columnCountSpan) columnCountSpan.textContent = '0';
                if (kanbanColumnState[columnId]) {
                    kanbanColumnState[columnId].isLoading = false;
                    kanbanColumnState[columnId].allLoaded = true;
                    kanbanColumnState[columnId].offset = 0;
                    kanbanColumnState[columnId].totalKnown = 0;
                }
                updateLoadMoreButton(columnId);
                return Promise.resolve();
            }
        }
        // Para a coluna 'scheduled', o status é 'scheduled', o estágio é irrelevante para o filtro de API (ou pode ser null)
        // Para colunas de estágio numérico, o status é 'active' (ou outro, dependendo da lógica) e o estágio é o columnId
        let apiParams = { // Renomeado para apiParams para evitar conflito com a função params
            limit: INITIAL_ITEMS_PER_COLUMN,
            offset: 0,
            status: columnId === 'scheduled' ? 'scheduled' : 'active',
        };
        if (jidFilter) {
            apiParams.jid = jidFilter;
        }
        if (columnId !== 'scheduled' && columnId != null) { // Adicionada verificação para columnId não ser null
            apiParams.stage = columnId;
        }
        // Filtra chaves com valor null ou undefined antes de enviar
        const filteredParams = Object.fromEntries(Object.entries(apiParams).filter(([_, v]) => v != null && v !== ''));
        return fetchAndRenderColumnData(columnId, filteredParams, false);
    });

    try {
        await Promise.all(loadPromises);
        console.log('manageProspects.js: Todos os dados iniciais das colunas Kanban foram carregados (ou tentativas concluídas).');
    } catch (error) {
        console.error('manageProspects.js: Erro ao carregar dados iniciais de uma ou mais colunas Kanban:', error);
        // Tratar erro global se necessário, embora fetchAndRenderColumnData já trate erros por coluna.
    }
}

async function fetchAndRenderColumnData(columnId, apiParams, append = false) {
    console.log(`manageProspects.js: Buscando dados para coluna ${columnId}, params: ${JSON.stringify(apiParams)}, append: ${append}`);
    const columnState = kanbanColumnState[columnId];
    if (!columnState) {
        console.error(`manageProspects.js: Estado não inicializado para coluna ${columnId}.`);
        return;
    }
    if (columnState.isLoading || (columnState.allLoaded && append)) {
        console.log(`manageProspects.js: Coluna ${columnId} já está carregando ou todos os itens foram carregados. Abortando.`);
        return;
    }

    columnState.isLoading = true;
    const columnCardsContainer = document.getElementById(`kanban-cards-${columnId}`);
    const loadMoreBtn = document.getElementById(`load-more-${columnId}`);
    const columnCountSpan = document.getElementById(`column-count-${columnId}`);

    if (!columnCardsContainer) {
        console.error(`manageProspects.js: Container de cards para coluna ${columnId} não encontrado.`);
        columnState.isLoading = false;
        return;
    }

    if (!append) {
        columnCardsContainer.innerHTML = `<div class="spinner-container"><div class="loading-spinner"></div></div>`;
    } else if (loadMoreBtn) {
        setLoadingState(loadMoreBtn, true);
    }

    try {
        const response = await getProspectsList(apiParams);
        console.log(`manageProspects.js: Dados recebidos para coluna ${columnId}:`, response);

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
        console.error(`manageProspects.js: Erro ao buscar dados para coluna ${columnId}:`, error);
        if (!append) {
            columnCardsContainer.innerHTML = `<div class="error-message">Erro ao carregar.</div>`;
        } else {
            showFeedback(document.getElementById('global-feedback-container') || columnCardsContainer, `Erro ao carregar mais para ${getKanbanColumnName(columnId)}.`, 'error');
        }
    } finally {
        columnState.isLoading = false;
        if (loadMoreBtn) setLoadingState(loadMoreBtn, false);
        updateLoadMoreButton(columnId);
    }
}

function renderColumnCards(columnId, prospects, append) {
    console.log(`manageProspects.js: Renderizando ${prospects.length} cards para coluna ${columnId}, append: ${append}`);
    const columnCardsContainer = document.getElementById(`kanban-cards-${columnId}`);
    if (!columnCardsContainer) return;

    if (!append) {
        columnCardsContainer.innerHTML = ''; 
    }

    if (prospects.length === 0 && !append && columnCardsContainer.innerHTML === '') {
        columnCardsContainer.innerHTML = `<p class="text-muted text-center" style="font-size:0.9em;">Nenhum prospect aqui.</p>`;
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

        const card = createElement('div', {
            className: 'kanban-card',
            'data-jid': prospect.jid,
            'data-funnel-id': prospect.funnel_id || currentFunnelId
        }, [
            createElement('div', { className: 'kanban-card-header' }, [
                avatarElement,
                createElement('h5', { className: 'kanban-card-title' }, displayName),
                createElement('div', { className: 'kanban-card-header-actions' }, [
                    createElement('button', {
                        className: 'btn btn-icon view-history-btn',
                        title: 'Ver Histórico',
                        dataset: { jid: prospect.jid }
                    }, [createElement('i', { 'data-feather': 'message-square' })]),
                    availableFunnels.length > 1 ? createElement('button', {
                        className: 'btn btn-icon funnel-menu-btn',
                        title: 'Mudar de Funil',
                        dataset: { jid: prospect.jid, funnelId: prospect.funnel_id || currentFunnelId }
                    }, [createElement('i', { 'data-feather': 'more-vertical' })]) : null
                ].filter(Boolean))
            ]),
            createElement('div', { className: 'kanban-card-body' }, [
                createElement('p', { className: 'kanban-card-detail' }, [
                    createElement('i', { 'data-feather': 'phone' }),
                    formatJidToDisplay(prospect.jid)
                ]),
                createElement('p', { className: 'kanban-card-detail' }, [
                    createElement('i', { 'data-feather': 'info' }),
                    `Status: ${getStatusName(prospect.status)}`
                ]),
            ]),
            createElement('div', { className: 'kanban-card-footer' }, [
                createElement('div', { className: 'kanban-card-llm-status' }, [
                    createElement('span', { className: `llm-status-indicator ${prospect.llm_paused ? 'is-paused' : 'is-active'}` }),
                    createElement('span', { id: `llm-status-text-${prospect.jid}` }, `LLM ${prospect.llm_paused ? 'Pausado' : 'Ativo'}`)
                ]),
                createElement('div', { className: 'kanban-card-actions' }, [
                    createElement('button', {
                        className: `btn ${prospect.llm_paused ? 'btn-success' : 'btn-warning'} toggle-llm-pause-btn`,
                        title: prospect.llm_paused ? 'Reativar LLM' : 'Pausar LLM',
                        dataset: { jid: prospect.jid, currentLlmPaused: prospect.llm_paused.toString() } 
                    }, [createElement('i', { 'data-feather': prospect.llm_paused ? 'play' : 'pause' })])
                ])
            ])
        ]);
        columnCardsContainer.appendChild(card);
    });

    columnCardsContainer.querySelectorAll('.view-history-btn:not(.listener-added)').forEach(button => {
        button.addEventListener('click', (event) => {
            const jid = event.currentTarget.dataset.jid;
            if (jid) showProspectHistory(jid);
        });
        button.classList.add('listener-added');
    });

    columnCardsContainer.querySelectorAll('.toggle-llm-pause-btn:not(.listener-added)').forEach(button => {
        button.addEventListener('click', handleToggleLLMPause);
        button.classList.add('listener-added');
    });

    // Add event listeners for funnel menu buttons
    columnCardsContainer.querySelectorAll('.funnel-menu-btn:not(.listener-added)').forEach(button => {
        button.addEventListener('click', (event) => {
            const jid = event.currentTarget.dataset.jid;
            const funnelId = event.currentTarget.dataset.funnelId;
            showCardContextMenu(event, jid, funnelId);
        });
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
        console.warn(`manageProspects.js: updateLoadMoreButton - Não foi possível encontrar o container de cards ou o estado da coluna para ${columnId}.`);
        return;
    }
    
    const existingBtn = columnCardsContainer.parentNode.querySelector(`#load-more-${columnId}`);
    if (existingBtn) {
        existingBtn.removeEventListener('click', () => loadMoreForColumn(columnId)); 
        existingBtn.remove();
    }
    
    if (!columnState.allLoaded && !columnState.isLoading && columnState.totalKnown > columnState.offset) {
        const newLoadMoreBtn = createElement('button', {
            className: 'btn btn-secondary load-more-btn',
            id: `load-more-${columnId}`,
            style: 'margin-top: 10px; width: 100%;'
        }, `Carregar Mais (${columnState.totalKnown - columnState.offset} restantes)`);
        
        newLoadMoreBtn.addEventListener('click', () => loadMoreForColumn(columnId));
        columnCardsContainer.parentNode.appendChild(newLoadMoreBtn);
        console.log(`manageProspects.js: Botão "Carregar Mais" atualizado/adicionado para coluna ${columnId}.`);
    } else {
        console.log(`manageProspects.js: Botão "Carregar Mais" não necessário ou removido para coluna ${columnId}. AllLoaded: ${columnState.allLoaded}, IsLoading: ${columnState.isLoading}`);
    }
}


async function loadMoreForColumn(columnId) {
    console.log(`manageProspects.js: Carregando mais prospects para coluna ${columnId}...`);
    const columnState = kanbanColumnState[columnId];
    const jidFilter = document.getElementById('filter-jid').value.trim();
    if (columnState && !columnState.isLoading && !columnState.allLoaded) {
        let apiParams = { // Renomeado para apiParams
            limit: ITEMS_PER_LOAD_MORE,
            offset: columnState.offset,
            status: columnId === 'scheduled' ? 'scheduled' : 'active',
        };
        if (jidFilter) {
            apiParams.jid = jidFilter;
        }
        if (columnId !== 'scheduled' && columnId != null) { // Adicionada verificação para columnId não ser null
            apiParams.stage = columnId;
        }
        // Filtra chaves com valor null ou undefined antes de enviar
        const filteredParams = Object.fromEntries(Object.entries(apiParams).filter(([_, v]) => v != null && v !== ''));
        await fetchAndRenderColumnData(columnId, filteredParams, true);
    }
}

function handleFilterSubmit(event) {
    event.preventDefault();
    console.log('manageProspects.js: Formulário de filtro submetido. Recarregando dados iniciais do Kanban.');
    loadInitialKanbanData(); // Recarrega todas as colunas com os novos filtros
}

async function handleToggleLLMPause(event) {
    const button = event.currentTarget;
    const jid = button.dataset.jid;
    const currentLlmPaused = button.dataset.currentLlmPaused === 'true';
    const newLlmPausedState = !currentLlmPaused;

    console.log(`manageProspects.js: Tentando ${newLlmPausedState ? 'pausar' : 'reativar'} LLM para JID: ${jid}`);
    setLoadingState(button, true, newLlmPausedState ? 'Pausando...' : 'Reativando...');

    try {
        await toggleProspectLLMPause(jid, newLlmPausedState);
        
        // Update UI
        const statusTextElement = document.getElementById(`llm-status-text-${jid}`);
        if (statusTextElement) {
            statusTextElement.textContent = `LLM: ${newLlmPausedState ? 'Pausado' : 'Ativo'}`;
        }
        button.dataset.currentLlmPaused = newLlmPausedState.toString();
        button.textContent = newLlmPausedState ? 'Reativar' : 'Pausar';
        button.title = newLlmPausedState ? 'Reativar LLM' : 'Pausar LLM';
        button.classList.toggle('btn-success', newLlmPausedState); // Green if paused (so action is "Reativar")
        button.classList.toggle('btn-warning', !newLlmPausedState); // Yellow if active (so action is "Pausar")

        showFeedback(document.getElementById('global-feedback-container'), `LLM para ${formatJidToDisplay(jid)} ${newLlmPausedState ? 'pausado' : 'reativado'} com sucesso.`, 'success');
        setTimeout(() => clearFeedback(document.getElementById('global-feedback-container')), 3000);

    } catch (error) {
        console.error(`manageProspects.js: Erro ao ${newLlmPausedState ? 'pausar' : 'reativar'} LLM para ${jid}:`, error);
        showFeedback(document.getElementById('global-feedback-container'), `Erro ao alterar status do LLM para ${formatJidToDisplay(jid)}.`, 'error');
    } finally {
        setLoadingState(button, false, newLlmPausedState ? 'Reativar' : 'Pausar');
    }
}

function handleClearFilters() {
    console.log('manageProspects.js: Limpando filtros. Resetando formulário e recarregando dados iniciais do Kanban.');
    document.getElementById('filter-stage').value = '';
    document.getElementById('filter-jid').value = '';
    loadInitialKanbanData(); // Recarrega todas as colunas sem filtros
}

async function showProspectHistory(jid) {
    console.log(`manageProspects.js: Iniciando exibição do histórico para JID: ${jid}`);
    const historyModal = document.getElementById('prospect-history-modal');
    const historyContent = document.getElementById('prospect-history-content');
    const historyModalTitle = document.getElementById('history-modal-title');

    if (!historyModal || !historyContent || !historyModalTitle) {
        console.error('manageProspects.js: Elementos do modal de histórico não encontrados no DOM.');
        const globalFeedback = document.getElementById('global-feedback-container');
        if (globalFeedback) {
            showFeedback(globalFeedback, 'Erro ao tentar abrir o histórico: elementos do modal não encontrados.', 'error');
        }
        return;
    }

    historyModalTitle.textContent = 'Histórico de Conversa';
    historyContent.innerHTML = `<div class="spinner-container"><div class="loading-spinner"></div></div>`;
    showModal('prospect-history-modal');

    try {
        // Obtém os dados do prospect para pegar o nome e status
        const prospectsList = await getProspectsList({ jid_search: jid });
        const prospectData = prospectsList.prospects.find(p => p.jid === jid);
        const prospectName = prospectData?.name || null;
        const llmPaused = prospectData?.llm_paused || false;
        const currentStage = prospectData?.current_stage || 0;

        const response = await getProspectHistory(jid);
        historyContent.innerHTML = '';

        // Criar cabeçalho do prospect
        const displayName = prospectName || formatJidToDisplay(jid);
        const initial = (displayName || 'U').charAt(0).toUpperCase();

        const headerElement = createElement('div', { className: 'history-prospect-header' }, [
            createElement('div', { className: 'history-prospect-avatar', id: `history-avatar-${jid}` }, initial),
            createElement('div', { className: 'history-prospect-info' }, [
                createElement('h4', { className: 'history-prospect-name' }, displayName),
                createElement('span', { className: 'history-prospect-phone' }, [
                    createElement('i', { 'data-feather': 'phone' }),
                    formatJidToDisplay(jid)
                ])
            ]),
            createElement('div', { className: 'history-prospect-status' }, [
                createElement('span', { className: `llm-status-indicator ${llmPaused ? 'is-paused' : 'is-active'}` }),
                createElement('span', { className: 'badge badge-info' }, getKanbanColumnName(currentStage))
            ])
        ]);
        historyContent.appendChild(headerElement);

        // Buscar foto de perfil de forma assíncrona
        fetchProfilePictureForHistory(jid, document.getElementById(`history-avatar-${jid}`));

        // Renderizar feather icons
        if (typeof feather !== 'undefined') {
            feather.replace();
        }

        if (response.history.length === 0) {
            historyContent.appendChild(createElement('p', { className: 'text-center text-muted', style: 'padding: 2rem;' }, 'Nenhum histórico de conversa encontrado.'));
            return;
        }

        // Criar lista de mensagens
        const conversationList = createElement('ul', { className: 'conversation-history' });

        response.history.forEach(item => {
            const messageClass = item.role === 'user' ? 'user' : (item.role === 'system' ? 'system-event' : 'assistant');
            const senderLabel = item.role === 'user' ? (prospectName || 'Prospect') : (item.role === 'system' ? 'Sistema' : 'Assistente IA');

            // Criar elementos do footer (timestamp + token info)
            const footerElements = [
                createElement('span', { className: 'message-timestamp' }, formatTimestamp(item.timestamp))
            ];

            // Adicionar info de tokens se disponível
            if (item.role === 'assistant' && (item.llm_model || item.total_tokens)) {
                let tokenInfoStr = '';
                if (item.llm_model) tokenInfoStr += item.llm_model;
                if (item.total_tokens) tokenInfoStr += (tokenInfoStr ? ' • ' : '') + `${item.total_tokens} tokens`;
                if (tokenInfoStr) {
                    footerElements.push(createElement('span', { className: 'token-info' }, tokenInfoStr));
                }
            }

            const messageBubble = createElement('div', { className: 'message-bubble' }, [
                createElement('span', { className: 'message-sender' }, `${senderLabel}:`),
                createElement('span', { className: 'message-content' }, item.content),
                createElement('div', { className: 'message-footer' }, footerElements)
            ]);

            const listItem = createElement('li', { className: `message ${messageClass}` }, [messageBubble]);
            conversationList.appendChild(listItem);
        });

        historyContent.appendChild(conversationList);

        // Scroll para o final
        setTimeout(() => {
            const historyList = historyContent.querySelector('.conversation-history');
            if (historyList) {
                historyList.scrollTop = historyList.scrollHeight;
            }
        }, 100);

    } catch (error) {
        console.error(`manageProspects.js: Erro detalhado ao carregar histórico para ${jid}:`, error.message, error.stack);
        historyContent.innerHTML = `<div class="error-message">Erro ao carregar histórico. Verifique o console para detalhes.</div>`;
    }
}

// Busca foto de perfil para o header do histórico
async function fetchProfilePictureForHistory(jid, avatarElement) {
    if (!avatarElement) return;

    if (profilePictureCache.has(jid)) {
        const cachedUrl = profilePictureCache.get(jid);
        if (cachedUrl) {
            avatarElement.innerHTML = `<img src="${cachedUrl}" alt="Foto de perfil">`;
        }
        return;
    }

    try {
        const response = await getProspectProfilePicture(jid);
        const profileUrl = response?.data?.profile_picture_url;
        profilePictureCache.set(jid, profileUrl || null);
        if (profileUrl) {
            avatarElement.innerHTML = `<img src="${profileUrl}" alt="Foto de perfil">`;
        }
    } catch (error) {
        console.debug(`manageProspects.js: Erro ao buscar foto para histórico ${jid}:`, error);
    }
}

// --- Funnel Management Functions ---

// Load available funnels for the funnel selector
async function loadAvailableFunnels() {
    console.log('manageProspects.js: Carregando lista de funis disponíveis...');
    try {
        const response = await getFunnelsList();
        availableFunnels = response.funnels || [];
        console.log(`manageProspects.js: ${availableFunnels.length} funis carregados`);

        // Set current funnel to the default one
        const defaultFunnel = availableFunnels.find(f => f.is_default);
        if (defaultFunnel) {
            currentFunnelId = defaultFunnel.funnel_id;
        } else if (availableFunnels.length > 0) {
            currentFunnelId = availableFunnels[0].funnel_id;
        }

        return availableFunnels;
    } catch (error) {
        console.error('manageProspects.js: Erro ao carregar funis:', error);
        return [];
    }
}

// Create the funnel context menu for a card
function createFunnelContextMenu(jid, currentFunnelId) {
    const menu = createElement('div', { className: 'funnel-context-menu' }, [
        createElement('div', { className: 'funnel-context-menu-header' }, 'Mover para funil:'),
        createElement('ul', { className: 'funnel-context-menu-list' })
    ]);

    const list = menu.querySelector('ul');

    availableFunnels.forEach(funnel => {
        const isCurrentFunnel = funnel.funnel_id === currentFunnelId;
        const listItem = createElement('li', {
            className: `funnel-context-menu-item ${isCurrentFunnel ? 'current' : ''}`,
            dataset: { funnelId: funnel.funnel_id }
        }, [
            createElement('span', { className: 'funnel-name' }, funnel.name),
            funnel.is_default ? createElement('span', { className: 'funnel-default-badge' }, '⭐') : null,
            isCurrentFunnel ? createElement('span', { className: 'funnel-current-badge' }, '(atual)') : null
        ].filter(Boolean));

        if (!isCurrentFunnel) {
            listItem.addEventListener('click', () => {
                showChangeFunnelConfirmation(jid, funnel);
                hideContextMenu();
            });
        }

        list.appendChild(listItem);
    });

    return menu;
}

// Show the context menu for a card
function showCardContextMenu(event, jid, currentProspectFunnelId) {
    event.stopPropagation();

    // Hide any existing context menus
    hideContextMenu();

    if (availableFunnels.length <= 1) {
        showFeedback(document.getElementById('global-feedback-container'),
            'Não há outros funis disponíveis. Crie novos funis na página de configuração do funil.',
            'info');
        return;
    }

    const menu = createFunnelContextMenu(jid, currentProspectFunnelId || currentFunnelId);
    menu.id = 'active-context-menu';
    menu.dataset.jid = jid;

    // Position the menu near the button
    const buttonRect = event.currentTarget.getBoundingClientRect();
    menu.style.position = 'fixed';
    menu.style.top = `${buttonRect.bottom + 5}px`;
    menu.style.left = `${buttonRect.left - 150}px`;
    menu.style.zIndex = '9999';

    document.body.appendChild(menu);

    // Close menu on outside click
    setTimeout(() => {
        document.addEventListener('click', hideContextMenu, { once: true });
    }, 0);
}

function hideContextMenu() {
    const existingMenu = document.getElementById('active-context-menu');
    if (existingMenu) {
        existingMenu.remove();
    }
}

// Show confirmation modal for changing funnel
function showChangeFunnelConfirmation(jid, targetFunnel) {
    const displayJid = formatJidToDisplay(jid);
    const modalHtml = `
        <div id="change-funnel-modal" style="display: flex;">
            <div class="modal-overlay" onclick="document.getElementById('change-funnel-modal').remove()"></div>
            <div class="modal-content" style="max-width: 450px;">
                <div class="modal-header">
                    <h3 class="modal-title">Confirmar Mudança de Funil</h3>
                    <button type="button" class="btn-close-modal" onclick="document.getElementById('change-funnel-modal').remove()">&times;</button>
                </div>
                <div class="modal-body">
                    <p>O prospect <strong>${displayJid}</strong> será movido para:</p>
                    <p style="font-size: 1.2em; margin: 1rem 0;">
                        <strong>${targetFunnel.name}</strong> ${targetFunnel.is_default ? '⭐' : ''}
                    </p>
                    <div class="alert alert-warning" style="margin-top: 1rem;">
                        <i data-feather="alert-triangle"></i>
                        O prospect voltará para o <strong>estágio 1</strong> do novo funil.
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" onclick="document.getElementById('change-funnel-modal').remove()">Cancelar</button>
                    <button type="button" class="btn btn-primary" id="confirm-change-funnel-btn">Confirmar Mudança</button>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);

    if (typeof feather !== 'undefined') {
        feather.replace();
    }

    // Handle confirm button
    document.getElementById('confirm-change-funnel-btn').addEventListener('click', async () => {
        const confirmBtn = document.getElementById('confirm-change-funnel-btn');
        setLoadingState(confirmBtn, true);

        try {
            await updateProspectFunnel(jid, targetFunnel.funnel_id, true, null);

            // Remove the card from the current view since it's now in a different funnel
            const card = document.querySelector(`.kanban-card[data-jid="${jid}"]`);
            if (card) {
                card.remove();
            }

            showFeedback(document.getElementById('global-feedback-container'),
                `Prospect movido para "${targetFunnel.name}" com sucesso!`,
                'success');

            // Close the modal
            document.getElementById('change-funnel-modal').remove();

            // Reload kanban data to update counts
            await loadInitialKanbanData();

        } catch (error) {
            console.error('manageProspects.js: Erro ao mudar funil do prospect:', error);
            showFeedback(document.getElementById('global-feedback-container'),
                'Erro ao mudar funil: ' + error.message,
                'error');
            setLoadingState(confirmBtn, false);
        }
    });
}
