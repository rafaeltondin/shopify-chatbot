// static/js/pages/leads.js
/**
 * Página de Leads - Lista todos os leads que entraram em contato
 * Exibe nome, tags, última mensagem, status e outras informações
 */
import { getLeadsList, getLeadsStats, getProspectHistory, getTagDefinitions } from '../api.js';
import { showFeedback, clearFeedback, setLoadingState, replaceFeatherIcons, showModal, hideModal } from '../utils.js';

/**
 * Formata número de telefone para exibição
 * Ex: 5511987654321 -> +55 (11) 98765-4321
 */
function formatPhoneNumber(jid) {
    if (!jid) return '';

    // Remove @s.whatsapp.net se presente
    const cleanNumber = jid.replace('@s.whatsapp.net', '').replace(/\D/g, '');

    // Formato brasileiro: 55 + DDD (2) + número (8 ou 9)
    if (cleanNumber.startsWith('55') && cleanNumber.length >= 12) {
        const countryCode = cleanNumber.slice(0, 2);
        const ddd = cleanNumber.slice(2, 4);
        const number = cleanNumber.slice(4);

        if (number.length === 9) {
            return `+${countryCode} (${ddd}) ${number.slice(0, 5)}-${number.slice(5)}`;
        } else if (number.length === 8) {
            return `+${countryCode} (${ddd}) ${number.slice(0, 4)}-${number.slice(4)}`;
        }
    }

    // Formato genérico
    return cleanNumber;
}

// Estado da página
let currentPage = 1;
let currentLimit = 20;
let currentFilters = {};
let tagDefinitions = [];

/**
 * Carrega a página de leads
 */
