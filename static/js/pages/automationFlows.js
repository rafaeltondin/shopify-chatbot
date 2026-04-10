// static/js/pages/automationFlows.js
// Página de configuração de Fluxos de Automação

import { showToast, replaceFeatherIcons } from '../utils.js';

// Helper para requisições autenticadas
async function authenticatedFetch(url, options = {}) {
    const token = localStorage.getItem('innovaFluxoAuthToken');
    const headers = {
        'Content-Type': 'application/json',
        ...(options.headers || {})
    };

    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    console.log(`automationFlows.js: Fazendo requisição autenticada para ${url} (token: ${token ? 'presente' : 'ausente'})`);
    return fetch(url, { ...options, headers });
}

let automationFlows = [];
let triggerTypes = [];
let actionTypes = [];
let aiSemanticIntents = []; // Intenções semânticas para detecção por IA
let availableAudios = []; // Áudios disponíveis para ações de envio
let availableFunnels = []; // Funis disponíveis para ação de mudar funil

// Estado do histórico
let historyExecutions = [];
let historyCurrentPage = 0;
let historyPageSize = 50;
let historyHasMore = true;
let historyFilters = {
    flowId: '',
    status: '',
    jid: ''
};
let historyDebounceTimer = null;

export async function initAutomationFlowsPage() {
    console.log('automationFlows.js: Inicializando página de Fluxos de Automação...');

    const pageContainer = document.getElementById('content-area');
    if (!pageContainer) {
        console.error('automationFlows.js: Container da página não encontrado.');
        return;
    }

    pageContainer.innerHTML = getPageHTML();
    replaceFeatherIcons();

    // Configurar event listeners
    setupEventListeners();

    // Carregar dados
    await Promise.all([
        loadTriggerTypes(),
        loadActionTypes(),
        loadAiSemanticIntents(),
        loadAvailableAudios(),
        loadAvailableFunnels(),
        loadAutomationFlows()
    ]);

    console.log('automationFlows.js: Página de Fluxos inicializada com sucesso.');
}

