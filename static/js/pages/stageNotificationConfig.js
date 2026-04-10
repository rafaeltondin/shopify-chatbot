// static/js/pages/stageNotificationConfig.js
import { getStageChangeNotificationConfig, setStageChangeNotificationConfig, getSalesFlowConfig, getFunnelsList, getFunnel } from '../api.js';
import { showFeedback, clearFeedback, setLoadingState } from '../utils.js';

let salesFlowStages = [];
let availableFunnels = [];
let funnelStagesCache = {}; // Cache de estágios por funil

const DEFAULT_MESSAGE_TEMPLATE = `🎯 *Prospect Avançou de Etapa!*

👤 *Nome:* {prospect_name}
📱 *Telefone:* {prospect_phone}

📊 *Etapa Anterior:* {old_stage_name}
📊 *Nova Etapa:* {stage_name}
⏰ *Horário:* {timestamp}`;

export async function loadStageNotificationConfigPage(container) {
    console.log('stageNotificationConfig.js: Carregando página...');

    container.innerHTML = `
        <header class="page-header">
            <h1 class="page-title"><i data-feather="bell" class="feather-title"></i> Notificações de Etapa</h1>
            <p class="page-description">Configure alertas via WhatsApp quando prospects mudarem de etapa no funil de vendas.</p>
        </header>

        <!-- Info Card -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="info" class="feather-title-sm"></i> Como Funciona</h3>
            </div>
            <div class="card-body">
                <div class="alert alert-info mb-0">
                    <i class="alert-icon" data-feather="trending-up"></i>
                    <div class="alert-content">
                        <div class="alert-title">Acompanhe a Evolução dos Prospects</div>
                        <div class="alert-description">
                            Receba notificações instantâneas quando um prospect avançar de etapa no funil.
                            Isso permite que você acompanhe o progresso das vendas em tempo real.
                        </div>
                    </div>
                </div>
                <div class="flow-steps">
                    <div class="flow-step">
                        <i data-feather="user"></i>
                        <span>Prospect avança</span>
                    </div>
                    <div class="flow-arrow"><i data-feather="chevron-right"></i></div>
                    <div class="flow-step">
                        <i data-feather="git-branch"></i>
                        <span>Muda de etapa</span>
                    </div>
                    <div class="flow-arrow"><i data-feather="chevron-right"></i></div>
                    <div class="flow-step">
                        <i data-feather="send"></i>
                        <span>WhatsApp enviado</span>
                    </div>
                    <div class="flow-arrow"><i data-feather="chevron-right"></i></div>
                    <div class="flow-step">
                        <i data-feather="bell"></i>
                        <span>Você é notificado</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Configuração Principal -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="settings" class="feather-title-sm"></i> Configurações</h3>
            </div>
            <div class="card-body">
                <form id="stage-notification-form" class="form">
                    <!-- Toggle -->
                    <div class="form-group">
                        <div class="form-check form-switch">
                            <input class="form-check-input" type="checkbox" id="stage-notification-enabled">
                            <label class="form-check-label" for="stage-notification-enabled">
                                <strong>Ativar Notificações de Mudança de Etapa</strong>
                            </label>
                        </div>
                        <small class="form-text text-muted">Receba alertas quando prospects avançarem no funil.</small>
                    </div>

                    <hr class="form-divider">

                    <div id="config-fields">
                        <!-- Número WhatsApp -->
                        <div class="form-group">
                            <label for="notification-phone" class="label">Número WhatsApp para Notificação:</label>
                            <input type="tel" id="notification-phone" class="input" placeholder="Ex: 5511999999999">
                            <p class="form-text">Número que receberá as notificações. Use formato: código do país + DDD + número (apenas números).</p>
                        </div>

                        <hr class="form-divider">

                        <!-- Seleção de Funis -->
                        <div class="form-section">
                            <h4 class="form-section-title"><i data-feather="git-branch" class="feather-sm"></i> Filtrar Funis</h4>

                            <div class="form-group">
                                <div class="form-check form-switch">
                                    <input class="form-check-input" type="checkbox" id="notify-all-funnels" checked>
                                    <label class="form-check-label" for="notify-all-funnels">
                                        Notificar todos os funis
                                    </label>
                                </div>
                                <small class="form-text text-muted">Se desmarcado, você pode escolher quais funis específicos devem gerar notificação.</small>
                            </div>

                            <div id="funnel-selection" style="display: none;">
                                <label class="label">Selecione o funil para esta configuração:</label>
                                <select id="funnel-selector" class="select">
                                    <option value="">Carregando funis...</option>
                                </select>
                            </div>
                        </div>

                        <hr class="form-divider">

                        <!-- Seleção de Etapas -->
                        <div class="form-section">
                            <h4 class="form-section-title"><i data-feather="filter" class="feather-sm"></i> Filtrar Etapas</h4>

                            <div class="form-group">
                                <div class="form-check form-switch">
                                    <input class="form-check-input" type="checkbox" id="notify-all-stages" checked>
                                    <label class="form-check-label" for="notify-all-stages">
                                        Notificar todas as etapas
                                    </label>
                                </div>
                                <small class="form-text text-muted">Se desmarcado, você pode escolher quais etapas específicas devem gerar notificação.</small>
                            </div>

                            <div id="stage-selection" style="display: none;">
                                <label class="label">Selecione as etapas que devem gerar notificação:</label>
                                <div id="stages-list" class="stages-checkbox-list">
                                    <p class="text-muted">Carregando etapas do funil...</p>
                                </div>
                            </div>
                        </div>

                        <hr class="form-divider">

                        <!-- Template da Mensagem -->
                        <div class="form-section">
                            <h4 class="form-section-title"><i data-feather="file-text" class="feather-sm"></i> Template da Mensagem</h4>

                            <div class="form-group">
                                <label for="message-template" class="label">Mensagem de Notificação:</label>
                                <textarea id="message-template" class="textarea" rows="10" placeholder="Template da mensagem de notificação"></textarea>
                                <p class="form-text">
                                    Variáveis disponíveis: <code>{prospect_name}</code>, <code>{prospect_phone}</code>, <code>{stage_name}</code>, <code>{old_stage_name}</code>, <code>{stage_number}</code>, <code>{old_stage_number}</code>, <code>{timestamp}</code>
                                </p>
                                <div class="variable-buttons" style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem;">
                                    <button type="button" class="btn btn-outline btn-xs variable-btn" data-variable="{prospect_name}">{prospect_name}</button>
                                    <button type="button" class="btn btn-outline btn-xs variable-btn" data-variable="{prospect_phone}">{prospect_phone}</button>
                                    <button type="button" class="btn btn-outline btn-xs variable-btn" data-variable="{stage_name}">{stage_name}</button>
                                    <button type="button" class="btn btn-outline btn-xs variable-btn" data-variable="{old_stage_name}">{old_stage_name}</button>
                                    <button type="button" class="btn btn-outline btn-xs variable-btn" data-variable="{timestamp}">{timestamp}</button>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div id="form-feedback" class="feedback-message"></div>

                    <button type="submit" class="btn btn-primary">
                        <i data-feather="save"></i> Salvar Configurações
                    </button>
                </form>
            </div>
        </div>

        <style>
            .flow-steps {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                flex-wrap: wrap;
            }
            .flow-step {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                padding: 0.5rem 1rem;
                background: var(--bg-secondary, #f3f4f6);
                border-radius: 8px;
                font-size: 0.85rem;
                color: var(--text-secondary);
            }
            .flow-step svg {
                width: 16px;
                height: 16px;
            }
            .flow-arrow {
                color: var(--text-tertiary, #9ca3af);
            }
            .flow-arrow svg {
                width: 20px;
                height: 20px;
            }
            .stages-checkbox-list {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
                gap: 0.75rem;
                margin-top: 0.75rem;
                padding: 1rem;
                background: var(--bg-secondary, #f9fafb);
                border-radius: 8px;
            }
            .stage-checkbox-item {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                padding: 0.5rem;
                background: var(--card-bg, #fff);
                border: 1px solid var(--border-color, #e5e7eb);
                border-radius: 6px;
                cursor: pointer;
                transition: all 0.2s;
            }
            .stage-checkbox-item:hover {
                border-color: var(--primary-color, #3b82f6);
            }
            .stage-checkbox-item input {
                accent-color: var(--primary-color, #3b82f6);
            }
            .stage-checkbox-item label {
                cursor: pointer;
                font-size: 0.9rem;
            }
            @media (max-width: 768px) {
                .flow-steps {
                    flex-direction: column;
                    align-items: stretch;
                }
                .flow-arrow {
                    transform: rotate(90deg);
                    align-self: center;
                }
                .stages-checkbox-list {
                    grid-template-columns: 1fr;
                }
            }
        </style>
    `;

    // Event Listeners
    setupEventListeners();

    // Carregar dados - IMPORTANTE: primeiro os funis e etapas, depois a config
    await fetchAvailableFunnels();
    await fetchSalesFlowStages();
    await fetchConfig();

    // Initialize Feather icons
    if (typeof feather !== 'undefined') {
        feather.replace();
    }

    console.log('stageNotificationConfig.js: Página carregada.');
}