export async function loadLeadsPage(container) {
    console.log('leads.js: Carregando página de Leads...');

    container.innerHTML = `
        <div class="animate-fade-in">
            <header class="page-header">
                <h1 class="page-title">
                    <span class="icon-wrapper">
                        <i data-feather="users"></i>
                    </span>
                    Leads
                </h1>
                <p class="page-subtitle">Visualize todos os leads que entraram em contato, incluindo tags, última mensagem e status.</p>
            </header>

            <!-- KPI Cards - Usando padrão do sistema -->
            <div class="kpi-grid section-spacing" id="leads-stats-container">
                <div class="kpi-card">
                    <div class="kpi-card-header">
                        <div class="kpi-card-icon-wrapper">
                            <i data-feather="users"></i>
                        </div>
                        <span class="kpi-card-label">Total de Leads</span>
                    </div>
                    <div class="kpi-card-body">
                        <div class="kpi-card-value" id="stat-total">--</div>
                    </div>
                </div>
                <div class="kpi-card kpi-success">
                    <div class="kpi-card-header">
                        <div class="kpi-card-icon-wrapper">
                            <i data-feather="check-circle"></i>
                        </div>
                        <span class="kpi-card-label">Ativos</span>
                    </div>
                    <div class="kpi-card-body">
                        <div class="kpi-card-value" id="stat-active">--</div>
                    </div>
                </div>
                <div class="kpi-card kpi-warning">
                    <div class="kpi-card-header">
                        <div class="kpi-card-icon-wrapper">
                            <i data-feather="user-check"></i>
                        </div>
                        <span class="kpi-card-label">Concluídos</span>
                    </div>
                    <div class="kpi-card-body">
                        <div class="kpi-card-value" id="stat-completed">--</div>
                    </div>
                </div>
                <div class="kpi-card kpi-secondary">
                    <div class="kpi-card-header">
                        <div class="kpi-card-icon-wrapper">
                            <i data-feather="message-circle"></i>
                        </div>
                        <span class="kpi-card-label">Iniciados pelo Lead</span>
                    </div>
                    <div class="kpi-card-body">
                        <div class="kpi-card-value" id="stat-user-initiated">--</div>
                    </div>
                </div>
            </div>

            <!-- Filtros -->
            <div class="card section-spacing">
                <div class="card-header">
                    <h3 class="card-title">
                        <i data-feather="filter"></i>
                        Filtros
                    </h3>
                    <button type="button" id="clear-filters-btn" class="btn btn-ghost btn-sm">
                        <i data-feather="x"></i>
                        Limpar
                    </button>
                </div>
                <div class="card-body">
                    <div class="filters-grid">
                        <div class="form-group">
                            <label for="filter-search" class="label">
                                <i data-feather="search"></i>
                                Buscar
                            </label>
                            <input type="text" id="filter-search" class="input" placeholder="Nome ou número...">
                        </div>
                        <div class="form-group">
                            <label for="filter-status" class="label">
                                <i data-feather="activity"></i>
                                Status
                            </label>
                            <select id="filter-status" class="select">
                                <option value="">Todos</option>
                                <option value="active">Ativo</option>
                                <option value="completed">Concluído</option>
                                <option value="failed">Falhou</option>
                                <option value="paused">Pausado</option>
                                <option value="unsubscribed">Cancelado</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="filter-tag" class="label">
                                <i data-feather="tag"></i>
                                Tag
                            </label>
                            <select id="filter-tag" class="select">
                                <option value="">Todas</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="filter-initiator" class="label">
                                <i data-feather="play"></i>
                                Iniciador
                            </label>
                            <select id="filter-initiator" class="select">
                                <option value="">Todos</option>
                                <option value="user">Lead</option>
                                <option value="llm_agent">Agente</option>
                            </select>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Lista de Leads -->
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title">
                        <i data-feather="list"></i>
                        Lista de Leads
                    </h3>
                    <div class="card-header-actions">
                        <span id="leads-count-info" class="text-muted">Carregando...</span>
                    </div>
                </div>
                <div class="card-body p-0">
                    <div id="leads-table-container" class="table-responsive">
                        <div class="spinner-container p-8">
                            <div class="loading-spinner loading-spinner-lg"></div>
                        </div>
                    </div>
                </div>
                <div class="card-footer" id="leads-pagination-container" style="display: none;">
                    <div class="pagination">
                        <button type="button" id="btn-prev-page" class="btn btn-ghost btn-sm" disabled>
                            <i data-feather="chevron-left"></i>
                            Anterior
                        </button>
                        <span id="pagination-info" class="pagination-info">Página 1 de 1</span>
                        <button type="button" id="btn-next-page" class="btn btn-ghost btn-sm" disabled>
                            Próxima
                            <i data-feather="chevron-right"></i>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    replaceFeatherIcons();

    // Carregar dados iniciais
    await Promise.all([
        loadStats(),
        loadTagDefinitions(),
        loadLeads()
    ]);

    // Configurar event listeners
    setupEventListeners();

    console.log('leads.js: Página de Leads carregada.');
}

/**
 * Carrega estatísticas dos leads
 */
async function loadStats() {
    console.log('leads.js: Carregando estatísticas...');
    try {
        const stats = await getLeadsStats();

        document.getElementById('stat-total').textContent = stats.total_leads || 0;
        document.getElementById('stat-active').textContent = stats.active_leads || 0;
        document.getElementById('stat-completed').textContent = stats.completed_leads || 0;
        document.getElementById('stat-user-initiated').textContent = stats.user_initiated || 0;

        console.log('leads.js: Estatísticas carregadas.', stats);
    } catch (error) {
        console.error('leads.js: Erro ao carregar estatísticas:', error);
    }
}

/**
 * Carrega definições de tags para o filtro
 */
async function loadTagDefinitions() {
    const startTime = Date.now();
    console.log(`[${new Date().toISOString()}] [LEADS_LOAD_TAGS] Iniciando carregamento de tags`);

    try {
        const response = await getTagDefinitions();
        // CORREÇÃO: A API retorna 'definitions', não 'tag_definitions'
        tagDefinitions = response.definitions || [];

        console.log(`[${new Date().toISOString()}] [LEADS_LOAD_TAGS] Definições recebidas:`, {
            count: tagDefinitions.length,
            tags: tagDefinitions.map(t => t.name)
        });

        const filterTag = document.getElementById('filter-tag');
        if (!filterTag) {
            console.error(`[${new Date().toISOString()}] [LEADS_LOAD_TAGS] Elemento filter-tag não encontrado`);
            return;
        }

        // Limpar opções existentes (exceto a primeira "Todas")
        while (filterTag.options.length > 1) {
            filterTag.remove(1);
        }

        // Adicionar tags ao dropdown
        tagDefinitions.forEach(tag => {
            const option = document.createElement('option');
            // Usar 'name' como valor pois é assim que as tags são armazenadas nos prospects
            option.value = tag.name;
            option.textContent = tag.name;
            filterTag.appendChild(option);
        });

        const duration = Date.now() - startTime;
        console.log(`[${new Date().toISOString()}] [LEADS_LOAD_TAGS] Sucesso em ${duration}ms - ${tagDefinitions.length} tags carregadas`);
    } catch (error) {
        console.error(`[${new Date().toISOString()}] [LEADS_LOAD_TAGS] ERRO:`, {
            message: error.message,
            stack: error.stack
        });
    }
}

/**
 * Carrega a lista de leads
 */
async function loadLeads() {
    console.log('leads.js: Carregando leads...', { page: currentPage, limit: currentLimit, filters: currentFilters });

    const tableContainer = document.getElementById('leads-table-container');
    tableContainer.innerHTML = `
        <div class="spinner-container p-8">
            <div class="loading-spinner loading-spinner-lg"></div>
        </div>
    `;

    try {
        const params = {
            page: currentPage,
            limit: currentLimit,
            ...currentFilters
        };

        const response = await getLeadsList(params);
        const { leads, total_count, total_pages } = response;

        renderLeadsTable(leads);
        updatePagination(total_count, total_pages);

        console.log('leads.js: Leads carregados:', leads.length, 'de', total_count);
    } catch (error) {
        console.error('leads.js: Erro ao carregar leads:', error);
        tableContainer.innerHTML = `
            <div class="empty-state p-8">
                <i data-feather="alert-circle" class="empty-state-icon"></i>
                <p>Erro ao carregar leads. Tente novamente.</p>
            </div>
        `;
        replaceFeatherIcons();
    }
}

/**
 * Renderiza a tabela de leads
 */
function renderLeadsTable(leads) {
    const tableContainer = document.getElementById('leads-table-container');

    if (!leads || leads.length === 0) {
        tableContainer.innerHTML = `
            <div class="empty-state p-8">
                <i data-feather="users" class="empty-state-icon"></i>
                <h3>Nenhum lead encontrado</h3>
                <p>Ainda não há leads cadastrados ou os filtros não retornaram resultados.</p>
            </div>
        `;
        replaceFeatherIcons();
        return;
    }

    const tableHTML = `
        <table class="table">
            <thead>
                <tr>
                    <th>Lead</th>
                    <th>Tags</th>
                    <th>Última Mensagem</th>
                    <th>Status</th>
                    <th>Estágio</th>
                    <th>Última Interação</th>
                    <th>Ações</th>
                </tr>
            </thead>
            <tbody>
                ${leads.map(lead => renderLeadRow(lead)).join('')}
            </tbody>
        </table>
    `;

    tableContainer.innerHTML = tableHTML;
    replaceFeatherIcons();

    // Adicionar event listeners aos botões de ação
    tableContainer.querySelectorAll('.btn-view-history').forEach(btn => {
        btn.addEventListener('click', () => {
            const jid = btn.dataset.jid;
            const name = btn.dataset.name || jid;
            openHistoryModal(jid, name);
        });
    });
}

/**
 * Renderiza uma linha da tabela de leads
 */
function renderLeadRow(lead) {
    const displayName = lead.name || formatPhoneNumber(lead.jid) || lead.jid;
    const displayPhone = formatPhoneNumber(lead.jid) || lead.jid;

    // Tags - As tags nos prospects são armazenadas pelo NOME, não pelo ID
    const tagsHTML = lead.tags && lead.tags.length > 0
        ? lead.tags.map(tagName => {
            // Buscar definição da tag pelo nome (case-insensitive)
            const tagDef = tagDefinitions.find(t => t.name && t.name.toLowerCase() === tagName.toLowerCase());
            const displayName = tagDef ? tagDef.name : tagName;
            const tagColor = tagDef ? (tagDef.color || '#6b7280') : '#6b7280';
            return `<span class="tag-badge" style="background-color: ${tagColor}20; color: ${tagColor}; border: 1px solid ${tagColor}40;">${displayName}</span>`;
        }).join('')
        : '<span class="text-muted">-</span>';

    // Última mensagem
    let lastMessageHTML = '<span class="text-muted">Sem mensagens</span>';
    if (lead.last_message) {
        const msgContent = lead.last_message.content || '';
        const truncatedMsg = msgContent.length > 50 ? msgContent.substring(0, 50) + '...' : msgContent;
        const msgRole = lead.last_message.role === 'user' ? 'Lead' : 'Agente';
        const msgIcon = lead.last_message.role === 'user' ? 'user' : 'cpu';
        lastMessageHTML = `
            <div class="last-message-preview">
                <span class="msg-sender"><i data-feather="${msgIcon}" style="width: 12px; height: 12px;"></i> ${msgRole}:</span>
                <span class="msg-content" title="${msgContent.replace(/"/g, '&quot;')}">${truncatedMsg}</span>
            </div>
        `;
    }

    // Status badge
    const statusConfig = {
        active: { label: 'Ativo', class: 'badge-success' },
        completed: { label: 'Concluído', class: 'badge-info' },
        failed: { label: 'Falhou', class: 'badge-danger' },
        paused: { label: 'Pausado', class: 'badge-warning' },
        unsubscribed: { label: 'Cancelado', class: 'badge-secondary' },
        scheduled: { label: 'Agendado', class: 'badge-primary' }
    };
    const statusInfo = statusConfig[lead.status] || { label: lead.status, class: 'badge-secondary' };

    // Estágio
    const stageHTML = `<span class="stage-badge">Estágio ${lead.current_stage}</span>`;

    // Última interação
    const lastInteraction = lead.last_interaction_at
        ? formatRelativeTime(lead.last_interaction_at)
        : '-';

    return `
        <tr>
            <td>
                <div class="lead-info">
                    <div class="lead-avatar">
                        <i data-feather="user"></i>
                    </div>
                    <div class="lead-details">
                        <span class="lead-name">${displayName}</span>
                        <span class="lead-phone">${displayPhone}</span>
                    </div>
                </div>
            </td>
            <td>
                <div class="tags-container">
                    ${tagsHTML}
                </div>
            </td>
            <td>
                ${lastMessageHTML}
            </td>
            <td>
                <span class="badge ${statusInfo.class}">${statusInfo.label}</span>
                ${lead.llm_paused ? '<span class="badge badge-warning" title="IA pausada"><i data-feather="pause" style="width: 10px; height: 10px;"></i></span>' : ''}
            </td>
            <td>
                ${stageHTML}
            </td>
            <td>
                <span class="text-muted">${lastInteraction}</span>
            </td>
            <td>
                <button type="button" class="btn btn-ghost btn-sm btn-view-history" data-jid="${lead.jid}" data-name="${lead.name || ''}" title="Ver histórico">
                    <i data-feather="message-square"></i>
                </button>
            </td>
        </tr>
    `;
}

/**
 * Formata tempo relativo
 */
function formatRelativeTime(isoString) {
    if (!isoString) return '-';

    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Agora';
    if (diffMins < 60) return `${diffMins}min atrás`;
    if (diffHours < 24) return `${diffHours}h atrás`;
    if (diffDays < 7) return `${diffDays}d atrás`;

    return date.toLocaleDateString('pt-BR');
}

/**
 * Atualiza a paginação
 */
function updatePagination(totalCount, totalPages) {
    const paginationContainer = document.getElementById('leads-pagination-container');
    const countInfo = document.getElementById('leads-count-info');
    const paginationInfo = document.getElementById('pagination-info');
    const btnPrev = document.getElementById('btn-prev-page');
    const btnNext = document.getElementById('btn-next-page');

    const startItem = ((currentPage - 1) * currentLimit) + 1;
    const endItem = Math.min(currentPage * currentLimit, totalCount);

    countInfo.textContent = `Mostrando ${startItem}-${endItem} de ${totalCount} leads`;
    paginationInfo.textContent = `Página ${currentPage} de ${totalPages || 1}`;

    btnPrev.disabled = currentPage <= 1;
    btnNext.disabled = currentPage >= totalPages;

    paginationContainer.style.display = totalCount > currentLimit ? 'block' : 'none';
}

/**
 * Busca os dados do paciente de um prospect
 */
async function getPatientData(jid) {
    try {
        const response = await fetch(`/api/prospect/${encodeURIComponent(jid)}/patient-data`, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('authToken')}`,
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            console.warn('leads.js: Erro ao buscar dados do paciente:', response.status);
            return null;
        }

        return await response.json();
    } catch (error) {
        console.error('leads.js: Erro ao buscar dados do paciente:', error);
        return null;
    }
}

