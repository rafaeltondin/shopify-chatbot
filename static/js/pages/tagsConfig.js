// static/js/pages/tagsConfig.js
// Página de configuração de Tags e Definições

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

    console.log(`tagsConfig.js: Fazendo requisição autenticada para ${url} (token: ${token ? 'presente' : 'ausente'})`);
    return fetch(url, { ...options, headers });
}

let tagDefinitions = [];
let allTagsInUse = [];
let aiSemanticIntents = []; // Intenções semânticas disponíveis para detecção por IA

export async function initTagsConfigPage() {
    console.log('tagsConfig.js: Inicializando página de configuração de Tags...');

    const pageContainer = document.getElementById('content-area');
    if (!pageContainer) {
        console.error('tagsConfig.js: Container da página não encontrado.');
        return;
    }

    pageContainer.innerHTML = getPageHTML();
    replaceFeatherIcons();

    // Configurar event listeners
    setupEventListeners();

    // Carregar dados
    await Promise.all([
        loadTagDefinitions(),
        loadAllTagsInUse(),
        loadAiSemanticIntents()
    ]);

    console.log('tagsConfig.js: Página de Tags inicializada com sucesso.');
}

function getPageHTML() {
    return `
        <div class="page-header">
            <div class="page-header-content">
                <h1 class="page-title">
                    <i data-feather="tag"></i>
                    Configuração de Tags
                </h1>
                <p class="page-description">
                    Defina tags para categorizar seus prospects e configure gatilhos automáticos.
                </p>
            </div>
        </div>

        <div class="tags-config-container">
            <!-- Seção de Tags em Uso -->
            <section class="card tags-in-use-section">
                <header class="card-header">
                    <h2 class="card-title">
                        <i data-feather="pie-chart"></i>
                        Tags em Uso
                    </h2>
                    <span class="badge badge-info" id="tags-count-badge">0 tags</span>
                </header>
                <div class="card-body">
                    <div id="tags-in-use-container" class="tags-cloud">
                        <div class="spinner-container">
                            <div class="loading-spinner"></div>
                        </div>
                    </div>
                </div>
            </section>

            <!-- Seção de Definições de Tags -->
            <section class="card tag-definitions-section">
                <header class="card-header">
                    <h2 class="card-title">
                        <i data-feather="settings"></i>
                        Definições de Tags
                    </h2>
                    <button type="button" class="btn btn-primary btn-sm" id="add-tag-definition-btn">
                        <i data-feather="plus"></i>
                        Nova Tag
                    </button>
                </header>
                <div class="card-body">
                    <div id="tag-definitions-list" class="tag-definitions-list">
                        <div class="spinner-container">
                            <div class="loading-spinner"></div>
                        </div>
                    </div>
                </div>
            </section>
        </div>

        <!-- Modal de Prospects por Tag -->
        <div id="prospects-by-tag-modal-backdrop" class="modal-backdrop" aria-hidden="true"></div>
        <div id="prospects-by-tag-modal" class="modal modal-lg" role="dialog" aria-modal="true" aria-hidden="true">
            <div class="modal-content">
                <header class="modal-header">
                    <h3 class="modal-title" id="prospects-by-tag-modal-title">
                        <i data-feather="users"></i>
                        <span>Leads com a tag: </span>
                        <span id="prospects-tag-name" class="tag-chip-inline"></span>
                    </h3>
                    <button type="button" class="btn-icon modal-close-btn" aria-label="Fechar modal" onclick="window.closeProspectsByTagModal()">
                        <i data-feather="x"></i>
                    </button>
                </header>
                <div class="modal-body">
                    <div id="prospects-by-tag-content" class="prospects-list-container">
                        <div class="spinner-container">
                            <div class="loading-spinner"></div>
                        </div>
                    </div>
                </div>
                <footer class="modal-footer">
                    <span id="prospects-count-info" class="text-muted"></span>
                    <button type="button" class="btn btn-secondary" onclick="window.closeProspectsByTagModal()">Fechar</button>
                </footer>
            </div>
        </div>

        <!-- Modal de Edição de Tag -->
        <div id="edit-tag-modal-backdrop" class="modal-backdrop" aria-hidden="true"></div>
        <div id="edit-tag-modal" class="modal modal-lg" role="dialog" aria-modal="true" aria-hidden="true">
            <div class="modal-content">
                <header class="modal-header">
                    <h3 class="modal-title" id="edit-tag-modal-title">Editar Tag</h3>
                    <button type="button" class="btn-icon modal-close-btn" aria-label="Fechar modal">
                        <i data-feather="x"></i>
                    </button>
                </header>
                <div class="modal-body">
                    <form id="edit-tag-form" class="form">
                        <input type="hidden" id="tag-edit-id">

                        <!-- Seção de Informações Básicas -->
                        <div class="form-section">
                            <div class="form-section-header">
                                <i data-feather="info"></i>
                                <span>Informações Básicas</span>
                            </div>
                            <div class="form-row">
                                <div class="form-group flex-2">
                                    <label for="tag-edit-name" class="label">Nome da Tag *</label>
                                    <input type="text" id="tag-edit-name" class="input" required maxlength="100" placeholder="Ex: interessado, vip, aguardando">
                                    <span class="form-hint">Use nomes curtos e descritivos</span>
                                </div>
                                <div class="form-group">
                                    <label for="tag-edit-color" class="label">Cor</label>
                                    <div class="color-picker-wrapper">
                                        <input type="color" id="tag-edit-color" class="color-picker" value="#3B82F6">
                                        <span class="color-preview" id="tag-color-preview" style="background: #3B82F6;"></span>
                                        <div class="color-presets">
                                            <button type="button" class="color-preset" data-color="#EF4444" style="background: #EF4444;" title="Vermelho"></button>
                                            <button type="button" class="color-preset" data-color="#F59E0B" style="background: #F59E0B;" title="Laranja"></button>
                                            <button type="button" class="color-preset" data-color="#10B981" style="background: #10B981;" title="Verde"></button>
                                            <button type="button" class="color-preset" data-color="#3B82F6" style="background: #3B82F6;" title="Azul"></button>
                                            <button type="button" class="color-preset" data-color="#8B5CF6" style="background: #8B5CF6;" title="Roxo"></button>
                                            <button type="button" class="color-preset" data-color="#EC4899" style="background: #EC4899;" title="Rosa"></button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="form-group">
                                <label for="tag-edit-description" class="label">Descrição</label>
                                <textarea id="tag-edit-description" class="textarea" rows="2" maxlength="500" placeholder="Descreva quando usar esta tag..."></textarea>
                            </div>
                        </div>

                        <!-- Seção de Gatilhos Automáticos -->
                        <div class="form-section">
                            <div class="form-section-header">
                                <i data-feather="zap"></i>
                                <span>Gatilhos Automáticos</span>
                                <span class="badge badge-secondary" id="triggers-count-badge">0</span>
                            </div>
                            <p class="form-helper-text">
                                Configure quando esta tag deve ser aplicada automaticamente aos prospects.
                            </p>
                            <div id="auto-triggers-container" class="auto-triggers-list">
                                <!-- Gatilhos serão adicionados dinamicamente -->
                            </div>
                            <button type="button" class="btn btn-ghost btn-sm add-trigger-button" id="add-trigger-btn">
                                <i data-feather="plus-circle"></i>
                                Adicionar Gatilho
                            </button>
                        </div>
                    </form>
                </div>
                <footer class="modal-footer">
                    <button type="button" class="btn btn-secondary modal-close-btn">Cancelar</button>
                    <button type="button" class="btn btn-primary" id="save-tag-btn">
                        <i data-feather="check"></i>
                        Salvar Tag
                    </button>
                </footer>
            </div>
        </div>

        <style>
            /* ============================================
               TAGS CONFIG - LAYOUT PRINCIPAL
               ============================================ */
            .tags-config-container {
                display: grid;
                gap: 1.5rem;
            }

            @media (min-width: 1024px) {
                .tags-config-container {
                    grid-template-columns: 1fr 2fr;
                }
            }

            /* ============================================
               SEÇÃO DE TAGS EM USO
               ============================================ */
            .tags-in-use-section {
                height: fit-content;
            }

            .tags-cloud {
                display: flex;
                flex-wrap: wrap;
                gap: 0.5rem;
                min-height: 40px;
                align-content: flex-start;
            }

            .tag-chip {
                display: inline-flex;
                align-items: center;
                gap: 0.35rem;
                padding: 0.25rem 0.6rem;
                border-radius: 4px;
                font-size: 0.75rem;
                font-weight: 500;
                background: transparent;
                border: 1px solid var(--color-border);
                transition: all 0.15s ease;
                cursor: pointer;
            }

            .tag-chip:hover {
                border-color: var(--color-primary);
                background: rgba(var(--color-primary-rgb), 0.1);
                transform: translateY(-1px);
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
            }

            .tag-chip:active {
                transform: translateY(0);
            }

            .tag-chip .tag-color-dot {
                width: 6px;
                height: 6px;
                border-radius: 50%;
                flex-shrink: 0;
            }

            .tag-chip .tag-name {
                font-weight: 500;
                color: var(--color-text-muted);
            }

            .tag-chip .tag-count {
                background: var(--color-surface-alt);
                color: var(--color-text-muted);
                padding: 0 0.35rem;
                border-radius: 3px;
                font-size: 0.65rem;
                font-weight: 600;
                min-width: 16px;
                text-align: center;
            }

            /* ============================================
               LISTA DE DEFINIÇÕES DE TAGS
               ============================================ */
            .tag-definitions-list {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
            }

            .tag-definition-card {
                display: grid;
                grid-template-columns: auto 1fr auto;
                align-items: center;
                gap: 0.75rem;
                padding: 0.6rem 0.85rem;
                background: transparent;
                border: 1px solid var(--color-border);
                border-radius: 6px;
                transition: all 0.15s ease;
            }

            .tag-definition-card:hover {
                border-color: var(--color-primary);
                background: rgba(var(--color-primary-rgb), 0.02);
            }

            .tag-color-indicator {
                width: 12px;
                height: 12px;
                border-radius: 3px;
                flex-shrink: 0;
            }

            .tag-definition-info {
                flex: 1;
                min-width: 0;
            }

            .tag-definition-header {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                flex-wrap: wrap;
            }

            .tag-definition-name {
                font-weight: 600;
                font-size: 0.85rem;
                color: var(--color-text);
            }

            .tag-definition-description {
                font-size: 0.7rem;
                color: var(--color-text-muted);
                margin-top: 0.15rem;
                line-height: 1.3;
                opacity: 0.8;
            }

            .tag-definition-triggers {
                display: flex;
                flex-wrap: wrap;
                gap: 0.25rem;
                margin-top: 0.35rem;
            }

            .trigger-badge {
                display: inline-flex;
                align-items: center;
                gap: 0.2rem;
                padding: 0.1rem 0.4rem;
                background: var(--color-surface-alt);
                color: var(--color-text-muted);
                border-radius: 3px;
                font-size: 0.6rem;
                font-weight: 500;
                text-transform: uppercase;
                letter-spacing: 0.02em;
            }

            .trigger-badge i {
                width: 8px;
                height: 8px;
            }

            .trigger-badge-ai {
                background: rgba(99, 102, 241, 0.1);
                color: #6366F1;
            }

            .trigger-badge-keyword {
                background: rgba(16, 185, 129, 0.1);
                color: #10B981;
            }

            .trigger-badge-inactivity {
                background: rgba(245, 158, 11, 0.1);
                color: #F59E0B;
            }

            .trigger-badge-stage {
                background: rgba(14, 165, 233, 0.1);
                color: #0EA5E9;
            }

            .tag-definition-actions {
                display: flex;
                gap: 0.25rem;
            }

            .tag-definition-actions .btn {
                padding: 0.35rem;
                opacity: 0.6;
                transition: opacity 0.15s ease;
            }

            .tag-definition-card:hover .tag-definition-actions .btn {
                opacity: 1;
            }

            /* ============================================
               MODAL DE PROSPECTS POR TAG
               ============================================ */
            .prospects-list-container {
                max-height: 400px;
                overflow-y: auto;
            }

            .prospects-list-table {
                width: 100%;
                border-collapse: collapse;
            }

            .prospects-list-table th,
            .prospects-list-table td {
                padding: 0.6rem 0.75rem;
                text-align: left;
                border-bottom: 1px solid var(--color-border);
            }

            .prospects-list-table th {
                font-weight: 600;
                font-size: 0.7rem;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                color: var(--color-text-muted);
                background: var(--color-surface-alt);
                position: sticky;
                top: 0;
                z-index: 1;
            }

            .prospects-list-table tr:hover td {
                background: rgba(var(--color-primary-rgb), 0.05);
            }

            .prospect-row {
                cursor: pointer;
                transition: background 0.15s ease;
            }

            .prospect-name {
                font-weight: 500;
                color: var(--color-text);
            }

            .prospect-phone {
                font-family: monospace;
                font-size: 0.8rem;
                color: var(--color-text-muted);
            }

            .prospect-status-badge {
                display: inline-flex;
                align-items: center;
                padding: 0.15rem 0.5rem;
                border-radius: 4px;
                font-size: 0.65rem;
                font-weight: 500;
            }

            .prospect-status-badge.active {
                background: rgba(16, 185, 129, 0.15);
                color: #10B981;
            }

            .prospect-status-badge.inactive {
                background: rgba(107, 114, 128, 0.15);
                color: #6B7280;
            }

            .prospect-status-badge.won {
                background: rgba(59, 130, 246, 0.15);
                color: #3B82F6;
            }

            .prospect-status-badge.lost {
                background: rgba(239, 68, 68, 0.15);
                color: #EF4444;
            }

            .tag-chip-inline {
                display: inline-flex;
                align-items: center;
                gap: 0.35rem;
                padding: 0.2rem 0.5rem;
                border-radius: 4px;
                font-size: 0.75rem;
                font-weight: 600;
                background: rgba(var(--color-primary-rgb), 0.1);
                color: var(--color-primary);
                margin-left: 0.5rem;
            }

            .empty-prospects-state {
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 2rem;
                color: var(--color-text-muted);
                text-align: center;
            }

            .empty-prospects-state i {
                width: 48px;
                height: 48px;
                margin-bottom: 1rem;
                opacity: 0.5;
            }

            #prospects-count-info {
                font-size: 0.8rem;
            }

            /* ============================================
               MODAL DE EDIÇÃO
               ============================================ */
            .modal-lg .modal-content {
                max-width: 600px;
                width: 95%;
            }

            .form-section {
                background: transparent;
                border: 1px solid var(--color-border);
                border-radius: 6px;
                padding: 0.85rem;
                margin-bottom: 0.85rem;
            }

            .form-section:last-child {
                margin-bottom: 0;
            }

            .form-section-header {
                display: flex;
                align-items: center;
                gap: 0.4rem;
                font-weight: 600;
                font-size: 0.8rem;
                color: var(--color-text);
                margin-bottom: 0.75rem;
                padding-bottom: 0.5rem;
                border-bottom: 1px solid var(--color-border);
            }

            .form-section-header i {
                width: 14px;
                height: 14px;
                color: var(--color-primary);
            }

            .form-section-header .badge {
                margin-left: auto;
                font-size: 0.65rem;
                padding: 0.1rem 0.4rem;
            }

            .form-row {
                display: flex;
                gap: 0.75rem;
                flex-wrap: wrap;
            }

            .form-row .form-group {
                flex: 1;
                min-width: 180px;
            }

            .form-row .form-group.flex-2 {
                flex: 2;
                min-width: 250px;
            }

            .form-hint {
                display: block;
                font-size: 0.65rem;
                color: var(--color-text-muted);
                margin-top: 0.2rem;
                opacity: 0.7;
            }

            /* Color Picker melhorado */
            .color-picker-wrapper {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                flex-wrap: wrap;
            }

            .color-picker {
                width: 36px;
                height: 28px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                padding: 0;
            }

            .color-preview {
                width: 28px;
                height: 28px;
                border-radius: 4px;
                border: 1px solid var(--color-border);
            }

            .color-presets {
                display: flex;
                gap: 0.25rem;
            }

            .color-preset {
                width: 18px;
                height: 18px;
                border-radius: 3px;
                border: 1px solid transparent;
                cursor: pointer;
                transition: all 0.2s ease;
            }

            .color-preset:hover {
                transform: scale(1.2);
                border-color: var(--color-text);
            }

            /* ============================================
               GATILHOS AUTOMÁTICOS
               ============================================ */
            .auto-triggers-list {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
                margin-bottom: 0.75rem;
            }

            .auto-trigger-item {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
                padding: 0.6rem;
                background: transparent;
                border: 1px solid var(--color-border);
                border-radius: 4px;
                position: relative;
            }

            .auto-trigger-header {
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .auto-trigger-header .trigger-type-select {
                flex: 1;
                font-size: 0.8rem;
                padding: 0.35rem 0.5rem;
            }

            .auto-trigger-header .btn-remove-trigger {
                padding: 0.25rem;
                color: var(--color-error);
                opacity: 0.6;
            }

            .auto-trigger-header .btn-remove-trigger:hover {
                opacity: 1;
            }

            .trigger-value-container {
                width: 100%;
            }

            .add-trigger-button {
                width: 100%;
                justify-content: center;
                border: 1px dashed var(--color-border);
                background: transparent;
                padding: 0.5rem;
                font-size: 0.75rem;
            }

            .add-trigger-button:hover {
                border-color: var(--color-primary);
                background: rgba(var(--color-primary-rgb), 0.05);
            }

            /* Estilos para gatilho de IA */
            .ai-semantic-trigger {
                border-color: rgba(99, 102, 241, 0.3);
            }

            .ai-intents-selector {
                width: 100%;
            }

            .ai-intents-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 0.35rem;
                flex-wrap: wrap;
                gap: 0.35rem;
            }

            .ai-intents-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
                gap: 0.35rem;
                max-height: 180px;
                overflow-y: auto;
                padding: 0.5rem;
                background: transparent;
                border-radius: 4px;
                border: 1px solid var(--color-border);
            }

            .ai-intent-option {
                display: flex;
                align-items: flex-start;
                gap: 0.35rem;
                padding: 0.4rem;
                border-radius: 3px;
                cursor: pointer;
                transition: all 0.15s ease;
                border: 1px solid transparent;
            }

            .ai-intent-option:hover {
                background: var(--color-surface-alt);
                border-color: var(--color-border);
            }

            .ai-intent-option input[type="checkbox"] {
                margin-top: 1px;
                flex-shrink: 0;
                width: 12px;
                height: 12px;
            }

            .ai-intent-option .intent-name {
                font-size: 0.7rem;
                font-weight: 500;
                text-transform: capitalize;
                color: var(--color-text);
            }

            .ai-intent-option .intent-desc {
                font-size: 0.6rem;
                color: var(--color-text-muted);
                line-height: 1.2;
                margin-top: 0.1rem;
                opacity: 0.7;
            }

            /* Scrollbar customizada */
            .ai-intents-grid::-webkit-scrollbar {
                width: 6px;
            }

            .ai-intents-grid::-webkit-scrollbar-track {
                background: var(--color-surface-alt);
                border-radius: 3px;
            }

            .ai-intents-grid::-webkit-scrollbar-thumb {
                background: var(--color-border);
                border-radius: 3px;
            }

            .ai-intents-grid::-webkit-scrollbar-thumb:hover {
                background: var(--color-text-muted);
            }

            /* ============================================
               ESTADOS VAZIOS E LOADING
               ============================================ */
            .empty-state {
                text-align: center;
                padding: 1.5rem 1rem;
                color: var(--color-text-muted);
            }

            .empty-state i {
                width: 32px;
                height: 32px;
                margin-bottom: 0.5rem;
                opacity: 0.3;
            }

            .empty-state p {
                margin: 0.15rem 0;
                font-size: 0.8rem;
            }

            .empty-state .text-sm {
                font-size: 0.7rem;
                opacity: 0.7;
            }

            /* ============================================
               RESPONSIVIDADE
               ============================================ */
            @media (max-width: 768px) {
                .tag-definition-card {
                    grid-template-columns: auto 1fr;
                    grid-template-rows: auto auto;
                }

                .tag-definition-actions {
                    grid-column: 1 / -1;
                    justify-content: flex-end;
                    padding-top: 0.75rem;
                    border-top: 1px solid var(--color-border);
                    margin-top: 0.5rem;
                }

                .form-row {
                    flex-direction: column;
                }

                .form-row .form-group,
                .form-row .form-group.flex-2 {
                    min-width: 100%;
                }

                .color-picker-wrapper {
                    flex-wrap: wrap;
                }

                .ai-intents-grid {
                    grid-template-columns: 1fr;
                }

                .modal-lg .modal-content {
                    max-height: 90vh;
                    overflow-y: auto;
                }
            }

            @media (max-width: 480px) {
                .tags-cloud {
                    gap: 0.5rem;
                }

                .tag-chip {
                    padding: 0.375rem 0.75rem;
                    font-size: 0.8rem;
                }

                .tag-definition-card {
                    padding: 0.875rem;
                }

                .form-section {
                    padding: 1rem;
                }
            }

            /* ============================================
               ESTILOS ADICIONAIS PARA CAMPOS DE GATILHO
               ============================================ */
            .trigger-placeholder {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                padding: 0.75rem;
                background: var(--color-surface-alt);
                border-radius: var(--radius-sm);
                border: 1px dashed var(--color-border);
            }

            .trigger-field-group {
                display: flex;
                flex-direction: column;
                gap: 0.375rem;
            }

            .trigger-field-label {
                display: flex;
                align-items: center;
                gap: 0.375rem;
                font-size: 0.8rem;
                font-weight: 600;
                color: var(--color-text);
            }

            .trigger-field-label i {
                color: var(--color-primary);
            }

            .trigger-field-hint {
                font-size: 0.7rem;
                color: var(--color-text-muted);
                line-height: 1.3;
            }

            /* Animações suaves */
            .auto-trigger-item {
                animation: slideIn 0.2s ease-out;
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

            .tag-definition-card {
                animation: fadeIn 0.15s ease-out;
            }

            @keyframes fadeIn {
                from { opacity: 0; }
                to { opacity: 1; }
            }

            /* Badges adicionais */
            .badge-secondary {
                background: var(--color-surface-alt);
                color: var(--color-text-muted);
                padding: 0.125rem 0.5rem;
                border-radius: var(--radius-full);
                font-size: 0.7rem;
                font-weight: 600;
            }
        </style>
    `;
}