function setupEventListeners() {
    // Toggle enable/disable
    document.getElementById('stage-notification-enabled').addEventListener('change', handleToggle);

    // Toggle notify all funnels
    document.getElementById('notify-all-funnels').addEventListener('change', handleNotifyAllFunnelsToggle);

    // Toggle notify all stages
    document.getElementById('notify-all-stages').addEventListener('change', handleNotifyAllToggle);

    // Funnel selector change
    document.getElementById('funnel-selector').addEventListener('change', handleFunnelSelectorChange);

    // Form submit
    document.getElementById('stage-notification-form').addEventListener('submit', handleFormSubmit);

    // Variable buttons
    document.querySelectorAll('.variable-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const variable = btn.dataset.variable;
            const textarea = document.getElementById('message-template');
            const start = textarea.selectionStart;
            const end = textarea.selectionEnd;
            const text = textarea.value;
            textarea.value = text.substring(0, start) + variable + text.substring(end);
            textarea.focus();
            textarea.setSelectionRange(start + variable.length, start + variable.length);
        });
    });
}

function handleToggle() {
    const enabled = document.getElementById('stage-notification-enabled').checked;
    const fieldsContainer = document.getElementById('config-fields');
    fieldsContainer.style.opacity = enabled ? '1' : '0.5';
    fieldsContainer.style.pointerEvents = enabled ? 'auto' : 'none';
}