/**
 * Formata CPF para exibição
 */
function formatCPF(cpf) {
    if (!cpf) return '-';
    const cleanCPF = cpf.replace(/\D/g, '');
    if (cleanCPF.length !== 11) return cpf;
    return cleanCPF.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, '$1.$2.$3-$4');
}

/**
 * Formata data de nascimento para exibição
 */
function formatBirthDate(date) {
    if (!date) return '-';
    try {
        // Se já estiver no formato DD/MM/YYYY, retorna como está
        if (date.includes('/')) return date;
        // Se estiver no formato YYYY-MM-DD, converte
        const parts = date.split('-');
        if (parts.length === 3) {
            return `${parts[2]}/${parts[1]}/${parts[0]}`;
        }
        return date;
    } catch {
        return date;
    }
}

/**
 * Calcula idade a partir da data de nascimento
 */
function calculateAge(birthDate) {
    if (!birthDate) return null;
    try {
        let dateObj;
        if (birthDate.includes('/')) {
            const parts = birthDate.split('/');
            dateObj = new Date(parts[2], parts[1] - 1, parts[0]);
        } else {
            dateObj = new Date(birthDate);
        }
        const today = new Date();
        let age = today.getFullYear() - dateObj.getFullYear();
        const monthDiff = today.getMonth() - dateObj.getMonth();
        if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < dateObj.getDate())) {
            age--;
        }
        return age;
    } catch {
        return null;
    }
}