function setupEventListeners() {
    // Botão de adicionar nova tag
    const addTagBtn = document.getElementById('add-tag-definition-btn');
    if (addTagBtn) {
        addTagBtn.addEventListener('click', () => openTagModal());
    }

    // Botão de salvar tag no modal
    const saveTagBtn = document.getElementById('save-tag-btn');
    if (saveTagBtn) {
        saveTagBtn.addEventListener('click', saveTagFromModal);
    }

    // Color picker preview
    const colorPicker = document.getElementById('tag-edit-color');
    if (colorPicker) {
        colorPicker.addEventListener('input', (e) => {
            const preview = document.getElementById('tag-color-preview');
            if (preview) {
                preview.style.background = e.target.value;
            }
        });
    }

    // Color presets - delegar evento
    document.addEventListener('click', (e) => {
        if (e.target.classList.contains('color-preset')) {
            const color = e.target.dataset.color;
            const colorPicker = document.getElementById('tag-edit-color');
            const preview = document.getElementById('tag-color-preview');
            if (colorPicker) colorPicker.value = color;
            if (preview) preview.style.background = color;
        }
    });

    // Botão de adicionar gatilho
    const addTriggerBtn = document.getElementById('add-trigger-btn');
    if (addTriggerBtn) {
        addTriggerBtn.addEventListener('click', addAutoTrigger);
    }

    // Fechar modal
    document.querySelectorAll('.modal-close-btn').forEach(btn => {
        btn.addEventListener('click', closeTagModal);
    });

    // Fechar modal ao clicar no backdrop
    const backdrop = document.getElementById('edit-tag-modal-backdrop');
    if (backdrop) {
        backdrop.addEventListener('click', closeTagModal);
    }

    // Fechar modal de prospects ao clicar no backdrop
    const prospectsBackdrop = document.getElementById('prospects-by-tag-modal-backdrop');
    if (prospectsBackdrop) {
        prospectsBackdrop.addEventListener('click', window.closeProspectsByTagModal);
    }

    // Fechar modal com ESC
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const modal = document.getElementById('edit-tag-modal');
            if (modal && modal.classList.contains('is-visible')) {
                closeTagModal();
            }
            const prospectsModal = document.getElementById('prospects-by-tag-modal');
            if (prospectsModal && prospectsModal.classList.contains('is-visible')) {
                window.closeProspectsByTagModal();
            }
        }
    });
}