function handleNotifyAllToggle() {
    const notifyAll = document.getElementById('notify-all-stages').checked;
    const stageSelection = document.getElementById('stage-selection');
    stageSelection.style.display = notifyAll ? 'none' : 'block';
}

function handleNotifyAllFunnelsToggle() {
    const notifyAllFunnels = document.getElementById('notify-all-funnels').checked;
    const funnelSelection = document.getElementById('funnel-selection');
    funnelSelection.style.display = notifyAllFunnels ? 'none' : 'block';

    // Quando ativar filtro de funil, recarregar estágios do funil selecionado
    if (!notifyAllFunnels) {
        const selectedFunnelId = document.getElementById('funnel-selector').value;
        if (selectedFunnelId) {
            loadStagesForFunnel(selectedFunnelId);
        }
    } else {
        // Se notificar todos os funis, usar estágios do funil padrão
        fetchSalesFlowStages();
    }
}

async function handleFunnelSelectorChange() {
    const selectedFunnelId = document.getElementById('funnel-selector').value;
    if (selectedFunnelId) {
        await loadStagesForFunnel(selectedFunnelId);
    }
}

async function loadStagesForFunnel(funnelId) {
    console.log(`stageNotificationConfig.js: Carregando estágios do funil ${funnelId}...`);

    // Verificar cache
    if (funnelStagesCache[funnelId]) {
        salesFlowStages = funnelStagesCache[funnelId];
        renderStagesCheckboxes();
        console.log(`stageNotificationConfig.js: Estágios do funil ${funnelId} carregados do cache:`, salesFlowStages.length);
        return;
    }

    try {
        const funnel = await getFunnel(funnelId);
        const stages = funnel.stages || [];
        funnelStagesCache[funnelId] = stages;
        salesFlowStages = stages;
        renderStagesCheckboxes();
        console.log(`stageNotificationConfig.js: Estágios do funil ${funnelId} carregados:`, stages.length);
    } catch (error) {
        console.error(`stageNotificationConfig.js: Erro ao carregar estágios do funil ${funnelId}:`, error);
        salesFlowStages = [];
        renderStagesCheckboxes();
    }
}

async function fetchSalesFlowStages() {
    console.log('stageNotificationConfig.js: Buscando etapas do funil padrão...');
    try {
        const config = await getSalesFlowConfig();
        salesFlowStages = config.stages || [];
        renderStagesCheckboxes();
        console.log('stageNotificationConfig.js: Etapas carregadas:', salesFlowStages.length);
    } catch (error) {
        console.error('stageNotificationConfig.js: Erro ao buscar etapas:', error);
        salesFlowStages = [];
        renderStagesCheckboxes();
    }
}