function getPageHTML() {
    return `
        <div class="page-header">
            <div class="page-header-content">
                <h1 class="page-title">
                    <i data-feather="git-branch"></i>
                    Fluxos de Automação
                </h1>
                <p class="page-description">
                    Configure fluxos automáticos baseados em tags, inatividade, palavras-chave, detecção de IA e outros gatilhos.
                </p>
            </div>
        </div>

        <div class="automation-flows-container">
            <!-- Seção de Fluxos -->
            <section class="card flows-section">
                <header class="card-header">
                    <h2 class="card-title">
                        <i data-feather="layers"></i>
                        Fluxos Configurados
                    </h2>
                    <div class="card-header-actions">
                        <span class="badge badge-info" id="flows-count-badge">0 fluxos</span>
                        <button type="button" class="btn btn-primary btn-sm" id="add-flow-btn">
                            <i data-feather="plus"></i>
                            Novo Fluxo
                        </button>
                    </div>
                </header>
                <div class="card-body">
                    <div id="flows-list" class="flows-list">
                        <div class="spinner-container">
                            <div class="loading-spinner"></div>
                        </div>
                    </div>
                </div>
            </section>

            <!-- Seção de Histórico Completo -->
            <section class="card history-section">
                <header class="card-header">
                    <h2 class="card-title">
                        <i data-feather="clock"></i>
                        Histórico de Execuções
                    </h2>
                    <div class="card-header-actions">
                        <span class="badge badge-info" id="history-count-badge">0 execuções</span>
                        <button type="button" class="btn btn-ghost btn-sm" id="refresh-history-btn" title="Atualizar histórico">
                            <i data-feather="refresh-cw"></i>
                        </button>
                    </div>
                </header>
                <div class="card-body">
                    <!-- Filtros do Histórico -->
                    <div class="history-filters">
                        <div class="filter-group">
                            <label class="filter-label">Fluxo</label>
                            <select id="history-filter-flow" class="select select-sm">
                                <option value="">Todos os fluxos</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label class="filter-label">Status</label>
                            <select id="history-filter-status" class="select select-sm">
                                <option value="">Todos</option>
                                <option value="success">✅ Sucesso</option>
                                <option value="partial">⚠️ Parcial</option>
                                <option value="failed">❌ Falhou</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label class="filter-label">Buscar JID</label>
                            <input type="text" id="history-filter-jid" class="input input-sm" placeholder="Ex: 5511999...">
                        </div>
                    </div>

                    <!-- Lista do Histórico -->
                    <div id="history-list" class="history-list">
                        <div class="spinner-container">
                            <div class="loading-spinner"></div>
                        </div>
                    </div>

                    <!-- Paginação -->
                    <div class="history-pagination" id="history-pagination">
                        <button type="button" class="btn btn-ghost btn-sm" id="history-load-more" style="display: none;">
                            <i data-feather="chevrons-down"></i>
                            Carregar mais
                        </button>
                    </div>
                </div>
            </section>
        </div>

        <!-- Modal de Detalhes da Execução -->
        <div id="execution-detail-modal-backdrop" class="modal-backdrop" aria-hidden="true"></div>
        <div id="execution-detail-modal" class="modal modal-lg" role="dialog" aria-modal="true" aria-hidden="true">
            <div class="modal-content">
                <header class="modal-header">
                    <h3 class="modal-title">Detalhes da Execução</h3>
                    <button type="button" class="btn-icon modal-close-btn" aria-label="Fechar modal">
                        <i data-feather="x"></i>
                    </button>
                </header>
                <div class="modal-body" id="execution-detail-content">
                    <!-- Conteúdo carregado dinamicamente -->
                </div>
                <footer class="modal-footer">
                    <button type="button" class="btn btn-secondary modal-close-btn">Fechar</button>
                </footer>
            </div>
        </div>

        <!-- Modal de Edição de Fluxo -->
        <div id="edit-flow-modal-backdrop" class="modal-backdrop" aria-hidden="true"></div>
        <div id="edit-flow-modal" class="modal modal-lg" role="dialog" aria-modal="true" aria-hidden="true">
            <div class="modal-content">
                <header class="modal-header">
                    <h3 class="modal-title" id="edit-flow-modal-title">Editar Fluxo</h3>
                    <button type="button" class="btn-icon modal-close-btn" aria-label="Fechar modal">
                        <i data-feather="x"></i>
                    </button>
                </header>
                <div class="modal-body">
                    <form id="edit-flow-form" class="form">
                        <input type="hidden" id="flow-edit-id">

                        <div class="form-row form-row-status">
                            <div class="form-group flex-2">
                                <label for="flow-edit-name" class="label">Nome do Fluxo *</label>
                                <input type="text" id="flow-edit-name" class="input" required maxlength="200" placeholder="Ex: Reengajamento VIP">
                            </div>
                            <div class="form-group status-toggle-group">
                                <label class="label">Status</label>
                                <div class="status-toggle-wrapper" title="Clique para alternar o status do fluxo">
                                    <label class="switch">
                                        <input type="checkbox" id="flow-edit-enabled" checked>
                                        <span class="slider"></span>
                                    </label>
                                    <span class="status-label" id="status-label-text">Ativo</span>
                                </div>
                            </div>
                        </div>

                        <div class="form-group">
                            <label for="flow-edit-description" class="label">Descrição</label>
                            <textarea id="flow-edit-description" class="textarea" rows="2" maxlength="1000" placeholder="Descreva o objetivo deste fluxo..."></textarea>
                        </div>

                        <!-- Gatilho -->
                        <fieldset class="fieldset">
                            <legend>
                                <i data-feather="zap"></i>
                                Gatilho (O que dispara este fluxo?)
                            </legend>

                            <div class="form-row">
                                <div class="form-group">
                                    <label for="trigger-type" class="label">Tipo de Gatilho *</label>
                                    <select id="trigger-type" class="select" required>
                                        <option value="">Selecione...</option>
                                    </select>
                                </div>
                                <div class="form-group" id="trigger-config-container">
                                    <!-- Campos específicos do gatilho serão renderizados aqui -->
                                </div>
                            </div>
                        </fieldset>

                        <!-- Condições -->
                        <fieldset class="fieldset">
                            <legend>
                                <i data-feather="filter"></i>
                                Condições (Opcional - Quando executar?)
                            </legend>
                            <div id="conditions-container" class="conditions-list">
                                <!-- Condições serão adicionadas aqui -->
                            </div>
                            <button type="button" class="btn btn-ghost btn-sm" id="add-condition-btn">
                                <i data-feather="plus-circle"></i>
                                Adicionar Condição
                            </button>
                        </fieldset>

                        <!-- Ações -->
                        <fieldset class="fieldset">
                            <legend>
                                <i data-feather="play"></i>
                                Ações (O que fazer?)
                            </legend>
                            <div id="actions-container" class="actions-list">
                                <!-- Ações serão adicionadas aqui -->
                            </div>
                            <button type="button" class="btn btn-ghost btn-sm" id="add-action-btn">
                                <i data-feather="plus-circle"></i>
                                Adicionar Ação
                            </button>
                        </fieldset>
                    </form>
                </div>
                <footer class="modal-footer">
                    <button type="button" class="btn btn-secondary modal-close-btn">Cancelar</button>
                    <button type="button" class="btn btn-primary" id="save-flow-btn">
                        <i data-feather="check"></i>
                        Salvar Fluxo
                    </button>
                </footer>
            </div>
        </div>

        <style>
            /* ============================================
               AUTOMATION FLOWS - LAYOUT PRINCIPAL
               ============================================ */
            .automation-flows-container {
                display: grid;
                gap: 1.5rem;
            }

            @media (min-width: 1024px) {
                .automation-flows-container {
                    grid-template-columns: 2fr 1fr;
                }
            }

            .card-header-actions {
                display: flex;
                align-items: center;
                gap: 0.75rem;
            }

            /* ============================================
               LISTA DE FLUXOS - MINIMALISTA
               ============================================ */
            .flows-list {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
            }

            .flow-card {
                display: flex;
                align-items: center;
                gap: 0.75rem;
                padding: 0.75rem 1rem;
                background: var(--color-surface-alt);
                border: 1px solid var(--color-border);
                border-radius: var(--radius-md);
                transition: all 0.15s ease;
                position: relative;
            }

            .flow-card::before {
                content: '';
                position: absolute;
                left: 0;
                top: 50%;
                transform: translateY(-50%);
                height: 60%;
                width: 3px;
                background: #10B981;
                border-radius: 0 2px 2px 0;
                opacity: 1;
            }

            .flow-card:hover {
                background: var(--color-surface);
                border-color: var(--color-primary);
            }

            .flow-card.disabled {
                opacity: 0.5;
            }

            .flow-card.disabled::before {
                background: var(--color-text-muted);
            }

            /* Indicador de status (bolinha) */
            .flow-status-dot {
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: #10B981;
                flex-shrink: 0;
                box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);
            }

            .flow-card.disabled .flow-status-dot {
                background: #9CA3AF;
                box-shadow: 0 0 0 2px rgba(156, 163, 175, 0.2);
            }

            /* Conteúdo principal */
            .flow-main {
                flex: 1;
                min-width: 0;
                display: flex;
                flex-direction: column;
                gap: 0.125rem;
            }

            .flow-name {
                font-weight: 600;
                font-size: 0.875rem;
                color: var(--color-text);
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }

            .flow-meta {
                display: flex;
                align-items: center;
                gap: 0.75rem;
                font-size: 0.7rem;
                color: var(--color-text-muted);
            }

            .flow-meta-item {
                display: flex;
                align-items: center;
                gap: 0.25rem;
            }

            .flow-meta-item i {
                width: 11px;
                height: 11px;
                opacity: 0.6;
            }

            /* Botões de ação compactos */
            .flow-actions {
                display: flex;
                align-items: center;
                gap: 0.25rem;
                flex-shrink: 0;
            }

            .flow-action-btn {
                display: flex;
                align-items: center;
                justify-content: center;
                width: 32px;
                height: 32px;
                border: none;
                background: transparent;
                border-radius: var(--radius-sm);
                cursor: pointer;
                color: var(--color-text-muted);
                transition: all 0.15s ease;
            }

            .flow-action-btn:hover {
                background: var(--color-surface);
                color: var(--color-primary);
            }

            .flow-action-btn.danger:hover {
                background: #FEE2E2;
                color: #DC2626;
            }

            .flow-action-btn i {
                width: 16px;
                height: 16px;
            }

            /* Classes antigas mantidas para compatibilidade mas não usadas */
            .flow-header { display: none; }
            .flow-status-badge { display: none; }
            .flow-description { display: none; }
            .flow-details { display: none; }
            .flow-trigger-info { display: none; }
            .flow-actions-info { display: none; }
            .flow-actions-buttons { display: none; }

            /* ============================================
               HISTÓRICO DE EXECUÇÕES - COMPLETO
               ============================================ */

            /* Filtros do Histórico */
            .history-filters {
                display: flex;
                flex-wrap: wrap;
                gap: 0.75rem;
                padding: 1rem;
                background: var(--color-surface-alt);
                border-radius: var(--radius-md);
                margin-bottom: 1rem;
                border: 1px solid var(--color-border);
            }

            .history-filters .filter-group {
                display: flex;
                flex-direction: column;
                gap: var(--label-margin-bottom, 0.5rem);
                flex: 1;
                min-width: 140px;
            }

            .history-filters .filter-label {
                font-size: var(--font-size-xs);
                font-weight: var(--font-weight-semibold);
                color: var(--text-muted);
                text-transform: uppercase;
                letter-spacing: 0.025em;
            }

            .history-filters .select-sm,
            .history-filters .input-sm {
                height: var(--input-height-sm);
                font-size: var(--font-size-sm);
                padding: 0 var(--input-padding-x);
            }

            /* Lista do Histórico */
            .history-list {
                display: flex;
                flex-direction: column;
                gap: 0.625rem;
                max-height: 600px;
                overflow-y: auto;
                padding-right: 0.25rem;
            }

            .history-item {
                padding: 1rem;
                background: var(--color-surface-alt);
                border-radius: var(--radius-md);
                border-left: 4px solid var(--color-primary);
                transition: all 0.15s ease;
                cursor: pointer;
            }

            .history-item:hover {
                background: var(--color-surface);
                transform: translateX(4px);
                box-shadow: var(--shadow-sm);
            }

            .history-item.success {
                border-left-color: #10B981;
            }

            .history-item.partial {
                border-left-color: #F59E0B;
            }

            .history-item.failed {
                border-left-color: #EF4444;
            }

            .history-header {
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                margin-bottom: 0.5rem;
                gap: 0.5rem;
            }

            .history-header-left {
                flex: 1;
                min-width: 0;
            }

            .history-flow-name {
                font-weight: 700;
                font-size: 0.9rem;
                color: var(--color-text);
                margin-bottom: 0.25rem;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .history-flow-name i {
                width: 14px;
                height: 14px;
                color: var(--color-primary);
            }

            .history-time {
                font-size: 0.7rem;
                color: var(--color-text-muted);
                font-family: monospace;
            }

            .history-status-badge {
                display: inline-flex;
                align-items: center;
                gap: 0.25rem;
                padding: 0.25rem 0.5rem;
                border-radius: var(--radius-full);
                font-size: 0.65rem;
                font-weight: 600;
                text-transform: uppercase;
                flex-shrink: 0;
            }

            .history-status-badge.success {
                background: linear-gradient(135deg, #D1FAE5, #A7F3D0);
                color: #047857;
            }

            .history-status-badge.partial {
                background: linear-gradient(135deg, #FEF3C7, #FDE68A);
                color: #B45309;
            }

            .history-status-badge.failed {
                background: linear-gradient(135deg, #FEE2E2, #FECACA);
                color: #DC2626;
            }

            .history-status-badge i {
                width: 12px;
                height: 12px;
            }

            .history-body {
                display: flex;
                flex-wrap: wrap;
                gap: 0.75rem;
                align-items: center;
            }

            .history-info-item {
                display: flex;
                align-items: center;
                gap: 0.375rem;
                font-size: 0.75rem;
                color: var(--color-text-muted);
            }

            .history-info-item i {
                width: 12px;
                height: 12px;
                opacity: 0.7;
            }

            .history-info-item strong {
                color: var(--color-text);
                font-weight: 600;
            }

            .history-jid {
                font-family: monospace;
                background: var(--color-surface);
                padding: 0.125rem 0.375rem;
                border-radius: var(--radius-sm);
                font-size: 0.7rem;
            }

            .history-actions-count {
                display: flex;
                align-items: center;
                gap: 0.25rem;
                padding: 0.25rem 0.5rem;
                background: var(--color-surface);
                border-radius: var(--radius-sm);
                font-size: 0.7rem;
            }

            .history-view-details {
                margin-left: auto;
                font-size: 0.7rem;
                color: var(--color-primary);
                display: flex;
                align-items: center;
                gap: 0.25rem;
                opacity: 0;
                transition: opacity 0.2s ease;
            }

            .history-item:hover .history-view-details {
                opacity: 1;
            }

            /* Paginação */
            .history-pagination {
                display: flex;
                justify-content: center;
                padding-top: 1rem;
                border-top: 1px solid var(--color-border);
                margin-top: 1rem;
            }

            .history-pagination .btn {
                min-width: 150px;
            }

            /* Modal de Detalhes da Execução */
            .execution-detail-grid {
                display: grid;
                gap: 1.25rem;
            }

            .execution-detail-section {
                background: var(--color-surface-alt);
                border-radius: var(--radius-md);
                padding: 1rem;
                border: 1px solid var(--color-border);
            }

            .execution-detail-section h4 {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                font-size: 0.85rem;
                font-weight: 700;
                color: var(--color-text);
                margin-bottom: 0.75rem;
                padding-bottom: 0.5rem;
                border-bottom: 1px solid var(--color-border);
            }

            .execution-detail-section h4 i {
                width: 16px;
                height: 16px;
                color: var(--color-primary);
            }

            .execution-info-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                gap: 0.75rem;
            }

            .execution-info-item {
                display: flex;
                flex-direction: column;
                gap: 0.25rem;
            }

            .execution-info-item .info-label {
                font-size: 0.65rem;
                font-weight: 600;
                text-transform: uppercase;
                color: var(--color-text-muted);
                letter-spacing: 0.025em;
            }

            .execution-info-item .info-value {
                font-size: 0.85rem;
                color: var(--color-text);
                font-weight: 500;
            }

            .execution-info-item .info-value.mono {
                font-family: monospace;
                font-size: 0.8rem;
            }

            /* Lista de ações executadas */
            .executed-actions-list {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
            }

            .executed-action-item {
                display: flex;
                align-items: center;
                gap: 0.75rem;
                padding: 0.625rem 0.75rem;
                background: var(--color-surface);
                border-radius: var(--radius-sm);
                font-size: 0.8rem;
            }

            .executed-action-item .action-icon {
                width: 24px;
                height: 24px;
                display: flex;
                align-items: center;
                justify-content: center;
                border-radius: var(--radius-sm);
                background: var(--color-primary-light);
                font-size: 0.85rem;
            }

            .executed-action-item .action-info {
                flex: 1;
            }

            .executed-action-item .action-type-label {
                font-weight: 600;
                color: var(--color-text);
            }

            .executed-action-item .action-details {
                font-size: 0.7rem;
                color: var(--color-text-muted);
                margin-top: 0.125rem;
            }

            .executed-action-item .action-status {
                font-size: 0.75rem;
            }

            .executed-action-item .action-status.success {
                color: #10B981;
            }

            .executed-action-item .action-status.failed {
                color: #EF4444;
            }

            /* Erro da execução */
            .execution-error-box {
                padding: 0.75rem;
                background: #FEE2E2;
                border: 1px solid #FECACA;
                border-radius: var(--radius-sm);
                color: #DC2626;
                font-size: 0.8rem;
                font-family: monospace;
                white-space: pre-wrap;
                word-break: break-word;
            }

            /* ============================================
               MODAL DE EDIÇÃO DE FLUXO - PADRONIZADO
               ============================================ */
            .modal-lg .modal-content {
                max-width: 850px;
                width: 95%;
            }

            /* Usa estilos padronizados do main.css para fieldset, form-row, etc */

            /* Form Row Status - Alinhamento especial */
            .form-row-status {
                align-items: flex-end;
            }

            .form-row-status .form-group.flex-2 {
                flex: 1;
            }

            .form-row-status .status-toggle-group {
                margin-bottom: 0;
            }

            /* Switch - Design Moderno */
            .switch {
                position: relative;
                display: inline-flex;
                align-items: center;
                width: 48px;
                height: 26px;
                flex-shrink: 0;
            }

            .switch input {
                opacity: 0;
                width: 0;
                height: 0;
                position: absolute;
            }

            .slider {
                position: absolute;
                cursor: pointer;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background-color: #CBD5E1;
                transition: all 0.25s ease;
                border-radius: 26px;
            }

            .slider:before {
                position: absolute;
                content: "";
                height: 20px;
                width: 20px;
                left: 3px;
                bottom: 3px;
                background-color: white;
                transition: all 0.25s ease;
                border-radius: 50%;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.15);
            }

            .switch:hover .slider {
                background-color: #94A3B8;
            }

            input:checked + .slider {
                background: linear-gradient(135deg, #10B981, #059669);
            }

            .switch:hover input:checked + .slider {
                background: linear-gradient(135deg, #059669, #047857);
            }

            input:checked + .slider:before {
                transform: translateX(22px);
            }

            input:focus + .slider {
                box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2);
            }

            /* ============================================
               CONDIÇÕES E AÇÕES
               ============================================ */
            .conditions-list,
            .actions-list {
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
                margin-bottom: 1rem;
            }

            @keyframes slideIn {
                from {
                    opacity: 0;
                    transform: translateY(-10px);
                }
                to {
                    opacity: 1;
                    transform: translateY(0);
                }
            }

            /* Condition Item - Layout Padronizado */
            .condition-item {
                display: flex;
                flex-direction: row;
                align-items: flex-end;
                gap: var(--form-row-gap);
                padding: var(--space-4);
                background: var(--surface-primary);
                border: 1px solid var(--border-default);
                border-radius: var(--radius-md);
                animation: slideIn 0.2s ease-out;
            }

            .condition-item select,
            .condition-item input {
                flex: 1;
                height: var(--input-height-md);
                padding: 0 var(--input-padding-x);
                border: 1px solid var(--input-border);
                border-radius: var(--radius-md);
                font-size: var(--font-size-sm);
                background: var(--input-bg);
                transition: all var(--duration-fast) var(--ease);
            }

            .condition-item select:focus,
            .condition-item input:focus {
                border-color: var(--input-border-focus);
                outline: none;
                box-shadow: var(--shadow-focus-ring);
            }

            .condition-item .condition-type {
                flex: 0 0 200px;
            }

            .condition-item .condition-operator {
                flex: 0 0 120px;
            }

            .condition-item .condition-value {
                flex: 1;
            }

            .condition-item > button {
                flex: 0 0 auto;
                align-self: flex-end;
            }

            /* Action Item - Layout Padronizado */
            .action-item {
                display: flex;
                flex-direction: row;
                align-items: flex-end;
                gap: var(--form-row-gap);
                padding: var(--space-4);
                background: var(--surface-primary);
                border: 1px solid var(--border-default);
                border-radius: var(--radius-md);
            }

            .action-item > .action-type {
                flex: 0 0 180px;
                width: 180px;
            }

            .action-item > .action-config {
                flex: 1;
                display: flex;
                flex-direction: row;
                align-items: flex-end;
                gap: var(--form-row-gap);
            }

            .action-item > .action-delay {
                flex: 0 0 90px;
                width: 90px;
            }

            .action-item > button {
                flex: 0 0 auto;
                align-self: flex-end;
            }

            /* Campo dentro do action-config */
            .action-item .action-config .field-group {
                flex: 1;
                display: flex;
                flex-direction: column;
                gap: var(--label-margin-bottom);
                min-width: 0;
            }

            .action-item .action-config .action-field-row {
                display: flex;
                flex-direction: row;
                gap: var(--form-row-gap);
                width: 100%;
            }

            .action-item .action-config .action-field-row .field-group {
                flex: 1;
            }

            .action-item .action-config label.field-label {
                font-size: var(--font-size-xs);
                font-weight: var(--font-weight-semibold);
                color: var(--text-muted);
                text-transform: uppercase;
                letter-spacing: 0.025em;
                white-space: nowrap;
            }

            .action-item .action-config select,
            .action-item .action-config input,
            .action-item .action-config textarea {
                width: 100%;
                height: var(--input-height-md);
                padding: 0 var(--input-padding-x);
                border: 1px solid var(--input-border);
                border-radius: var(--radius-md);
                font-size: var(--font-size-sm);
                background: var(--input-bg);
                transition: all var(--duration-fast) var(--ease);
            }

            .action-item .action-config select:focus,
            .action-item .action-config input:focus,
            .action-item .action-config textarea:focus {
                border-color: var(--input-border-focus);
                outline: none;
                box-shadow: var(--shadow-focus-ring);
            }

            .action-item .action-config textarea {
                height: auto;
                min-height: var(--input-height-md);
                padding: var(--input-padding-y) var(--input-padding-x);
                resize: vertical;
            }

            /* Estilização dos selects e inputs principais */
            .action-item > .action-type,
            .action-item > .action-delay {
                height: var(--input-height-md);
                padding: 0 var(--input-padding-x);
                border: 1px solid var(--input-border);
                border-radius: var(--radius-md);
                font-size: var(--font-size-sm);
                background: var(--input-bg);
                transition: all var(--duration-fast) var(--ease);
            }

            .action-item > .action-type:focus,
            .action-item > .action-delay:focus {
                border-color: var(--input-border-focus);
                outline: none;
                box-shadow: var(--shadow-focus-ring);
            }

            /* Texto muted dentro do config */
            .action-item .action-config > .text-muted {
                display: flex;
                align-items: center;
                height: var(--input-height-md);
                font-size: var(--font-size-sm);
                padding: 0 var(--space-2);
            }

            .add-item-button {
                width: 100%;
                justify-content: center;
                border: 2px dashed var(--border-default);
                background: transparent;
                padding: var(--space-3);
                transition: all var(--duration-fast) var(--ease);
            }

            .add-item-button:hover {
                border-color: var(--primary);
                background: rgba(var(--primary-rgb), 0.05);
            }

            /* ============================================
               CONFIGURAÇÃO DE GATILHO AI
               ============================================ */
            .ai-semantic-config {
                width: 100%;
            }

            .ai-semantic-config .label {
                display: flex;
                align-items: center;
                gap: var(--space-2);
                margin-bottom: var(--label-margin-bottom);
            }

            .ai-intents-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
                gap: var(--space-2);
                max-height: 280px;
                overflow-y: auto;
                padding: var(--space-3);
                background: var(--surface-primary);
                border-radius: var(--radius-md);
                border: 1px solid var(--border-default);
            }

            .ai-intent-option {
                display: flex;
                align-items: flex-start;
                gap: var(--space-2);
                padding: var(--space-3);
                border-radius: var(--radius-sm);
                cursor: pointer;
                transition: all var(--duration-fast) var(--ease);
                border: 1px solid transparent;
            }

            .ai-intent-option:hover {
                background: var(--surface-tertiary);
                border-color: var(--border-default);
            }

            .ai-intent-option input[type="checkbox"] {
                margin-top: 2px;
                flex-shrink: 0;
            }

            .ai-intent-option .intent-info {
                flex: 1;
            }

            .ai-intent-option .intent-name {
                font-size: var(--font-size-sm);
                font-weight: var(--font-weight-semibold);
                text-transform: capitalize;
                color: var(--text-primary);
            }

            .ai-intent-option .intent-desc {
                font-size: var(--font-size-xs);
                color: var(--text-muted);
                line-height: 1.3;
                margin-top: var(--space-1);
            }

            /* ============================================
               ESTADOS VAZIOS
               ============================================ */
            .empty-state {
                text-align: center;
                padding: var(--space-10) var(--space-6);
                color: var(--text-muted);
            }

            .empty-state i {
                width: var(--icon-xl);
                height: var(--icon-xl);
                margin-bottom: var(--space-4);
                opacity: 0.4;
            }

            .empty-state p {
                margin: var(--space-1) 0;
            }

            .empty-state .text-sm {
                font-size: var(--font-size-sm);
            }

            /* ============================================
               SCROLLBAR CUSTOMIZADA
               ============================================ */
            .history-list::-webkit-scrollbar,
            .ai-intents-grid::-webkit-scrollbar {
                width: 6px;
            }

            .history-list::-webkit-scrollbar-track,
            .ai-intents-grid::-webkit-scrollbar-track {
                background: var(--scrollbar-track);
                border-radius: 3px;
            }

            .history-list::-webkit-scrollbar-thumb,
            .ai-intents-grid::-webkit-scrollbar-thumb {
                background: var(--scrollbar-thumb);
                border-radius: 3px;
            }

            .history-list::-webkit-scrollbar-thumb:hover,
            .ai-intents-grid::-webkit-scrollbar-thumb:hover {
                background: var(--scrollbar-thumb-hover);
            }

            /* ============================================
               RESPONSIVIDADE
               ============================================ */
            @media (max-width: 768px) {
                .automation-flows-container {
                    grid-template-columns: 1fr;
                }

                .flow-header {
                    flex-wrap: wrap;
                }

                .form-row {
                    flex-direction: column;
                }

                .form-row .form-group,
                .form-row .form-group.flex-2 {
                    min-width: 100%;
                }

                .condition-item {
                    flex-direction: column;
                    align-items: stretch;
                }

                .condition-item .condition-type,
                .condition-item .condition-operator,
                .condition-item .condition-value {
                    flex: 1 1 100%;
                    width: 100%;
                }

                .condition-item > button {
                    align-self: flex-end;
                }

                .action-item {
                    flex-direction: column;
                    align-items: stretch;
                    gap: 0.75rem;
                }

                .action-item > .action-type,
                .action-item > .action-delay {
                    flex: 1 1 100%;
                    width: 100%;
                }

                .action-item > .action-config {
                    flex-direction: column;
                    width: 100%;
                }

                .action-item .action-config .action-field-row {
                    flex-direction: column;
                }

                .action-item > button {
                    align-self: flex-end;
                }

                .flow-actions-buttons {
                    flex-direction: column;
                }

                .flow-actions-buttons .btn {
                    width: 100%;
                }

                /* Histórico - Mobile */
                .history-filters {
                    flex-direction: column;
                }

                .history-filters .filter-group {
                    min-width: 100%;
                }

                .history-item {
                    padding: 0.875rem;
                }

                .history-header {
                    flex-direction: column;
                    gap: 0.5rem;
                }

                .history-status-badge {
                    align-self: flex-start;
                }

                .history-body {
                    flex-direction: column;
                    align-items: flex-start;
                }

                .history-view-details {
                    opacity: 1;
                    margin-left: 0;
                    margin-top: 0.5rem;
                }

                .execution-info-grid {
                    grid-template-columns: 1fr;
                }

                .modal-lg .modal-content {
                    max-height: 90vh;
                    overflow-y: auto;
                }

                .ai-intents-grid {
                    grid-template-columns: 1fr;
                }
            }

            @media (max-width: 480px) {
                .flow-card {
                    padding: 0.625rem 0.75rem;
                    gap: 0.5rem;
                }

                .flow-meta {
                    flex-direction: column;
                    align-items: flex-start;
                    gap: 0.25rem;
                }

                .flow-actions {
                    flex-direction: column;
                    gap: 0.125rem;
                }

                .flow-action-btn {
                    width: 28px;
                    height: 28px;
                }

                .flow-action-btn i {
                    width: 14px;
                    height: 14px;
                }

                .fieldset {
                    padding: 1rem;
                }

                .card-header-actions {
                    flex-direction: column;
                    align-items: flex-end;
                    gap: 0.5rem;
                }
            }

            /* ============================================
               ESTILOS ADICIONAIS
               ============================================ */
            .form-hint {
                display: block;
                font-size: 0.7rem;
                color: var(--color-text-muted);
                margin-top: 0.375rem;
                line-height: 1.3;
            }

            .checkbox-label {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                font-size: 0.85rem;
                cursor: pointer;
            }

            .text-muted {
                color: var(--color-text-muted);
            }

            .badge-info {
                background: var(--color-info-light);
                color: var(--color-info);
                padding: 0.25rem 0.625rem;
                border-radius: var(--radius-full);
                font-size: 0.7rem;
                font-weight: 600;
            }

            .label i {
                display: inline;
                vertical-align: middle;
                margin-right: 0.25rem;
            }

            /* Status Toggle - Melhorado */
            .status-toggle-group {
                min-width: 140px !important;
                flex: 0 0 140px !important;
                display: flex;
                flex-direction: column;
            }

            .status-toggle-group .label {
                margin-bottom: 0.5rem;
            }

            .status-toggle-wrapper {
                display: flex;
                align-items: center;
                gap: 0.75rem;
                height: 42px;
                padding: 0 0.75rem;
                background: var(--color-surface);
                border: 1px solid var(--color-border);
                border-radius: var(--radius-md);
                transition: all 0.2s ease;
            }

            .status-toggle-wrapper:hover {
                border-color: var(--color-primary);
                background: var(--color-surface-alt);
            }

            .status-label {
                font-size: 0.85rem;
                font-weight: 600;
                color: var(--color-success);
                min-width: 55px;
                transition: color 0.2s ease;
            }

            .status-label.inactive {
                color: var(--color-text-muted);
            }

            /* Switch - Ajustes */
            .status-toggle-wrapper .switch {
                flex-shrink: 0;
            }
        </style>
    `;
}