/**
 * Gera HTML da seção de dados do paciente
 */
function generatePatientDataHTML(patientData) {
    if (!patientData || !patientData.data) {
        return `
            <div class="patient-data-section">
                <div class="patient-data-header">
                    <i data-feather="user-check"></i>
                    <span>Dados do Paciente</span>
                </div>
                <div class="patient-data-empty">
                    <p>Nenhum dado do paciente cadastrado.</p>
                </div>
            </div>
        `;
    }

    const data = patientData.data;
    const isComplete = patientData.is_complete;
    const missingFields = patientData.missing_fields || [];

    const age = calculateAge(data.birth_date);
    const ageDisplay = age !== null ? ` (${age} anos)` : '';

    const statusBadge = isComplete
        ? '<span class="badge badge-success">Completo</span>'
        : '<span class="badge badge-warning">Incompleto</span>';

    const missingFieldsHTML = missingFields.length > 0
        ? `<div class="patient-data-missing">
             <i data-feather="alert-circle"></i>
             <span>Faltam: ${missingFields.map(f => {
                 const translations = { cpf: 'CPF', full_name: 'Nome Completo', birth_date: 'Data de Nascimento' };
                 return translations[f] || f;
             }).join(', ')}</span>
           </div>`
        : '';

    return `
        <div class="patient-data-section">
            <div class="patient-data-header">
                <i data-feather="user-check"></i>
                <span>Dados do Paciente</span>
                ${statusBadge}
            </div>
            <div class="patient-data-content">
                <div class="patient-data-row">
                    <span class="patient-data-label">
                        <i data-feather="credit-card"></i>
                        CPF:
                    </span>
                    <span class="patient-data-value">${formatCPF(data.cpf)}</span>
                </div>
                <div class="patient-data-row">
                    <span class="patient-data-label">
                        <i data-feather="user"></i>
                        Nome Completo:
                    </span>
                    <span class="patient-data-value">${data.full_name || '-'}</span>
                </div>
                <div class="patient-data-row">
                    <span class="patient-data-label">
                        <i data-feather="calendar"></i>
                        Data de Nascimento:
                    </span>
                    <span class="patient-data-value">${formatBirthDate(data.birth_date)}${ageDisplay}</span>
                </div>
            </div>
            ${missingFieldsHTML}
        </div>
    `;
}