async function loadTagDefinitions() {
    console.log('tagsConfig.js: Carregando definições de tags...');

    try {
        const response = await authenticatedFetch('/api/tags/definitions');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        tagDefinitions = data.definitions || [];

        renderTagDefinitions();

    } catch (error) {
        console.error('tagsConfig.js: Erro ao carregar definições:', error);
        showToast('Erro ao carregar definições de tags', 'error');
    }
}

async function loadAllTagsInUse() {
    console.log('tagsConfig.js: Carregando tags em uso...');

    try {
        const response = await authenticatedFetch('/api/tags/all');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        allTagsInUse = data.tags || [];

        renderTagsInUse();

    } catch (error) {
        console.error('tagsConfig.js: Erro ao carregar tags em uso:', error);
        showToast('Erro ao carregar tags em uso', 'error');
    }
}

async function loadAiSemanticIntents() {
    console.log('tagsConfig.js: Carregando intenções semânticas da IA...');

    try {
        const response = await authenticatedFetch('/api/tags/ai-semantic-intents');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        aiSemanticIntents = data.intents || [];
        console.log('tagsConfig.js: Intenções semânticas carregadas:', aiSemanticIntents);

    } catch (error) {
        console.error('tagsConfig.js: Erro ao carregar intenções semânticas:', error);
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

function renderTagsInUse() {
    const container = document.getElementById('tags-in-use-container');
    const countBadge = document.getElementById('tags-count-badge');

    if (!container) return;

    if (allTagsInUse.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <i data-feather="tag"></i>
                <p>Nenhuma tag em uso ainda.</p>
                <p class="text-sm">As tags aparecerão aqui quando forem atribuídas aos prospects.</p>
            </div>
        `;
        if (countBadge) countBadge.textContent = '0 tags';
        replaceFeatherIcons();
        return;
    }

    if (countBadge) countBadge.textContent = `${allTagsInUse.length} ${allTagsInUse.length === 1 ? 'tag' : 'tags'}`;

    // Ordenar por contagem (maior primeiro)
    const sortedTags = [...allTagsInUse].sort((a, b) => b.count - a.count);

    container.innerHTML = sortedTags.map(tag => {
        const definition = tagDefinitions.find(d => d.name.toLowerCase() === tag.name.toLowerCase());
        const color = definition?.color || '#6B7280';
        const escapedTagName = escapeHtml(tag.name).replace(/'/g, "\\'");

        return `
            <div class="tag-chip" style="border-color: ${color};" title="Clique para ver ${tag.count} ${tag.count === 1 ? 'prospect' : 'prospects'}" onclick="window.showProspectsByTag('${escapedTagName}', '${color}')">
                <span class="tag-color-dot" style="background: ${color};"></span>
                <span class="tag-name">${escapeHtml(tag.name)}</span>
                <span class="tag-count">${tag.count}</span>
            </div>
        `;
    }).join('');

    replaceFeatherIcons();
}

function renderTagDefinitions() {
    const container = document.getElementById('tag-definitions-list');

    if (!container) return;

    if (tagDefinitions.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <i data-feather="plus-circle"></i>
                <p>Nenhuma definição de tag criada.</p>
                <p class="text-sm">Clique em "Nova Tag" para começar a organizar seus prospects.</p>
            </div>
        `;
        replaceFeatherIcons();
        return;
    }

    // Ordenar alfabeticamente
    const sortedDefinitions = [...tagDefinitions].sort((a, b) =>
        a.name.toLowerCase().localeCompare(b.name.toLowerCase())
    );

    container.innerHTML = sortedDefinitions.map(tag => {
        const triggersCount = tag.auto_triggers?.length || 0;
        const tagInUse = allTagsInUse.find(t => t.name.toLowerCase() === tag.name.toLowerCase());
        const usageCount = tagInUse?.count || 0;

        return `
            <div class="tag-definition-card" data-tag-id="${tag.id}">
                <div class="tag-color-indicator" style="background: ${tag.color || '#6B7280'};"></div>
                <div class="tag-definition-info">
                    <div class="tag-definition-header">
                        <span class="tag-definition-name">${escapeHtml(tag.name)}</span>
                        ${usageCount > 0 ? `<span class="badge badge-secondary" title="${usageCount} prospects">${usageCount} uso${usageCount > 1 ? 's' : ''}</span>` : ''}
                    </div>
                    ${tag.description ? `<div class="tag-definition-description">${escapeHtml(tag.description)}</div>` : ''}
                    ${renderTriggerBadges(tag.auto_triggers || [])}
                </div>
                <div class="tag-definition-actions">
                    <button type="button" class="btn btn-ghost btn-icon btn-sm" onclick="window.editTagDefinition('${tag.id}')" title="Editar tag">
                        <i data-feather="edit-2"></i>
                    </button>
                    <button type="button" class="btn btn-ghost btn-icon btn-sm btn-danger" onclick="window.deleteTagDefinition('${tag.id}')" title="Excluir tag">
                        <i data-feather="trash-2"></i>
                    </button>
                </div>
            </div>
        `;
    }).join('');

    replaceFeatherIcons();
}

function renderTriggerBadges(triggers) {
    if (!triggers || triggers.length === 0) return '';

    const triggerConfig = {
        'keyword': { label: 'Palavra-chave', icon: 'search', class: 'trigger-badge-keyword' },
        'inactivity': { label: 'Inatividade', icon: 'clock', class: 'trigger-badge-inactivity' },
        'stage_change': { label: 'Estágio', icon: 'git-branch', class: 'trigger-badge-stage' },
        'ai_semantic': { label: 'IA Semântica', icon: 'cpu', class: 'trigger-badge-ai' }
    };

    return `
        <div class="tag-definition-triggers">
            ${triggers.map(t => {
                const config = triggerConfig[t.type] || { label: t.type, icon: 'zap', class: '' };
                let extraInfo = '';

                if (t.type === 'ai_semantic' && t.custom_instruction) {
                    extraInfo = ' (Custom)';
                } else if (t.type === 'keyword' && t.keywords) {
                    extraInfo = ` (${t.keywords.length})`;
                } else if (t.type === 'inactivity' && t.minutes) {
                    extraInfo = ` ${t.minutes}min`;
                }

                return `
                    <span class="trigger-badge ${config.class}" title="${getTriggerDescription(t)}">
                        <i data-feather="${config.icon}"></i>
                        ${config.label}${extraInfo}
                    </span>
                `;
            }).join('')}
        </div>
    `;
}

function getTriggerDescription(trigger) {
    switch (trigger.type) {
        case 'keyword':
            return `Palavras: ${trigger.keywords?.join(', ') || 'N/A'}`;
        case 'inactivity':
            return `Após ${trigger.minutes || 60} minutos de inatividade`;
        case 'stage_change':
            return `Quando mudar de estágio ${trigger.from_stage || '*'} para ${trigger.to_stage || '*'}`;
        case 'ai_semantic':
            const instruction = trigger.custom_instruction || '';
            return `IA: ${instruction.substring(0, 50)}${instruction.length > 50 ? '...' : ''}`;
        default:
            return trigger.type;
    }
}

function openTagModal(tagId = null) {
    const modal = document.getElementById('edit-tag-modal');
    const backdrop = document.getElementById('edit-tag-modal-backdrop');
    const title = document.getElementById('edit-tag-modal-title');

    if (!modal || !backdrop) return;

    // Limpar form
    document.getElementById('tag-edit-id').value = '';
    document.getElementById('tag-edit-name').value = '';
    document.getElementById('tag-edit-color').value = '#3B82F6';
    document.getElementById('tag-color-preview').style.background = '#3B82F6';
    document.getElementById('tag-edit-description').value = '';
    document.getElementById('auto-triggers-container').innerHTML = '';

    if (tagId) {
        const tag = tagDefinitions.find(t => t.id === tagId);
        if (tag) {
            title.textContent = 'Editar Tag';
            document.getElementById('tag-edit-id').value = tag.id;
            document.getElementById('tag-edit-name').value = tag.name;
            document.getElementById('tag-edit-color').value = tag.color || '#3B82F6';
            document.getElementById('tag-color-preview').style.background = tag.color || '#3B82F6';
            document.getElementById('tag-edit-description').value = tag.description || '';

            // Renderizar gatilhos existentes
            if (tag.auto_triggers && tag.auto_triggers.length > 0) {
                tag.auto_triggers.forEach(trigger => addAutoTrigger(trigger));
            }
        }
    } else {
        title.textContent = 'Nova Tag';
    }

    modal.classList.add('is-visible');
    modal.setAttribute('aria-hidden', 'false');
    backdrop.classList.add('is-visible');
    backdrop.setAttribute('aria-hidden', 'false');
    document.body.classList.add('modal-open');

    replaceFeatherIcons();
}

function closeTagModal() {
    const modal = document.getElementById('edit-tag-modal');
    const backdrop = document.getElementById('edit-tag-modal-backdrop');

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

function addAutoTrigger(existingTrigger = null) {
    const container = document.getElementById('auto-triggers-container');
    if (!container) return;

    const triggerId = `trigger-${Date.now()}`;

    const triggerHtml = `
        <div class="auto-trigger-item ${existingTrigger?.type === 'ai_semantic' ? 'ai-semantic-trigger' : ''}" data-trigger-id="${triggerId}">
            <div class="auto-trigger-header">
                <select class="select trigger-type-select" onchange="window.updateTriggerFields('${triggerId}')">
                    <option value="">Selecione o tipo de gatilho...</option>
                    <option value="ai_semantic" ${existingTrigger?.type === 'ai_semantic' ? 'selected' : ''}>🤖 Detecção por IA (Semântica)</option>
                    <option value="keyword" ${existingTrigger?.type === 'keyword' ? 'selected' : ''}>🔍 Palavra-chave detectada</option>
                    <option value="inactivity" ${existingTrigger?.type === 'inactivity' ? 'selected' : ''}>⏰ Inatividade (tempo sem resposta)</option>
                    <option value="stage_change" ${existingTrigger?.type === 'stage_change' ? 'selected' : ''}>📊 Mudança de estágio</option>
                </select>
                <button type="button" class="btn btn-ghost btn-icon btn-sm btn-danger btn-remove-trigger" onclick="window.removeTrigger('${triggerId}')" title="Remover gatilho">
                    <i data-feather="trash-2"></i>
                </button>
            </div>
            <div class="trigger-value-container" id="${triggerId}-value">
                ${renderTriggerValueField(existingTrigger, triggerId)}
            </div>
        </div>
    `;

    container.insertAdjacentHTML('beforeend', triggerHtml);
    updateTriggersCount();
    replaceFeatherIcons();
}

function updateTriggersCount() {
    const container = document.getElementById('auto-triggers-container');
    const badge = document.getElementById('triggers-count-badge');
    if (container && badge) {
        const count = container.querySelectorAll('.auto-trigger-item').length;
        badge.textContent = count;
    }
}

function renderTriggerValueField(trigger, triggerId = null) {
    if (!trigger || !trigger.type) {
        return `
            <div class="trigger-placeholder">
                <i data-feather="info" style="width: 14px; height: 14px; opacity: 0.5;"></i>
                <span style="font-size: 0.8rem; color: var(--color-text-muted);">Selecione um tipo de gatilho acima para configurar</span>
            </div>
        `;
    }

    switch (trigger.type) {
        case 'ai_semantic':
            const customInstruction = trigger.custom_instruction || '';
            return `
                <div class="ai-custom-instruction">
                    <label class="trigger-field-label">
                        <i data-feather="cpu" style="width: 12px; height: 12px;"></i>
                        Instruções para a IA
                    </label>
                    <textarea class="textarea trigger-ai-instruction" rows="3" placeholder="Descreva quando esta tag deve ser aplicada. Ex: 'Quando o prospect demonstrar interesse em agendar uma reunião ou solicitar uma demonstração do produto'">${customInstruction}</textarea>
                    <span class="trigger-field-hint">A IA analisará cada mensagem e aplicará esta tag quando identificar o contexto descrito acima.</span>
                </div>
            `;
        case 'keyword':
            return `
                <div class="trigger-field-group">
                    <label class="trigger-field-label">
                        <i data-feather="search" style="width: 12px; height: 12px;"></i>
                        Palavras-chave a detectar
                    </label>
                    <input type="text" class="input trigger-value" placeholder="Ex: cancelar, desistir, problema (separar por vírgula)" value="${trigger.keywords?.join(', ') || ''}">
                    <span class="trigger-field-hint">A tag será aplicada quando qualquer uma dessas palavras for detectada na mensagem.</span>
                </div>
            `;
        case 'inactivity':
            return `
                <div class="trigger-field-group">
                    <label class="trigger-field-label">
                        <i data-feather="clock" style="width: 12px; height: 12px;"></i>
                        Tempo de inatividade (minutos)
                    </label>
                    <input type="number" class="input trigger-value" placeholder="Ex: 60" min="1" max="10080" value="${trigger.minutes || ''}">
                    <span class="trigger-field-hint">A tag será aplicada após o prospect ficar sem responder por este período.</span>
                </div>
            `;
        case 'stage_change':
            return `
                <div class="trigger-field-group">
                    <label class="trigger-field-label">
                        <i data-feather="git-branch" style="width: 12px; height: 12px;"></i>
                        Transição de estágio
                    </label>
                    <div style="display: flex; gap: 0.5rem; align-items: center;">
                        <input type="number" class="input trigger-from-stage" placeholder="De" min="1" value="${trigger.from_stage || ''}" style="width: 80px;">
                        <i data-feather="arrow-right" style="width: 16px; height: 16px; color: var(--color-text-muted);"></i>
                        <input type="number" class="input trigger-to-stage" placeholder="Para" min="1" value="${trigger.to_stage || ''}" style="width: 80px;">
                    </div>
                    <span class="trigger-field-hint">A tag será aplicada quando o prospect mudar de um estágio para outro. Deixe vazio para "qualquer".</span>
                </div>
            `;
        default:
            return '<input type="text" class="input trigger-value" placeholder="Valor...">';
    }
}

function formatIntentName(intentType) {
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

// Funções globais para os eventos inline
window.editTagDefinition = function(tagId) {
    openTagModal(tagId);
};

window.deleteTagDefinition = async function(tagId) {
    if (!confirm('Tem certeza que deseja excluir esta definição de tag?')) return;

    tagDefinitions = tagDefinitions.filter(t => t.id !== tagId);
    renderTagDefinitions();

    // Auto-save: salvar automaticamente após remover tag
    await saveTagDefinitions();
};

window.removeTrigger = function(triggerId) {
    const element = document.querySelector(`[data-trigger-id="${triggerId}"]`);
    if (element) {
        element.remove();
        updateTriggersCount();
    }
};

window.updateTriggerFields = function(triggerId) {
    const container = document.getElementById(`${triggerId}-value`);
    const select = document.querySelector(`[data-trigger-id="${triggerId}"] .trigger-type-select`);
    const triggerItem = document.querySelector(`[data-trigger-id="${triggerId}"]`);

    if (!container || !select) return;

    const type = select.value;
    container.innerHTML = renderTriggerValueField({ type }, triggerId);

    // Adicionar/remover classe para estilização do gatilho de IA
    if (triggerItem) {
        if (type === 'ai_semantic') {
            triggerItem.classList.add('ai-semantic-trigger');
        } else {
            triggerItem.classList.remove('ai-semantic-trigger');
        }
    }
};

window.toggleAllIntents = function(triggerId) {
    const container = document.getElementById(`${triggerId}-value`);
    if (!container) return;

    const checkboxes = container.querySelectorAll('.ai-intent-checkbox');
    const allChecked = Array.from(checkboxes).every(cb => cb.checked);

    checkboxes.forEach(cb => {
        cb.checked = !allChecked;
    });
};

async function saveTagFromModal() {
    const id = document.getElementById('tag-edit-id').value || `tag-${Date.now()}`;
    const name = document.getElementById('tag-edit-name').value.trim();
    const color = document.getElementById('tag-edit-color').value;
    const description = document.getElementById('tag-edit-description').value.trim();

    if (!name) {
        showToast('O nome da tag é obrigatório', 'error');
        return;
    }

    // Verificar se nome já existe (exceto para a mesma tag)
    const existingWithName = tagDefinitions.find(t =>
        t.name.toLowerCase() === name.toLowerCase() && t.id !== id
    );
    if (existingWithName) {
        showToast('Já existe uma tag com este nome', 'error');
        return;
    }

    // Coletar gatilhos
    const triggers = [];
    let hasError = false;

    document.querySelectorAll('.auto-trigger-item').forEach(item => {
        if (hasError) return;

        const typeSelect = item.querySelector('.trigger-type-select');
        const valueInput = item.querySelector('.trigger-value');
        const intentCheckboxes = item.querySelectorAll('.ai-intent-checkbox');

        if (typeSelect && typeSelect.value) {
            const trigger = { type: typeSelect.value };

            switch (typeSelect.value) {
                case 'ai_semantic':
                    // Coletar instrução customizada
                    const instructionTextarea = item.querySelector('.trigger-ai-instruction');
                    const customInstruction = instructionTextarea?.value?.trim() || '';
                    if (!customInstruction) {
                        showToast('Preencha as instruções para a IA', 'warning');
                        hasError = true;
                        return;
                    }
                    trigger.custom_instruction = customInstruction;
                    break;
                case 'keyword':
                    if (valueInput) {
                        const keywords = valueInput.value.split(',').map(k => k.trim()).filter(k => k);
                        if (keywords.length === 0) {
                            showToast('Adicione pelo menos uma palavra-chave', 'warning');
                            hasError = true;
                            return;
                        }
                        trigger.keywords = keywords;
                    }
                    break;
                case 'inactivity':
                    if (valueInput) {
                        const minutes = parseInt(valueInput.value);
                        if (!minutes || minutes < 1) {
                            showToast('Informe um tempo de inatividade válido (mínimo 1 minuto)', 'warning');
                            hasError = true;
                            return;
                        }
                        trigger.minutes = minutes;
                    }
                    break;
                case 'stage_change':
                    // Novo layout com campos separados
                    const fromInput = item.querySelector('.trigger-from-stage');
                    const toInput = item.querySelector('.trigger-to-stage');
                    if (fromInput && fromInput.value) {
                        trigger.from_stage = parseInt(fromInput.value);
                    }
                    if (toInput && toInput.value) {
                        trigger.to_stage = parseInt(toInput.value);
                    }
                    // Pelo menos um deve estar preenchido
                    if (!trigger.from_stage && !trigger.to_stage) {
                        showToast('Informe pelo menos um estágio (de ou para)', 'warning');
                        hasError = true;
                        return;
                    }
                    break;
            }

            triggers.push(trigger);
        }
    });

    if (hasError) return;

    // Atualizar ou adicionar tag
    const existingIndex = tagDefinitions.findIndex(t => t.id === id);
    const tagData = { id, name, color, description, auto_triggers: triggers };

    if (existingIndex >= 0) {
        tagDefinitions[existingIndex] = tagData;
    } else {
        tagDefinitions.push(tagData);
    }

    closeTagModal();
    renderTagDefinitions();
    renderTagsInUse();

    // Auto-save: salvar automaticamente no servidor após criar/editar tag
    await saveTagDefinitions();
}

async function saveTagDefinitions() {
    console.log('tagsConfig.js: Salvando definições de tags...');

    try {
        const response = await authenticatedFetch('/api/tags/definitions', {
            method: 'POST',
            body: JSON.stringify({ definitions: tagDefinitions })
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        showToast('Definições de tags salvas com sucesso!', 'success');

    } catch (error) {
        console.error('tagsConfig.js: Erro ao salvar definições:', error);
        showToast('Erro ao salvar definições de tags', 'error');
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ==================== MODAL DE PROSPECTS POR TAG ====================

window.showProspectsByTag = async function(tagName, tagColor) {
    console.log(`[${new Date().toISOString()}] [SHOW_PROSPECTS_BY_TAG] Iniciando`, { tagName, tagColor });

    const modal = document.getElementById('prospects-by-tag-modal');
    const backdrop = document.getElementById('prospects-by-tag-modal-backdrop');
    const tagNameSpan = document.getElementById('prospects-tag-name');
    const contentContainer = document.getElementById('prospects-by-tag-content');
    const countInfo = document.getElementById('prospects-count-info');

    if (!modal || !backdrop) {
        console.error('[SHOW_PROSPECTS_BY_TAG] Modal não encontrado');
        return;
    }

    // Mostrar modal com loading
    tagNameSpan.textContent = tagName;
    tagNameSpan.style.backgroundColor = `${tagColor}20`;
    tagNameSpan.style.color = tagColor;

    contentContainer.innerHTML = `
        <div class="spinner-container">
            <div class="loading-spinner"></div>
            <p class="text-muted" style="margin-top: 0.5rem;">Carregando prospects...</p>
        </div>
    `;
    countInfo.textContent = '';

    modal.classList.add('is-visible');
    modal.setAttribute('aria-hidden', 'false');
    backdrop.classList.add('is-visible');
    backdrop.setAttribute('aria-hidden', 'false');
    document.body.classList.add('modal-open');

    replaceFeatherIcons();

    try {
        const startTime = Date.now();
        const encodedTag = encodeURIComponent(tagName);
        const response = await authenticatedFetch(`/api/tags/prospects/by-tag/${encodedTag}`);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        const duration = Date.now() - startTime;

        console.log(`[${new Date().toISOString()}] [SHOW_PROSPECTS_BY_TAG] Sucesso em ${duration}ms`, {
            tag: tagName,
            count: data.count,
            prospects: data.prospects?.length || 0
        });

        renderProspectsByTagList(data.prospects || [], tagName, tagColor);
        countInfo.textContent = `${data.count} ${data.count === 1 ? 'lead encontrado' : 'leads encontrados'}`;

    } catch (error) {
        console.error(`[${new Date().toISOString()}] [SHOW_PROSPECTS_BY_TAG] ERRO`, {
            error: error.message,
            tagName
        });

        contentContainer.innerHTML = `
            <div class="empty-prospects-state">
                <i data-feather="alert-circle"></i>
                <p>Erro ao carregar prospects</p>
                <p class="text-sm text-muted">${error.message}</p>
            </div>
        `;
        replaceFeatherIcons();
    }
};

function renderProspectsByTagList(prospects, tagName, tagColor) {
    const container = document.getElementById('prospects-by-tag-content');

    if (!prospects || prospects.length === 0) {
        container.innerHTML = `
            <div class="empty-prospects-state">
                <i data-feather="users"></i>
                <p>Nenhum lead encontrado com a tag "${escapeHtml(tagName)}"</p>
            </div>
        `;
        replaceFeatherIcons();
        return;
    }

    const tableHTML = `
        <table class="prospects-list-table">
            <thead>
                <tr>
                    <th>Nome</th>
                    <th>Telefone</th>
                    <th>Status</th>
                    <th>Estágio</th>
                    <th>Última Interação</th>
                </tr>
            </thead>
            <tbody>
                ${prospects.map(prospect => {
                    const statusClass = prospect.status || 'active';
                    const statusText = getStatusText(prospect.status);
                    const phone = formatPhone(prospect.jid);
                    const lastInteraction = prospect.last_interaction_at
                        ? formatRelativeTime(prospect.last_interaction_at)
                        : 'N/A';

                    return `
                        <tr class="prospect-row" onclick="window.openProspectChat('${prospect.jid}')" title="Clique para abrir conversa">
                            <td class="prospect-name">${escapeHtml(prospect.name || 'Sem nome')}</td>
                            <td class="prospect-phone">${phone}</td>
                            <td><span class="prospect-status-badge ${statusClass}">${statusText}</span></td>
                            <td>${prospect.current_stage || 1}</td>
                            <td>${lastInteraction}</td>
                        </tr>
                    `;
                }).join('')}
            </tbody>
        </table>
    `;

    container.innerHTML = tableHTML;
    replaceFeatherIcons();
}

function getStatusText(status) {
    const statusMap = {
        'active': 'Ativo',
        'inactive': 'Inativo',
        'won': 'Ganho',
        'lost': 'Perdido',
        'pending': 'Pendente'
    };
    return statusMap[status] || status || 'Ativo';
}

function formatPhone(jid) {
    if (!jid) return 'N/A';
    const cleaned = jid.replace('@s.whatsapp.net', '').replace('@c.us', '');
    if (cleaned.length >= 12) {
        // Formato brasileiro: +55 11 99999-9999
        return `+${cleaned.slice(0, 2)} ${cleaned.slice(2, 4)} ${cleaned.slice(4, 9)}-${cleaned.slice(9)}`;
    }
    return cleaned;
}

function formatRelativeTime(dateString) {
    if (!dateString) return 'N/A';

    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Agora';
    if (diffMins < 60) return `${diffMins}min atrás`;
    if (diffHours < 24) return `${diffHours}h atrás`;
    if (diffDays < 7) return `${diffDays}d atrás`;

    // Formatação com timezone America/Sao_Paulo (GMT-3)
    return date.toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo' });
}

window.closeProspectsByTagModal = function() {
    console.log(`[${new Date().toISOString()}] [CLOSE_PROSPECTS_MODAL] Fechando modal`);

    const modal = document.getElementById('prospects-by-tag-modal');
    const backdrop = document.getElementById('prospects-by-tag-modal-backdrop');

    if (modal) {
        modal.classList.remove('is-visible');
        modal.setAttribute('aria-hidden', 'true');
    }
    if (backdrop) {
        backdrop.classList.remove('is-visible');
        backdrop.setAttribute('aria-hidden', 'true');
    }
    document.body.classList.remove('modal-open');
};

window.openProspectChat = function(jid) {
    console.log(`[${new Date().toISOString()}] [OPEN_PROSPECT_CHAT] Abrindo chat`, { jid });

    // Fechar o modal primeiro
    window.closeProspectsByTagModal();

    // Navegar para o dashboard com o prospect selecionado
    if (window.navigateToPage) {
        window.navigateToPage('dashboard', { selectedJid: jid });
    } else {
        // Fallback: usar hash navigation
        window.location.hash = `#/dashboard?jid=${encodeURIComponent(jid)}`;
    }
};