function setupEventListeners() {
    // Botão de adicionar novo fluxo
    const addFlowBtn = document.getElementById('add-flow-btn');
    if (addFlowBtn) {
        addFlowBtn.addEventListener('click', () => openFlowModal());
    }

    // Botão de atualizar histórico
    const refreshBtn = document.getElementById('refresh-history-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadAutomationHistory);
    }

    // Botão de salvar fluxo no modal
    const saveFlowBtn = document.getElementById('save-flow-btn');
    if (saveFlowBtn) {
        saveFlowBtn.addEventListener('click', saveFlowFromModal);
    }

    // Trigger type change
    const triggerTypeSelect = document.getElementById('trigger-type');
    if (triggerTypeSelect) {
        triggerTypeSelect.addEventListener('change', () => {
            renderTriggerConfig();
            // Limpar condições quando o gatilho mudar (elas são específicas por tipo)
            updateConditionsForTriggerType();
        });
    }

    // Status toggle change
    const statusToggle = document.getElementById('flow-edit-enabled');
    if (statusToggle) {
        statusToggle.addEventListener('change', updateStatusLabel);
    }

    // Botão de adicionar condição
    const addConditionBtn = document.getElementById('add-condition-btn');
    if (addConditionBtn) {
        addConditionBtn.addEventListener('click', () => addCondition());
    }

    // Botão de adicionar ação
    const addActionBtn = document.getElementById('add-action-btn');
    if (addActionBtn) {
        addActionBtn.addEventListener('click', () => addAction());
    }

    // Fechar modal
    document.querySelectorAll('.modal-close-btn').forEach(btn => {
        btn.addEventListener('click', closeFlowModal);
    });

    const backdrop = document.getElementById('edit-flow-modal-backdrop');
    if (backdrop) {
        backdrop.addEventListener('click', closeFlowModal);
    }

    // Enter para salvar no modal
    const modal = document.getElementById('edit-flow-modal');
    if (modal) {
        modal.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                // Não disparar se estiver em textarea
                if (e.target.tagName === 'TEXTAREA') return;

                e.preventDefault();
                saveFlowFromModal();
            }
        });
    }

    // Configurar filtros do histórico
    setupHistoryFilters();
}