/**
 * Abre o modal de histórico
 */
async function openHistoryModal(jid, name) {
    console.log('leads.js: Abrindo histórico para:', jid);

    const modalTitle = document.getElementById('history-modal-title');
    const modalContent = document.getElementById('prospect-history-content');

    modalTitle.textContent = `Histórico - ${name || jid}`;
    modalContent.innerHTML = `
        <div class="spinner-container">
            <div class="loading-spinner"></div>
        </div>
    `;

    showModal('prospect-history-modal');

    try {
        // Buscar histórico e dados do paciente em paralelo
        const [historyResponse, patientDataResponse] = await Promise.all([
            getProspectHistory(jid),
            getPatientData(jid)
        ]);

        const history = historyResponse.history || [];

        // Gerar HTML dos dados do paciente
        const patientDataHTML = generatePatientDataHTML(patientDataResponse);

        if (history.length === 0) {
            modalContent.innerHTML = `
                ${patientDataHTML}
                <div class="empty-state">
                    <i data-feather="message-circle" class="empty-state-icon"></i>
                    <p>Nenhuma mensagem no histórico.</p>
                </div>
            `;
            replaceFeatherIcons();
            return;
        }

        const messagesHTML = history.map(msg => {
            const isUser = msg.role === 'user';
            const msgClass = isUser ? 'message-user' : 'message-assistant';
            const senderLabel = isUser ? 'Lead' : 'Agente';
            const timestamp = msg.timestamp
                ? new Date(msg.timestamp).toLocaleString('pt-BR')
                : '';

            return `
                <div class="history-message ${msgClass}">
                    <div class="message-header">
                        <span class="message-sender">${senderLabel}</span>
                        <span class="message-time">${timestamp}</span>
                    </div>
                    <div class="message-content">${msg.content || ''}</div>
                </div>
            `;
        }).join('');

        modalContent.innerHTML = `
            ${patientDataHTML}
            <div class="history-messages">
                ${messagesHTML}
            </div>
        `;

        replaceFeatherIcons();

    } catch (error) {
        console.error('leads.js: Erro ao carregar histórico:', error);
        modalContent.innerHTML = `
            <div class="empty-state">
                <i data-feather="alert-circle" class="empty-state-icon"></i>
                <p>Erro ao carregar histórico.</p>
            </div>
        `;
        replaceFeatherIcons();
    }
}