async function fetchAvailableFunnels() {
    console.log('stageNotificationConfig.js: Buscando funis disponíveis...');
    const funnelSelector = document.getElementById('funnel-selector');

    try {
        const response = await getFunnelsList();
        availableFunnels = response.funnels || [];
        console.log('stageNotificationConfig.js: Funis carregados:', availableFunnels.length);

        // Popular seletor de funis
        funnelSelector.innerHTML = '';

        if (availableFunnels.length === 0) {
            funnelSelector.innerHTML = '<option value="">Nenhum funil disponível</option>';
            return;
        }

        availableFunnels.forEach(funnel => {
            const option = document.createElement('option');
            option.value = funnel.funnel_id;
            option.textContent = funnel.name + (funnel.is_default ? ' (Padrão)' : '');
            funnelSelector.appendChild(option);
        });

        // Selecionar o funil padrão inicialmente
        const defaultFunnel = availableFunnels.find(f => f.is_default);
        if (defaultFunnel) {
            funnelSelector.value = defaultFunnel.funnel_id;
        }

    } catch (error) {
        console.error('stageNotificationConfig.js: Erro ao buscar funis:', error);
        funnelSelector.innerHTML = '<option value="">Erro ao carregar funis</option>';
        availableFunnels = [];
    }
}

function renderStagesCheckboxes() {
    const container = document.getElementById('stages-list');

    if (salesFlowStages.length === 0) {
        container.innerHTML = '<p class="text-muted">Nenhuma etapa configurada no funil de vendas.</p>';
        return;
    }

    // Ordena as etapas por stage_number
    const sortedStages = [...salesFlowStages].sort((a, b) => (a.stage_number || 0) - (b.stage_number || 0));

    // Usa stage.objective (nome da etapa) e stage.stage_number para identificação
    // value = stage_number para enviar ao backend
    let checkboxesHtml = sortedStages.map((stage) => {
        const stageNumber = stage.stage_number;
        const stageName = stage.objective || `Estágio ${stageNumber}`;
        return `
            <div class="stage-checkbox-item">
                <input type="checkbox" id="stage-${stageNumber}" value="${stageNumber}" data-stage-name="${stageName}" class="stage-checkbox">
                <label for="stage-${stageNumber}">${stageName}</label>
            </div>
        `;
    }).join('');

    // Adiciona a etapa especial de Agendamentos (igual ao Kanban)
    // value = 0 para identificar como etapa especial "scheduled"
    checkboxesHtml += `
        <div class="stage-checkbox-item">
            <input type="checkbox" id="stage-scheduled" value="0" data-stage-name="Agendamentos" class="stage-checkbox">
            <label for="stage-scheduled">Agendamentos</label>
        </div>
    `;

    container.innerHTML = checkboxesHtml;
}

async function fetchConfig() {
    console.log('stageNotificationConfig.js: Buscando configuração...');
    const feedbackContainer = document.getElementById('form-feedback');

    try {
        const config = await getStageChangeNotificationConfig();

        document.getElementById('stage-notification-enabled').checked = config.enabled !== false;
        document.getElementById('notification-phone').value = config.notification_whatsapp_number || '';
        document.getElementById('notify-all-funnels').checked = config.notify_all_funnels !== false;
        document.getElementById('notify-all-stages').checked = config.notify_all_stages !== false;
        // Backend usa default_message_template
        document.getElementById('message-template').value = config.default_message_template || DEFAULT_MESSAGE_TEMPLATE;

        // Restaurar seleção de funil se houver regras com funnel_id específico
        if (config.stage_rules && Array.isArray(config.stage_rules) && config.stage_rules.length > 0) {
            console.log('stageNotificationConfig.js: Restaurando configuração de funis e etapas:', config.stage_rules);

            // Buscar funnel_id das regras (se houver)
            const ruleFunnelId = config.stage_rules[0]?.funnel_id;
            if (ruleFunnelId) {
                const funnelSelector = document.getElementById('funnel-selector');
                funnelSelector.value = ruleFunnelId;

                // Se há um funil específico, carregar os estágios desse funil
                await loadStagesForFunnel(ruleFunnelId);
            }

            // Marcar etapas selecionadas
            config.stage_rules.forEach(rule => {
                // Suporta tanto objeto { stage_number } quanto número direto
                const stageNumber = typeof rule === 'object' ? rule.stage_number : rule;
                const checkbox = document.querySelector(`.stage-checkbox[value="${stageNumber}"]`);
                console.log(`stageNotificationConfig.js: Buscando checkbox para stage_number=${stageNumber}, encontrado:`, !!checkbox);
                if (checkbox) {
                    checkbox.checked = true;
                    console.log(`stageNotificationConfig.js: Checkbox stage_number=${stageNumber} marcado como checked.`);
                }
            });
        }

        handleToggle();
        handleNotifyAllFunnelsToggle();
        handleNotifyAllToggle();
        console.log('stageNotificationConfig.js: Configuração carregada com sucesso.');
    } catch (error) {
        console.error('stageNotificationConfig.js: Erro ao buscar configuração:', error);
        showFeedback(feedbackContainer, error.message || 'Erro ao carregar configuração.', 'error');
    }
}