async function loadTriggerTypes() {
    try {
        const response = await authenticatedFetch('/api/tags/trigger-types');
        if (response.ok) {
            const data = await response.json();
            triggerTypes = data.trigger_types || [];
            populateTriggerSelect();
        }
    } catch (error) {
        console.error('automationFlows.js: Erro ao carregar tipos de gatilho:', error);
    }
}

async function loadActionTypes() {
    try {
        const response = await authenticatedFetch('/api/tags/action-types');
        if (response.ok) {
            const data = await response.json();
            actionTypes = data.action_types || [];
        }
    } catch (error) {
        console.error('automationFlows.js: Erro ao carregar tipos de ação:', error);
    }
}

async function loadAiSemanticIntents() {
    console.log('automationFlows.js: Carregando intenções semânticas da IA...');

    try {
        const response = await authenticatedFetch('/api/tags/ai-semantic-intents');
        if (response.ok) {
            const data = await response.json();
            aiSemanticIntents = data.intents || [];
            console.log('automationFlows.js: Intenções semânticas carregadas:', aiSemanticIntents);
        }
    } catch (error) {
        console.error('automationFlows.js: Erro ao carregar intenções semânticas:', error);
        // Usar lista padrão se falhar
        aiSemanticIntents = [
            { type: 'interesse', description: 'Prospect demonstra interesse no produto/serviço' },
            { type: 'objecao', description: 'Prospect apresenta objeção ou resistência' },
            { type: 'urgencia', description: 'Prospect demonstra urgência ou necessidade imediata' },
            { type: 'duvida', description: 'Prospect tem dúvidas que precisam ser esclarecidas' },
            { type: 'preco', description: 'Prospect menciona preço, valor ou orçamento' },
            { type: 'agendamento', description: 'Prospect quer agendar reunião ou demonstração' },
            { type: 'cancelamento', description: 'Prospect menciona cancelar ou desistir' },
            { type: 'satisfacao', description: 'Prospect demonstra satisfação ou feedback positivo' },
            { type: 'insatisfacao', description: 'Prospect demonstra insatisfação ou reclamação' },
            { type: 'comparacao', description: 'Prospect compara com concorrentes' },
            { type: 'decisor', description: 'Prospect menciona precisar consultar decisor' },
            { type: 'trial', description: 'Prospect quer testar ou fazer trial' },
            { type: 'suporte', description: 'Prospect precisa de suporte técnico' },
            { type: 'indicacao', description: 'Prospect quer indicar ou foi indicado' }
        ];
    }
}

async function loadAvailableAudios() {
    console.log('automationFlows.js: Carregando áudios disponíveis...');

    try {
        const response = await authenticatedFetch('/api/config/flow-audios');
        if (response.ok) {
            const data = await response.json();
            availableAudios = data.audios || [];
            console.log('automationFlows.js: Áudios disponíveis carregados:', availableAudios.length);
        }
    } catch (error) {
        console.error('automationFlows.js: Erro ao carregar áudios disponíveis:', error);
        availableAudios = [];
    }
}

async function loadAvailableFunnels() {
    console.log('automationFlows.js: Carregando funis disponíveis...');

    try {
        const response = await authenticatedFetch('/api/config/funnels');
        if (response.ok) {
            const data = await response.json();
            availableFunnels = data.funnels || [];
            console.log('automationFlows.js: Funis disponíveis carregados:', availableFunnels.length);
        }
    } catch (error) {
        console.error('automationFlows.js: Erro ao carregar funis disponíveis:', error);
        availableFunnels = [];
    }
}

// Função global para popular select de funis quando o campo é renderizado
window.loadFunnelOptions = function(selectElement) {
    // Esta função é chamada pelo onchange, mas na verdade precisamos popular na renderização
    // Mantemos aqui por compatibilidade, mas a lógica principal está em populateFunnelSelect
};

// Popula todos os selects de funil na página
function populateFunnelSelects() {
    const selects = document.querySelectorAll('.action-funnel-id');
    selects.forEach(select => {
        const currentValue = select.value;
        select.innerHTML = '<option value="">Selecione um funil...</option>' +
            availableFunnels.map(f =>
                `<option value="${f.funnel_id}" ${currentValue === f.funnel_id ? 'selected' : ''}>${f.name}${f.is_default ? ' ⭐' : ''}</option>`
            ).join('');
    });
}

function populateTriggerSelect() {
    const select = document.getElementById('trigger-type');
    if (!select) return;

    const existingOptions = select.innerHTML;
    select.innerHTML = '<option value="">Selecione...</option>' +
        triggerTypes.map(t => `<option value="${t.type}">${t.description}</option>`).join('');
}

async function loadAutomationFlows() {
    console.log('automationFlows.js: Carregando fluxos de automação...');

    try {
        const response = await authenticatedFetch('/api/tags/automations');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        automationFlows = data.flows || [];

        renderFlowsList();
        await loadAutomationHistory();

    } catch (error) {
        console.error('automationFlows.js: Erro ao carregar fluxos:', error);
        showToast('Erro ao carregar fluxos de automação', 'error');
    }
}