/**
 * Configura event listeners
 */
function setupEventListeners() {
    // Filtro de busca (com debounce)
    let searchTimeout;
    document.getElementById('filter-search').addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentFilters.search = e.target.value.trim() || undefined;
            currentPage = 1;
            loadLeads();
        }, 300);
    });

    // Filtro de status
    document.getElementById('filter-status').addEventListener('change', (e) => {
        currentFilters.status = e.target.value || undefined;
        currentPage = 1;
        loadLeads();
    });

    // Filtro de tag
    document.getElementById('filter-tag').addEventListener('change', (e) => {
        currentFilters.tag = e.target.value || undefined;
        currentPage = 1;
        loadLeads();
    });

    // Filtro de iniciador
    document.getElementById('filter-initiator').addEventListener('change', (e) => {
        currentFilters.initiator = e.target.value || undefined;
        currentPage = 1;
        loadLeads();
    });

    // Limpar filtros
    document.getElementById('clear-filters-btn').addEventListener('click', () => {
        document.getElementById('filter-search').value = '';
        document.getElementById('filter-status').value = '';
        document.getElementById('filter-tag').value = '';
        document.getElementById('filter-initiator').value = '';
        currentFilters = {};
        currentPage = 1;
        loadLeads();
    });

    // Paginação
    document.getElementById('btn-prev-page').addEventListener('click', () => {
        if (currentPage > 1) {
            currentPage--;
            loadLeads();
        }
    });

    document.getElementById('btn-next-page').addEventListener('click', () => {
        currentPage++;
        loadLeads();
    });

    // Modal de histórico - fechar
    document.querySelectorAll('#prospect-history-modal .modal-close-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            hideModal('prospect-history-modal');
        });
    });

    document.getElementById('prospect-history-modal-backdrop').addEventListener('click', () => {
        hideModal('prospect-history-modal');
    });
}

console.log('leads.js: Módulo carregado.');