async function handleFormSubmit(event) {
    event.preventDefault();
    const feedbackContainer = document.getElementById('form-feedback');
    const submitBtn = event.currentTarget.querySelector('button[type="submit"]');

    setLoadingState(submitBtn, true);
    clearFeedback(feedbackContainer);

    const enabled = document.getElementById('stage-notification-enabled').checked;
    const notificationPhone = document.getElementById('notification-phone').value.trim();
    const notifyAllFunnels = document.getElementById('notify-all-funnels').checked;
    const notifyAllStages = document.getElementById('notify-all-stages').checked;
    const messageTemplate = document.getElementById('message-template').value.trim();

    // Obter funnel_id selecionado (se filtro de funil estiver ativo)
    const selectedFunnelId = notifyAllFunnels ? null : document.getElementById('funnel-selector').value;

    // Coletar etapas selecionadas e converter para o formato esperado pelo backend
    // Backend espera: List[StageNotificationRule] com { stage_number: int, enabled: bool, message_template: str, funnel_id: str|null }
    const selectedStageRules = [];
    document.querySelectorAll('.stage-checkbox:checked').forEach(cb => {
        const stageNumber = parseInt(cb.value, 10);
        selectedStageRules.push({
            stage_number: stageNumber,
            enabled: true,
            message_template: messageTemplate || DEFAULT_MESSAGE_TEMPLATE,
            funnel_id: selectedFunnelId || null
        });
    });

    // Validação
    if (enabled && !notificationPhone) {
        showFeedback(feedbackContainer, 'Número de WhatsApp para notificação é obrigatório quando a funcionalidade está habilitada.', 'error');
        setLoadingState(submitBtn, false);
        return;
    }

    const cleanedNumber = notificationPhone.replace(/\D/g, '');
    if (enabled && cleanedNumber && (cleanedNumber.length < 10 || cleanedNumber.length > 15)) {
        showFeedback(feedbackContainer, 'Número de WhatsApp inválido. Deve ter entre 10 e 15 dígitos.', 'error');
        setLoadingState(submitBtn, false);
        return;
    }

    if (enabled && !notifyAllStages && selectedStageRules.length === 0) {
        showFeedback(feedbackContainer, 'Selecione pelo menos uma etapa para notificação.', 'error');
        setLoadingState(submitBtn, false);
        return;
    }

    if (enabled && !notifyAllFunnels && !selectedFunnelId) {
        showFeedback(feedbackContainer, 'Selecione um funil para notificação.', 'error');
        setLoadingState(submitBtn, false);
        return;
    }

    const configData = {
        enabled: enabled,
        notification_whatsapp_number: cleanedNumber || null,
        notify_all_funnels: notifyAllFunnels,
        notify_all_stages: notifyAllStages,
        stage_rules: notifyAllStages ? [] : selectedStageRules,
        default_message_template: messageTemplate || DEFAULT_MESSAGE_TEMPLATE
    };

    try {
        const response = await setStageChangeNotificationConfig(configData);
        showFeedback(feedbackContainer, response.message || 'Configuração salva com sucesso!', 'success');
        console.log('stageNotificationConfig.js: Configuração salva com sucesso.');
    } catch (error) {
        console.error('stageNotificationConfig.js: Erro ao salvar configuração:', error);
        showFeedback(feedbackContainer, error.message || 'Erro ao salvar configuração.', 'error');
    } finally {
        setLoadingState(submitBtn, false);
    }
}