async function loadAutomationHistory(append = false) {
    console.log('automationFlows.js: Carregando histórico de automações...', { append, page: historyCurrentPage });

    const container = document.getElementById('history-list');
    const loadMoreBtn = document.getElementById('history-load-more');
    const countBadge = document.getElementById('history-count-badge');
    if (!container) return;

    // Mostrar loading
    if (!append) {
        container.innerHTML = `
            <div class="spinner-container">
                <div class="loading-spinner"></div>
            </div>
        `;
        historyExecutions = [];
        historyCurrentPage = 0;
    }

    try {
        // Construir URL com filtros
        const params = new URLSearchParams();
        params.append('limit', historyPageSize);

        if (historyFilters.flowId) {
            params.append('flow_id', historyFilters.flowId);
        }
        if (historyFilters.jid) {
            params.append('jid', historyFilters.jid);
        }

        const response = await authenticatedFetch(`/api/tags/automations/history?${params.toString()}`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        let executions = data.executions || [];

        // Filtrar por status no frontend (se o backend não suportar)
        if (historyFilters.status) {
            executions = executions.filter(e => e.status === historyFilters.status);
        }

        // Adicionar ou substituir execuções
        if (append) {
            historyExecutions = [...historyExecutions, ...executions];
        } else {
            historyExecutions = executions;
        }

        // Verificar se há mais páginas
        historyHasMore = executions.length >= historyPageSize;

        // Atualizar contador
        if (countBadge) {
            countBadge.textContent = `${historyExecutions.length} execuç${historyExecutions.length !== 1 ? 'ões' : 'ão'}`;
        }

        // Renderizar histórico
        renderHistory(historyExecutions);

        // Mostrar/ocultar botão "Carregar mais"
        if (loadMoreBtn) {
            loadMoreBtn.style.display = historyHasMore ? 'flex' : 'none';
        }

        // Popular filtro de fluxos (apenas na primeira carga)
        if (!append) {
            populateHistoryFlowFilter();
        }

    } catch (error) {
        console.error('automationFlows.js: Erro ao carregar histórico:', error);
        container.innerHTML = `
            <div class="empty-state">
                <i data-feather="alert-circle"></i>
                <p>Erro ao carregar histórico</p>
                <p class="text-sm">${error.message}</p>
            </div>
        `;
        replaceFeatherIcons();
    }
}

function populateHistoryFlowFilter() {
    const select = document.getElementById('history-filter-flow');
    if (!select) return;

    // Manter opção "Todos"
    let html = '<option value="">Todos os fluxos</option>';

    // Adicionar fluxos existentes
    automationFlows.forEach(flow => {
        html += `<option value="${flow.id}">${escapeHtml(flow.name)}</option>`;
    });

    select.innerHTML = html;
}

function setupHistoryFilters() {
    const flowFilter = document.getElementById('history-filter-flow');
    const statusFilter = document.getElementById('history-filter-status');
    const jidFilter = document.getElementById('history-filter-jid');
    const loadMoreBtn = document.getElementById('history-load-more');

    if (flowFilter) {
        flowFilter.addEventListener('change', () => {
            historyFilters.flowId = flowFilter.value;
            loadAutomationHistory(false);
        });
    }

    if (statusFilter) {
        statusFilter.addEventListener('change', () => {
            historyFilters.status = statusFilter.value;
            loadAutomationHistory(false);
        });
    }

    if (jidFilter) {
        jidFilter.addEventListener('input', () => {
            // Debounce para não fazer muitas requisições
            clearTimeout(historyDebounceTimer);
            historyDebounceTimer = setTimeout(() => {
                historyFilters.jid = jidFilter.value.trim();
                loadAutomationHistory(false);
            }, 500);
        });
    }

    if (loadMoreBtn) {
        loadMoreBtn.addEventListener('click', () => {
            historyCurrentPage++;
            loadAutomationHistory(true);
        });
    }
}

function renderFlowsList() {
    const container = document.getElementById('flows-list');
    const countBadge = document.getElementById('flows-count-badge');
    if (!container) return;

    const activeFlows = automationFlows.filter(f => f.enabled).length;

    if (countBadge) {
        countBadge.textContent = `${automationFlows.length} fluxo${automationFlows.length !== 1 ? 's' : ''} (${activeFlows} ativo${activeFlows !== 1 ? 's' : ''})`;
    }

    if (automationFlows.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <i data-feather="git-branch"></i>
                <p>Nenhum fluxo de automação configurado.</p>
                <p class="text-sm">Clique em "Novo Fluxo" para criar seu primeiro fluxo de automação.</p>
            </div>
        `;
        replaceFeatherIcons();
        return;
    }

    // Ordenar: ativos primeiro, depois por nome
    const sortedFlows = [...automationFlows].sort((a, b) => {
        if (a.enabled !== b.enabled) return b.enabled - a.enabled;
        return a.name.localeCompare(b.name);
    });

    container.innerHTML = sortedFlows.map(flow => {
        const triggerLabel = getTriggerLabelShort(flow.trigger);
        const actionsCount = flow.actions?.length || 0;

        return `
            <div class="flow-card ${flow.enabled ? '' : 'disabled'}" data-flow-id="${flow.id}">
                <span class="flow-status-dot" title="${flow.enabled ? 'Ativo' : 'Inativo'}"></span>
                <div class="flow-main">
                    <span class="flow-name">${escapeHtml(flow.name)}</span>
                    <div class="flow-meta">
                        <span class="flow-meta-item">
                            <i data-feather="zap"></i>
                            ${triggerLabel}
                        </span>
                        <span class="flow-meta-item">
                            <i data-feather="play"></i>
                            ${actionsCount} ${actionsCount === 1 ? 'ação' : 'ações'}
                        </span>
                    </div>
                </div>
                <div class="flow-actions">
                    <button type="button" class="flow-action-btn" onclick="window.editFlow('${flow.id}')" title="Editar">
                        <i data-feather="edit-2"></i>
                    </button>
                    <button type="button" class="flow-action-btn" onclick="window.toggleFlow('${flow.id}')" title="${flow.enabled ? 'Desativar' : 'Ativar'}">
                        <i data-feather="${flow.enabled ? 'pause' : 'play'}"></i>
                    </button>
                    <button type="button" class="flow-action-btn danger" onclick="window.deleteFlow('${flow.id}')" title="Excluir">
                        <i data-feather="trash-2"></i>
                    </button>
                </div>
            </div>
        `;
    }).join('');

    replaceFeatherIcons();
}

function getTriggerIcon(triggerType) {
    const icons = {
        'tag_added': 'tag',
        'tag_removed': 'tag',
        'inactivity': 'clock',
        'stage_change': 'git-branch',
        'keyword_detected': 'search',
        'message_received': 'message-circle',
        'ai_semantic': 'cpu'
    };
    return icons[triggerType] || 'zap';
}

function getTriggerLabelShort(trigger) {
    if (!trigger) return 'N/A';

    switch (trigger.type) {
        case 'tag_added':
            return `Tag +${trigger.tag || '*'}`;
        case 'tag_removed':
            return `Tag -${trigger.tag || '*'}`;
        case 'inactivity':
            return `${trigger.minutes || 0}min inativo`;
        case 'stage_change':
            return 'Mudança estágio';
        case 'keyword_detected':
            return 'Palavra-chave';
        case 'message_received':
            return 'Mensagem';
        case 'ai_semantic':
            return 'Detecção IA';
        default:
            return trigger.type || 'N/A';
    }
}

function renderHistory(executions) {
    const container = document.getElementById('history-list');
    if (!container) return;

    if (executions.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <i data-feather="clock"></i>
                <p>Nenhuma execução encontrada.</p>
                <p class="text-sm">${historyFilters.flowId || historyFilters.status || historyFilters.jid ? 'Tente ajustar os filtros.' : 'O histórico aparecerá quando os fluxos forem executados.'}</p>
            </div>
        `;
        replaceFeatherIcons();
        return;
    }

    const statusIcons = {
        'success': 'check-circle',
        'partial': 'alert-triangle',
        'failed': 'x-circle'
    };

    const statusLabels = {
        'success': 'Sucesso',
        'partial': 'Parcial',
        'failed': 'Falhou'
    };

    const triggerIcons = {
        'tag_added': 'tag',
        'tag_removed': 'tag',
        'inactivity': 'clock',
        'stage_change': 'git-branch',
        'keyword_detected': 'search',
        'message_received': 'message-circle',
        'ai_semantic': 'cpu'
    };

    container.innerHTML = executions.map((exec, index) => {
        const date = new Date(exec.executed_at);
        // Formatação com timezone America/Sao_Paulo (GMT-3)
        const timeStr = date.toLocaleString('pt-BR', {
            day: '2-digit',
            month: '2-digit',
            year: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            timeZone: 'America/Sao_Paulo'
        });

        const status = exec.status || 'success';
        const statusIcon = statusIcons[status] || 'help-circle';
        const triggerIcon = triggerIcons[exec.trigger_type] || 'zap';
        const actionsCount = Array.isArray(exec.actions_executed) ? exec.actions_executed.length : 0;

        return `
            <div class="history-item ${status}" onclick="window.showExecutionDetails(${index})" title="Clique para ver detalhes">
                <div class="history-header">
                    <div class="history-header-left">
                        <div class="history-flow-name">
                            <i data-feather="${triggerIcon}"></i>
                            ${escapeHtml(exec.flow_name || 'Fluxo desconhecido')}
                        </div>
                        <span class="history-time">${timeStr}</span>
                    </div>
                    <span class="history-status-badge ${status}">
                        <i data-feather="${statusIcon}"></i>
                        ${statusLabels[status]}
                    </span>
                </div>
                <div class="history-body">
                    <div class="history-info-item">
                        <i data-feather="user"></i>
                        <span class="history-jid">${formatJid(exec.jid)}</span>
                    </div>
                    <div class="history-info-item">
                        <i data-feather="zap"></i>
                        <span><strong>${getTriggerTypeLabel(exec.trigger_type)}</strong></span>
                    </div>
                    ${actionsCount > 0 ? `
                        <div class="history-actions-count">
                            <i data-feather="play"></i>
                            ${actionsCount} ${actionsCount === 1 ? 'ação' : 'ações'}
                        </div>
                    ` : ''}
                    <span class="history-view-details">
                        Ver detalhes
                        <i data-feather="chevron-right"></i>
                    </span>
                </div>
            </div>
        `;
    }).join('');

    replaceFeatherIcons();
}

function getTriggerTypeLabel(type) {
    const labels = {
        'tag_added': 'Tag adicionada',
        'tag_removed': 'Tag removida',
        'inactivity': 'Inatividade',
        'stage_change': 'Mudança de estágio',
        'keyword_detected': 'Palavra-chave',
        'message_received': 'Mensagem recebida',
        'ai_semantic': 'Detecção IA'
    };
    return labels[type] || type || 'Desconhecido';
}

// Função global para mostrar detalhes da execução
window.showExecutionDetails = function(index) {
    const exec = historyExecutions[index];
    if (!exec) return;

    const modal = document.getElementById('execution-detail-modal');
    const backdrop = document.getElementById('execution-detail-modal-backdrop');
    const content = document.getElementById('execution-detail-content');

    if (!modal || !backdrop || !content) return;

    const date = new Date(exec.executed_at);
    // Formatação com timezone America/Sao_Paulo (GMT-3)
    const timeStr = date.toLocaleString('pt-BR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        timeZone: 'America/Sao_Paulo'
    });

    const statusLabels = {
        'success': '✅ Sucesso',
        'partial': '⚠️ Parcial',
        'failed': '❌ Falhou'
    };

    const status = exec.status || 'success';
    const actionsExecuted = Array.isArray(exec.actions_executed) ? exec.actions_executed : [];

    content.innerHTML = `
        <div class="execution-detail-grid">
            <!-- Informações Gerais -->
            <div class="execution-detail-section">
                <h4>
                    <i data-feather="info"></i>
                    Informações Gerais
                </h4>
                <div class="execution-info-grid">
                    <div class="execution-info-item">
                        <span class="info-label">Fluxo</span>
                        <span class="info-value">${escapeHtml(exec.flow_name || 'Desconhecido')}</span>
                    </div>
                    <div class="execution-info-item">
                        <span class="info-label">Status</span>
                        <span class="info-value">${statusLabels[status]}</span>
                    </div>
                    <div class="execution-info-item">
                        <span class="info-label">Data/Hora</span>
                        <span class="info-value">${timeStr}</span>
                    </div>
                    <div class="execution-info-item">
                        <span class="info-label">JID</span>
                        <span class="info-value mono">${exec.jid || 'N/A'}</span>
                    </div>
                </div>
            </div>

            <!-- Gatilho -->
            <div class="execution-detail-section">
                <h4>
                    <i data-feather="zap"></i>
                    Gatilho
                </h4>
                <div class="execution-info-grid">
                    <div class="execution-info-item">
                        <span class="info-label">Tipo</span>
                        <span class="info-value">${getTriggerTypeLabel(exec.trigger_type)}</span>
                    </div>
                    <div class="execution-info-item">
                        <span class="info-label">Valor</span>
                        <span class="info-value mono">${escapeHtml(exec.trigger_value || 'N/A')}</span>
                    </div>
                </div>
            </div>

            <!-- Ações Executadas -->
            <div class="execution-detail-section">
                <h4>
                    <i data-feather="play"></i>
                    Ações Executadas (${actionsExecuted.length})
                </h4>
                ${actionsExecuted.length > 0 ? `
                    <div class="executed-actions-list">
                        ${actionsExecuted.map((action, i) => {
                            const actionIcon = getActionIcon(action.type);
                            const actionLabel = getActionLabel(action.type);
                            const actionDetails = getActionDetails(action);
                            const actionStatus = action.success !== false ? 'success' : 'failed';

                            return `
                                <div class="executed-action-item">
                                    <span class="action-icon">${actionIcon}</span>
                                    <div class="action-info">
                                        <span class="action-type-label">${actionLabel}</span>
                                        ${actionDetails ? `<div class="action-details">${escapeHtml(actionDetails)}</div>` : ''}
                                    </div>
                                    <span class="action-status ${actionStatus}">
                                        ${actionStatus === 'success' ? '✓' : '✗'}
                                    </span>
                                </div>
                            `;
                        }).join('')}
                    </div>
                ` : `
                    <p class="text-muted" style="font-size: 0.85rem; margin: 0;">Nenhuma ação registrada.</p>
                `}
            </div>

            ${exec.error_message ? `
                <!-- Erro -->
                <div class="execution-detail-section">
                    <h4>
                        <i data-feather="alert-circle"></i>
                        Erro
                    </h4>
                    <div class="execution-error-box">${escapeHtml(exec.error_message)}</div>
                </div>
            ` : ''}
        </div>
    `;

    modal.classList.add('is-visible');
    modal.setAttribute('aria-hidden', 'false');
    backdrop.classList.add('is-visible');
    backdrop.setAttribute('aria-hidden', 'false');
    document.body.classList.add('modal-open');

    replaceFeatherIcons();

    // Configurar fechamento do modal
    const closeButtons = modal.querySelectorAll('.modal-close-btn');
    closeButtons.forEach(btn => {
        btn.onclick = closeExecutionDetailModal;
    });
    backdrop.onclick = closeExecutionDetailModal;
};

function closeExecutionDetailModal() {
    const modal = document.getElementById('execution-detail-modal');
    const backdrop = document.getElementById('execution-detail-modal-backdrop');

    if (modal) {
        modal.classList.remove('is-visible');
        modal.setAttribute('aria-hidden', 'true');
    }
    if (backdrop) {
        backdrop.classList.remove('is-visible');
        backdrop.setAttribute('aria-hidden', 'true');
    }
    document.body.classList.remove('modal-open');
}

function getActionIcon(type) {
    const icons = {
        'send_message': '💬',
        'send_audio': '🔊',
        'add_tag': '🏷️',
        'remove_tag': '🚫',
        'change_stage': '📊',
        'change_funnel': '🔄',
        'pause_llm': '⏸️',
        'resume_llm': '▶️',
        'notify_team': '🔔',
        'assign_professional': '👤',
        'schedule_followup': '📅',
        'mark_status': '✅'
    };
    return icons[type] || '⚡';
}

function getActionLabel(type) {
    const labels = {
        'send_message': 'Enviar mensagem',
        'send_audio': 'Enviar áudio',
        'add_tag': 'Adicionar tag',
        'remove_tag': 'Remover tag',
        'change_stage': 'Mudar estágio',
        'change_funnel': 'Mudar de funil',
        'pause_llm': 'Pausar IA',
        'resume_llm': 'Retomar IA',
        'notify_team': 'Notificar equipe',
        'assign_professional': 'Atribuir profissional',
        'schedule_followup': 'Agendar follow-up',
        'mark_status': 'Marcar status'
    };
    return labels[type] || type || 'Ação';
}

function getActionDetails(action) {
    if (!action) return '';

    switch (action.type) {
        case 'send_message':
            return action.text ? `"${action.text.substring(0, 50)}${action.text.length > 50 ? '...' : ''}"` : '';
        case 'add_tag':
        case 'remove_tag':
            return action.tag ? `Tag: ${action.tag}` : '';
        case 'change_stage':
            return action.stage ? `Estágio: ${action.stage}` : '';
        case 'change_funnel':
            return action.funnel_id ? `Funil: ${action.funnel_id}` : '';
        case 'notify_team':
            return action.notify_number ? `Para: ${action.notify_number}` : '';
        case 'mark_status':
            return action.status ? `Status: ${action.status}` : '';
        default:
            return '';
    }
}

function formatJid(jid) {
    if (!jid) return 'N/A';
    // Remover @s.whatsapp.net e formatar número
    const cleaned = jid.replace('@s.whatsapp.net', '').replace('@c.us', '');
    if (cleaned.length > 11) {
        // Formato internacional: +55 11 99999-9999
        return `+${cleaned.slice(0, 2)} ${cleaned.slice(2, 4)} ${cleaned.slice(4, 9)}-${cleaned.slice(9)}`;
    }
    return cleaned;
}

function getTriggerLabel(trigger) {
    if (!trigger) return 'Não configurado';

    switch (trigger.type) {
        case 'tag_added':
            return `Tag "${trigger.tag}" adicionada`;
        case 'tag_removed':
            return `Tag "${trigger.tag}" removida`;
        case 'inactivity':
            return `${trigger.minutes} minutos de inatividade`;
        case 'stage_change':
            return `Estágio ${trigger.from_stage || '*'} -> ${trigger.to_stage || '*'}`;
        case 'keyword_detected':
            return `Palavras: ${trigger.keywords?.join(', ') || 'N/A'}`;
        case 'message_received':
            return 'Mensagem recebida';
        case 'ai_semantic':
            const instruction = trigger.custom_instruction || '';
            return `IA: ${instruction.substring(0, 40)}${instruction.length > 40 ? '...' : ''}`;
        default:
            return trigger.type;
    }
}

function updateStatusLabel() {
    const checkbox = document.getElementById('flow-edit-enabled');
    const label = document.getElementById('status-label-text');
    if (checkbox && label) {
        if (checkbox.checked) {
            label.textContent = 'Ativo';
            label.classList.remove('inactive');
        } else {
            label.textContent = 'Inativo';
            label.classList.add('inactive');
        }
    }
}

function openFlowModal(flowId = null) {
    const modal = document.getElementById('edit-flow-modal');
    const backdrop = document.getElementById('edit-flow-modal-backdrop');
    const title = document.getElementById('edit-flow-modal-title');

    if (!modal || !backdrop) return;

    // Limpar form
    document.getElementById('flow-edit-id').value = '';
    document.getElementById('flow-edit-name').value = '';
    document.getElementById('flow-edit-description').value = '';
    document.getElementById('flow-edit-enabled').checked = true;
    document.getElementById('trigger-type').value = '';
    document.getElementById('trigger-config-container').innerHTML = '';
    document.getElementById('conditions-container').innerHTML = '';
    document.getElementById('actions-container').innerHTML = '';
    updateStatusLabel();

    if (flowId) {
        const flow = automationFlows.find(f => f.id === flowId);
        if (flow) {
            title.textContent = 'Editar Fluxo';
            document.getElementById('flow-edit-id').value = flow.id;
            document.getElementById('flow-edit-name').value = flow.name;
            document.getElementById('flow-edit-description').value = flow.description || '';
            document.getElementById('flow-edit-enabled').checked = flow.enabled !== false;
            updateStatusLabel();

            // Trigger
            if (flow.trigger) {
                document.getElementById('trigger-type').value = flow.trigger.type;
                renderTriggerConfig(flow.trigger);
            }

            // Condições
            if (flow.conditions) {
                flow.conditions.forEach(cond => addCondition(cond));
            }

            // Ações
            if (flow.actions) {
                flow.actions.forEach(action => addAction(action));
            }
        }
    } else {
        title.textContent = 'Novo Fluxo';
    }

    modal.classList.add('is-visible');
    modal.setAttribute('aria-hidden', 'false');
    backdrop.classList.add('is-visible');
    backdrop.setAttribute('aria-hidden', 'false');
    document.body.classList.add('modal-open');

    replaceFeatherIcons();
}

function closeFlowModal() {
    const modal = document.getElementById('edit-flow-modal');
    const backdrop = document.getElementById('edit-flow-modal-backdrop');

    if (modal) {
        modal.classList.remove('is-visible');
        modal.setAttribute('aria-hidden', 'true');
    }
    if (backdrop) {
        backdrop.classList.remove('is-visible');
        backdrop.setAttribute('aria-hidden', 'true');
    }
    document.body.classList.remove('modal-open');
}

function renderTriggerConfig(existingTrigger = null) {
    const container = document.getElementById('trigger-config-container');
    const select = document.getElementById('trigger-type');
    if (!container || !select) return;

    const triggerType = existingTrigger?.type || select.value;
    if (!triggerType) {
        container.innerHTML = `
            <div style="padding: 1rem; background: var(--color-surface-alt); border-radius: var(--radius-md); border: 1px dashed var(--color-border); text-align: center;">
                <i data-feather="info" style="width: 16px; height: 16px; opacity: 0.5; display: inline;"></i>
                <span style="font-size: 0.8rem; color: var(--color-text-muted); margin-left: 0.5rem;">Selecione um tipo de gatilho para configurar</span>
            </div>
        `;
        replaceFeatherIcons();
        return;
    }

    let html = '';
    const selectedIntents = existingTrigger?.intents || [];

    switch (triggerType) {
        case 'ai_semantic':
            const customInstruction = existingTrigger?.custom_instruction || '';
            html = `
                <div class="ai-semantic-config">
                    <label class="label">
                        <i data-feather="cpu" style="width: 14px; height: 14px;"></i>
                        Instruções para a IA
                    </label>
                    <p class="text-muted" style="font-size: 0.75rem; margin-bottom: 0.75rem;">
                        Descreva em linguagem natural quando este fluxo deve ser executado. A IA analisará cada mensagem e executará o fluxo quando identificar o contexto descrito.
                    </p>
                    <textarea id="trigger-ai-instruction" class="textarea" rows="4" placeholder="Ex: 'Quando o prospect demonstrar interesse em agendar uma reunião, solicitar demonstração ou mencionar que quer conhecer melhor o produto'">${customInstruction}</textarea>
                    <span class="form-hint">Seja específico e claro nas instruções para melhor precisão da IA.</span>
                </div>
            `;
            break;

        case 'tag_added':
        case 'tag_removed':
            html = `
                <div class="form-group">
                    <label class="label">
                        <i data-feather="tag" style="width: 14px; height: 14px;"></i>
                        Tag
                    </label>
                    <input type="text" id="trigger-tag" class="input" placeholder="Nome da tag (ou * para qualquer tag)" value="${existingTrigger?.tag || ''}">
                    <span class="form-hint">Use * para disparar em qualquer tag ${triggerType === 'tag_added' ? 'adicionada' : 'removida'}.</span>
                </div>
            `;
            break;

        case 'inactivity':
            html = `
                <div class="form-group">
                    <label class="label">
                        <i data-feather="clock" style="width: 14px; height: 14px;"></i>
                        Minutos de inatividade
                    </label>
                    <input type="number" id="trigger-minutes" class="input" min="1" max="10080" placeholder="Ex: 60" value="${existingTrigger?.minutes || ''}">
                    <span class="form-hint">O fluxo será executado quando o prospect ficar sem responder por este período.</span>
                </div>
            `;
            break;

        case 'stage_change':
            html = `
                <div class="form-row">
                    <div class="form-group">
                        <label class="label">
                            <i data-feather="arrow-left-circle" style="width: 14px; height: 14px;"></i>
                            De estágio
                        </label>
                        <input type="number" id="trigger-from-stage" class="input" min="1" placeholder="Qualquer (opcional)" value="${existingTrigger?.from_stage || ''}">
                    </div>
                    <div class="form-group">
                        <label class="label">
                            <i data-feather="arrow-right-circle" style="width: 14px; height: 14px;"></i>
                            Para estágio
                        </label>
                        <input type="number" id="trigger-to-stage" class="input" min="1" placeholder="Qualquer (opcional)" value="${existingTrigger?.to_stage || ''}">
                    </div>
                </div>
                <span class="form-hint">Deixe vazio para "qualquer estágio". Preencha ambos para uma transição específica.</span>
            `;
            break;

        case 'keyword_detected':
            html = `
                <div class="form-group">
                    <label class="label">
                        <i data-feather="search" style="width: 14px; height: 14px;"></i>
                        Palavras-chave (separar por vírgula)
                    </label>
                    <input type="text" id="trigger-keywords" class="input" placeholder="Ex: cancelar, desistir, problema" value="${existingTrigger?.keywords?.join(', ') || ''}">
                    <label class="checkbox-label" style="margin-top: 0.5rem; display: flex; align-items: center; gap: 0.5rem; font-size: 0.8rem;">
                        <input type="checkbox" id="trigger-case-sensitive" ${existingTrigger?.case_sensitive ? 'checked' : ''}>
                        Diferenciar maiúsculas/minúsculas (case sensitive)
                    </label>
                </div>
            `;
            break;

        case 'message_received':
            html = `
                <div style="padding: 1rem; background: var(--color-surface); border-radius: var(--radius-md); border: 1px solid var(--color-border);">
                    <p class="text-muted" style="margin: 0; font-size: 0.85rem;">
                        <i data-feather="message-circle" style="width: 14px; height: 14px; display: inline; vertical-align: middle;"></i>
                        Este gatilho dispara quando <strong>qualquer mensagem</strong> é recebida do prospect.
                    </p>
                </div>
            `;
            break;
    }

    container.innerHTML = html;
    replaceFeatherIcons();
}

function formatIntentNameForFlow(intentType) {
    const nameMap = {
        'interesse': '💡 Interesse',
        'objecao': '🚫 Objeção',
        'urgencia': '⚡ Urgência',
        'duvida': '❓ Dúvida',
        'preco': '💰 Preço',
        'agendamento': '📅 Agendamento',
        'cancelamento': '❌ Cancelamento',
        'satisfacao': '😊 Satisfação',
        'insatisfacao': '😞 Insatisfação',
        'comparacao': '⚖️ Comparação',
        'decisor': '👔 Decisor',
        'trial': '🧪 Trial',
        'suporte': '🔧 Suporte',
        'indicacao': '🤝 Indicação'
    };
    return nameMap[intentType] || intentType;
}

// Função global para toggle de intenções
window.toggleAllFlowIntents = function() {
    const checkboxes = document.querySelectorAll('#trigger-ai-intents .ai-intent-checkbox');
    const allChecked = Array.from(checkboxes).every(cb => cb.checked);

    checkboxes.forEach(cb => {
        cb.checked = !allChecked;
    });
};

function getConditionsForTriggerType(triggerType) {
    // Condições base disponíveis para todos os gatilhos
    const baseConditions = [
        { value: 'has_tag', label: '🏷️ Tem tag', placeholder: 'Nome da tag' },
        { value: 'not_has_tag', label: '🚫 Não tem tag', placeholder: 'Nome da tag' },
        { value: 'stage', label: '📊 Estágio', placeholder: 'Número do estágio', hasOperator: true },
        { value: 'llm_paused', label: '⏸️ LLM pausado', placeholder: 'true ou false' }
    ];

    // Condições específicas por tipo de gatilho
    const specificConditions = {
        'tag_added': [
            ...baseConditions,
            { value: 'tag_is', label: '🏷️ Tag adicionada é', placeholder: 'Nome da tag específica' }
        ],
        'tag_removed': [
            ...baseConditions,
            { value: 'tag_was', label: '🏷️ Tag removida era', placeholder: 'Nome da tag específica' }
        ],
        'inactivity': [
            ...baseConditions,
            { value: 'inactivity_minutes', label: '⏰ Minutos inativos >=', placeholder: 'Minutos mínimos', hasOperator: true }
        ],
        'stage_change': [
            ...baseConditions,
            { value: 'from_stage', label: '📤 Veio do estágio', placeholder: 'Estágio anterior' },
            { value: 'to_stage', label: '📥 Foi para estágio', placeholder: 'Novo estágio' }
        ],
        'keyword_detected': [
            ...baseConditions,
            { value: 'keyword_matched', label: '🔍 Palavra detectada', placeholder: 'Palavra específica' },
            { value: 'message_length', label: '📝 Tamanho da mensagem >=', placeholder: 'Caracteres mínimos', hasOperator: true }
        ],
        'message_received': [
            ...baseConditions,
            { value: 'message_contains', label: '📝 Mensagem contém', placeholder: 'Texto parcial' },
            { value: 'message_type', label: '📎 Tipo de mensagem', placeholder: 'text, image, audio' }
        ],
        'ai_semantic': [
            ...baseConditions,
            { value: 'confidence_level', label: '🎯 Nível de confiança >=', placeholder: '0.0 a 1.0', hasOperator: true }
        ]
    };

    return specificConditions[triggerType] || baseConditions;
}

function addCondition(existingCondition = null) {
    const container = document.getElementById('conditions-container');
    if (!container) return;

    const conditionId = `condition-${Date.now()}`;

    // Obter o tipo de gatilho selecionado
    const triggerTypeSelect = document.getElementById('trigger-type');
    const triggerType = triggerTypeSelect?.value || '';
    const availableConditions = getConditionsForTriggerType(triggerType);

    const html = `
        <div class="condition-item" data-condition-id="${conditionId}">
            <select class="select condition-type" onchange="window.updateConditionFields('${conditionId}')">
                <option value="">Selecione a condição...</option>
                ${availableConditions.map(c => `
                    <option value="${c.value}" ${existingCondition?.type === c.value ? 'selected' : ''} data-placeholder="${c.placeholder}" data-has-operator="${c.hasOperator || false}">
                        ${c.label}
                    </option>
                `).join('')}
            </select>
            <select class="select condition-operator" ${!existingCondition?.type || !availableConditions.find(c => c.value === existingCondition?.type)?.hasOperator ? 'style="display:none;"' : ''}>
                <option value="equals" ${existingCondition?.operator === 'equals' ? 'selected' : ''}>= Igual a</option>
                <option value="greater_than" ${existingCondition?.operator === 'greater_than' ? 'selected' : ''}>&#62; Maior que</option>
                <option value="less_than" ${existingCondition?.operator === 'less_than' ? 'selected' : ''}>&#60; Menor que</option>
            </select>
            <input type="text" class="input condition-value" placeholder="${getConditionPlaceholder(existingCondition?.type, availableConditions)}" value="${existingCondition?.value || ''}">
            <button type="button" class="btn btn-ghost btn-icon btn-sm btn-danger" onclick="window.removeCondition('${conditionId}')" title="Remover condição">
                <i data-feather="trash-2"></i>
            </button>
        </div>
    `;

    container.insertAdjacentHTML('beforeend', html);
    replaceFeatherIcons();
}

function getConditionPlaceholder(type, conditions = null) {
    if (conditions) {
        const condition = conditions.find(c => c.value === type);
        if (condition) return condition.placeholder;
    }
    const placeholders = {
        'has_tag': 'Nome da tag',
        'not_has_tag': 'Nome da tag',
        'stage': 'Número do estágio',
        'llm_paused': 'true ou false'
    };
    return placeholders[type] || 'Valor';
}

window.updateConditionFields = function(conditionId) {
    const item = document.querySelector(`[data-condition-id="${conditionId}"]`);
    if (!item) return;

    const typeSelect = item.querySelector('.condition-type');
    const operatorSelect = item.querySelector('.condition-operator');
    const valueInput = item.querySelector('.condition-value');
    const selectedOption = typeSelect.options[typeSelect.selectedIndex];

    // Verificar se a condição selecionada tem operador
    const hasOperator = selectedOption?.dataset?.hasOperator === 'true';
    if (operatorSelect) {
        operatorSelect.style.display = hasOperator ? '' : 'none';
    }

    // Atualizar placeholder
    if (valueInput && selectedOption?.dataset?.placeholder) {
        valueInput.placeholder = selectedOption.dataset.placeholder;
    }
};

window.removeCondition = function(conditionId) {
    const element = document.querySelector(`[data-condition-id="${conditionId}"]`);
    if (element) {
        element.remove();
    }
};

// Função para atualizar as condições quando o tipo de gatilho mudar
function updateConditionsForTriggerType() {
    const container = document.getElementById('conditions-container');
    if (!container) return;

    // Limpar condições existentes
    container.innerHTML = '';
}

function addAction(existingAction = null) {
    const container = document.getElementById('actions-container');
    if (!container) return;

    const actionId = `action-${Date.now()}`;

    // Mapear ícones para cada tipo de ação
    const actionIcons = {
        'send_message': '💬',
        'send_audio': '🔊',
        'add_tag': '🏷️',
        'remove_tag': '🚫',
        'change_stage': '📊',
        'change_funnel': '🔄',
        'pause_llm': '⏸️',
        'resume_llm': '▶️',
        'notify_team': '🔔',
        'assign_professional': '👤',
        'schedule_followup': '📅',
        'mark_status': '✅'
    };

    const html = `
        <div class="action-item" data-action-id="${actionId}">
            <select class="select action-type" onchange="window.updateActionFields('${actionId}')">
                <option value="">Selecione...</option>
                ${actionTypes.map(t => `<option value="${t.type}" ${existingAction?.type === t.type ? 'selected' : ''}>${actionIcons[t.type] || '⚡'} ${t.description}</option>`).join('')}
            </select>
            <div class="action-config" id="${actionId}-config">
                ${renderActionConfigFields(existingAction)}
            </div>
            <input type="number" class="input action-delay" placeholder="Delay" title="Delay em milissegundos" min="0" max="300000" value="${existingAction?.delay_ms || ''}">
            <button type="button" class="btn btn-ghost btn-icon btn-sm btn-danger" onclick="window.removeAction('${actionId}')" title="Remover ação">
                <i data-feather="trash-2"></i>
            </button>
        </div>
    `;

    container.insertAdjacentHTML('beforeend', html);
    replaceFeatherIcons();
}

window.removeAction = function(actionId) {
    const element = document.querySelector(`[data-action-id="${actionId}"]`);
    if (element) {
        element.remove();
    }
};

function renderActionConfigFields(action) {
    if (!action || !action.type) return '<span class="text-muted">Selecione uma ação</span>';

    switch (action.type) {
        case 'send_message':
            return `
                <div class="field-group">
                    <label class="field-label">Mensagem</label>
                    <textarea class="textarea action-text" placeholder="Digite a mensagem a ser enviada..." rows="1">${action.text || ''}</textarea>
                </div>
            `;

        case 'send_audio':
            const audioOptions = availableAudios.length > 0
                ? availableAudios.map(a => `<option value="${a.filename}" ${action.audio_file === a.filename ? 'selected' : ''}>${a.filename} (${a.size_display})</option>`).join('')
                : '';
            return `
                <div class="field-group">
                    <label class="field-label">Arquivo de Áudio</label>
                    <select class="select action-audio-file">
                        <option value="">Selecione um áudio...</option>
                        ${audioOptions}
                    </select>
                </div>
            `;

        case 'add_tag':
        case 'remove_tag':
            return `
                <div class="field-group">
                    <label class="field-label">Nome da Tag</label>
                    <input type="text" class="input action-tag" placeholder="Ex: interessado, vip, qualificado" value="${action.tag || ''}">
                </div>
            `;

        case 'change_stage':
            return `
                <div class="field-group">
                    <label class="field-label">Estágio</label>
                    <input type="number" class="input action-stage" placeholder="1" min="1" max="20" value="${action.stage || ''}">
                </div>
            `;

        case 'change_funnel':
            // Gerar opções dos funis disponíveis
            const funnelOptions = availableFunnels.length > 0
                ? availableFunnels.map(f =>
                    `<option value="${f.funnel_id}" ${action.funnel_id === f.funnel_id ? 'selected' : ''}>${f.name}${f.is_default ? ' ⭐' : ''}</option>`
                ).join('')
                : '';
            return `
                <div class="action-field-row">
                    <div class="field-group">
                        <label class="field-label">Funil de Destino</label>
                        <select class="select action-funnel-id">
                            <option value="">Selecione um funil...</option>
                            ${funnelOptions}
                        </select>
                    </div>
                    <div class="field-group">
                        <label class="field-label">Resetar Estágio?</label>
                        <select class="select action-reset-stage">
                            <option value="true" ${action.reset_stage !== false ? 'selected' : ''}>Sim (voltar p/ estágio 1)</option>
                            <option value="false" ${action.reset_stage === false ? 'selected' : ''}>Não (manter estágio atual)</option>
                        </select>
                    </div>
                </div>
            `;

        case 'mark_status':
            return `
                <div class="field-group">
                    <label class="field-label">Novo Status</label>
                    <select class="select action-status">
                        <option value="active" ${action.status === 'active' ? 'selected' : ''}>Ativo</option>
                        <option value="paused" ${action.status === 'paused' ? 'selected' : ''}>Pausado</option>
                        <option value="completed" ${action.status === 'completed' ? 'selected' : ''}>Completado</option>
                        <option value="failed" ${action.status === 'failed' ? 'selected' : ''}>Falhou</option>
                    </select>
                </div>
            `;

        case 'notify_team':
            return `
                <div class="action-field-row">
                    <div class="field-group">
                        <label class="field-label">WhatsApp</label>
                        <input type="text" class="input action-notify-number" placeholder="5511999999999" value="${action.notify_number || ''}">
                    </div>
                    <div class="field-group">
                        <label class="field-label">Mensagem</label>
                        <input type="text" class="input action-message" placeholder="Ex: Novo lead qualificado!" value="${action.message || ''}">
                    </div>
                </div>
            `;

        case 'schedule_followup':
            return `
                <div class="action-field-row">
                    <div class="field-group">
                        <label class="field-label">Delay (min)</label>
                        <input type="number" class="input action-delay-minutes" placeholder="60" min="1" value="${action.delay_minutes || ''}">
                    </div>
                    <div class="field-group">
                        <label class="field-label">Mensagem</label>
                        <input type="text" class="input action-followup-msg" placeholder="Mensagem a ser enviada..." value="${action.message || ''}">
                    </div>
                </div>
            `;

        case 'assign_professional':
            return `
                <div class="field-group">
                    <label class="field-label">Profissional</label>
                    <input type="text" class="input action-professional" placeholder="Nome ou ID do profissional" value="${action.professional || ''}">
                </div>
            `;

        case 'pause_llm':
            return '<span class="text-muted">⏸️ Pausar IA</span>';

        case 'resume_llm':
            return '<span class="text-muted">▶️ Retomar IA</span>';

        default:
            return '<span class="text-muted">Selecione uma ação</span>';
    }
}

// Funções globais
window.editFlow = function(flowId) {
    openFlowModal(flowId);
};

window.toggleFlow = async function(flowId) {
    const flow = automationFlows.find(f => f.id === flowId);
    if (flow) {
        flow.enabled = !flow.enabled;
        renderFlowsList();

        // Auto-save: salvar automaticamente após ativar/desativar fluxo
        await saveAllFlows();
    }
};

window.deleteFlow = async function(flowId) {
    if (!confirm('Tem certeza que deseja excluir este fluxo?')) return;

    automationFlows = automationFlows.filter(f => f.id !== flowId);
    renderFlowsList();

    // Auto-save: salvar automaticamente após remover fluxo
    await saveAllFlows();
};

window.updateActionFields = function(actionId) {
    const container = document.getElementById(`${actionId}-config`);
    const select = document.querySelector(`[data-action-id="${actionId}"] .action-type`);

    if (!container || !select) return;

    container.innerHTML = renderActionConfigFields({ type: select.value });
};

async function saveFlowFromModal() {
    const id = document.getElementById('flow-edit-id').value || `flow-${Date.now()}`;
    const name = document.getElementById('flow-edit-name').value.trim();
    const description = document.getElementById('flow-edit-description').value.trim();
    const enabled = document.getElementById('flow-edit-enabled').checked;

    if (!name) {
        showToast('O nome do fluxo é obrigatório', 'error');
        return;
    }

    // Coletar trigger
    const triggerType = document.getElementById('trigger-type').value;
    if (!triggerType) {
        showToast('Selecione um tipo de gatilho', 'error');
        return;
    }

    const trigger = { type: triggerType };

    switch (triggerType) {
        case 'ai_semantic':
            // Coletar instrução customizada
            const aiInstruction = document.getElementById('trigger-ai-instruction')?.value?.trim() || '';
            if (!aiInstruction) {
                showToast('Preencha as instruções para a IA', 'error');
                return;
            }
            trigger.custom_instruction = aiInstruction;
            break;
        case 'tag_added':
        case 'tag_removed':
            trigger.tag = document.getElementById('trigger-tag')?.value || '*';
            break;
        case 'inactivity':
            trigger.minutes = parseInt(document.getElementById('trigger-minutes')?.value) || 60;
            break;
        case 'stage_change':
            const fromStage = document.getElementById('trigger-from-stage')?.value;
            const toStage = document.getElementById('trigger-to-stage')?.value;
            trigger.from_stage = fromStage === '*' ? null : parseInt(fromStage) || null;
            trigger.to_stage = toStage === '*' ? null : parseInt(toStage) || null;
            break;
        case 'keyword_detected':
            trigger.keywords = document.getElementById('trigger-keywords')?.value.split(',').map(k => k.trim()).filter(k => k) || [];
            trigger.case_sensitive = document.getElementById('trigger-case-sensitive')?.checked || false;
            break;
    }

    // Coletar condições
    const conditions = [];
    document.querySelectorAll('.condition-item').forEach(item => {
        const type = item.querySelector('.condition-type')?.value;
        const operator = item.querySelector('.condition-operator')?.value || 'equals';
        const value = item.querySelector('.condition-value')?.value;

        if (type && value) {
            conditions.push({ type, operator, value });
        }
    });

    // Coletar ações
    const actions = [];
    document.querySelectorAll('.action-item').forEach(item => {
        const type = item.querySelector('.action-type')?.value;
        const delay_ms = parseInt(item.querySelector('.action-delay')?.value) || 0;

        if (type) {
            const action = { type, delay_ms };

            switch (type) {
                case 'send_message':
                    action.text = item.querySelector('.action-text')?.value || '';
                    break;
                case 'send_audio':
                    action.audio_file = item.querySelector('.action-audio-file')?.value || '';
                    break;
                case 'add_tag':
                case 'remove_tag':
                    action.tag = item.querySelector('.action-tag')?.value || '';
                    break;
                case 'change_stage':
                    action.stage = parseInt(item.querySelector('.action-stage')?.value) || 1;
                    break;
                case 'change_funnel':
                    action.funnel_id = item.querySelector('.action-funnel-id')?.value || '';
                    action.reset_stage = item.querySelector('.action-reset-stage')?.value !== 'false';
                    break;
                case 'mark_status':
                    action.status = item.querySelector('.action-status')?.value || 'active';
                    break;
                case 'notify_team':
                    action.notify_number = item.querySelector('.action-notify-number')?.value || '';
                    action.message = item.querySelector('.action-message')?.value || '';
                    break;
                case 'assign_professional':
                    action.professional = item.querySelector('.action-professional')?.value || '';
                    break;
                case 'schedule_followup':
                    action.delay_minutes = parseInt(item.querySelector('.action-delay-minutes')?.value) || 60;
                    action.message = item.querySelector('.action-followup-msg')?.value || '';
                    break;
            }

            actions.push(action);
        }
    });

    if (actions.length === 0) {
        showToast('Adicione pelo menos uma ação', 'error');
        return;
    }

    // Validar campos obrigatórios das ações
    for (const action of actions) {
        if (action.type === 'change_funnel' && !action.funnel_id) {
            showToast('Selecione um funil de destino para a ação "Mudar de funil"', 'error');
            return;
        }
        if (action.type === 'send_message' && !action.text) {
            showToast('Digite a mensagem para a ação "Enviar mensagem"', 'error');
            return;
        }
        if (action.type === 'send_audio' && !action.audio_file) {
            showToast('Selecione um áudio para a ação "Enviar áudio"', 'error');
            return;
        }
        if ((action.type === 'add_tag' || action.type === 'remove_tag') && !action.tag) {
            showToast('Digite o nome da tag para a ação', 'error');
            return;
        }
    }

    // Montar fluxo
    const flowData = { id, name, description, enabled, trigger, conditions, actions };

    // Atualizar ou adicionar
    const existingIndex = automationFlows.findIndex(f => f.id === id);
    if (existingIndex >= 0) {
        automationFlows[existingIndex] = flowData;
    } else {
        automationFlows.push(flowData);
    }

    closeFlowModal();
    renderFlowsList();

    // Auto-save: salvar automaticamente no servidor após criar/editar fluxo
    await saveAllFlows();
}

async function saveAllFlows() {
    console.log('automationFlows.js: Salvando fluxos de automação...');

    try {
        const response = await authenticatedFetch('/api/tags/automations', {
            method: 'POST',
            body: JSON.stringify({ flows: automationFlows })
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        showToast('Fluxos de automação salvos com sucesso!', 'success');

    } catch (error) {
        console.error('automationFlows.js: Erro ao salvar fluxos:', error);
        showToast('Erro ao salvar fluxos de automação', 'error');
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
