// static/js/pages/salesFlowConfig.js
import { getSalesFlowConfig, setSalesFlowConfig, generateSalesFlowTemplate } from '../api.js';
import {
    getFunnelsList, getFunnel, createFunnel, updateFunnel, deleteFunnel,
    setDefaultFunnel, migrateLegacyFunnel
} from '../api.js';
import { showFeedback, clearFeedback, setLoadingState, createElement, replaceFeatherIcons } from '../utils.js';

let salesFlowStages = [];
let audioFiles = new Map(); // To store file objects for upload
let currentFunnelId = null; // Track the currently selected funnel
let allFunnels = []; // Store all available funnels

export async function loadSalesFlowConfigPage(container) {
    console.log('salesFlowConfig.js: Carregando página de Configuração do Funil de Vendas...');
    container.innerHTML = `
        <header class="page-header">
            <h1 class="page-title"><i data-feather="git-branch" class="feather-title"></i> Funil de Vendas</h1>
            <p class="page-description">Crie e gerencie os estágios do seu funil de vendas automatizado.</p>
        </header>

        <!-- Funnel Selector Card -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="layers" class="feather-title-sm"></i> Gerenciador de Funis</h3>
            </div>
            <div class="card-body">
                <div class="funnel-selector-container flex items-center gap-4 flex-wrap">
                    <label for="funnel-select" class="label m-0 whitespace-nowrap">Funil Ativo:</label>
                    <select id="funnel-select" class="select flex-1" style="min-width: 200px;">
                        <option value="">Carregando funis...</option>
                    </select>
                    <div class="funnel-actions">
                        <button type="button" id="btn-new-funnel" class="btn btn-secondary" title="Criar Novo Funil">
                            <i data-feather="plus"></i> Novo Funil
                        </button>
                        <button type="button" id="btn-set-default-funnel" class="btn btn-outline" title="Definir como Padrão">
                            <i data-feather="star"></i> Definir Padrão
                        </button>
                        <button type="button" id="btn-delete-funnel" class="btn btn-danger" title="Excluir Funil">
                            <i data-feather="trash-2"></i>
                        </button>
                    </div>
                </div>
                <div id="funnel-selector-feedback" class="feedback-message mt-2"></div>
            </div>
        </div>

        <div class="card">
             <div class="card-header">
                <h3 class="card-title"><i data-feather="zap" class="feather-title-sm"></i> Geração com IA</h3>
            </div>
            <div class="card-body">
                <form id="generate-sales-flow-form">
                    <div class="form-group">
                        <label for="ai-funnel-tips" class="label">Dicas para a IA (Opcional):</label>
                        <textarea id="ai-funnel-tips" class="textarea" rows="3" placeholder="Ex: Foque em agendar uma demonstração. Use uma linguagem mais informal."></textarea>
                        <p class="form-text">Forneça instruções adicionais para a IA gerar um funil mais alinhado com sua estratégia.</p>
                    </div>
                    <button type="submit" class="btn btn-success btn-gerar-funil-ia">
                        <i data-feather="cpu"></i> Gerar Funil de Vendas com IA
                    </button>
                </form>
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="edit" class="feather-title-sm"></i> Editor do Funil</h3>
            </div>
            <div class="card-body">
                <form id="sales-flow-form" class="form">
                    <div id="sales-flow-stages-container" class="sales-flow-editor">
                        <!-- Stages will be rendered here -->
                    </div>
                    <div class="btn-actions-end">
                        <button type="button" id="add-sales-flow-stage-btn" class="btn btn-secondary">
                            <i data-feather="plus"></i> Adicionar Estágio
                        </button>
                        <button type="submit" class="btn btn-primary">
                            <i data-feather="save"></i> Salvar Funil de Vendas
                        </button>
                    </div>
                    <div id="sales-flow-feedback" class="feedback-message"></div>
                </form>
            </div>
        </div>

        <!-- Modal for Creating New Funnel -->
        <div id="create-funnel-modal" style="display: none;">
            <div class="modal-overlay"></div>
            <div class="modal-content">
                <div class="modal-header">
                    <h3 class="modal-title">Criar Novo Funil</h3>
                    <button type="button" class="btn-close-modal">&times;</button>
                </div>
                <div class="modal-body">
                    <form id="create-funnel-form">
                        <div class="form-group">
                            <label for="new-funnel-name" class="label">Nome do Funil:</label>
                            <input type="text" id="new-funnel-name" class="input" required placeholder="Ex: Funil de Leads Frios">
                        </div>
                        <div class="form-group">
                            <label for="new-funnel-description" class="label">Descrição (opcional):</label>
                            <textarea id="new-funnel-description" class="textarea" rows="2" placeholder="Descrição do propósito deste funil"></textarea>
                        </div>
                        <div class="form-group">
                            <label class="label">
                                <input type="checkbox" id="copy-from-current"> Copiar estágios do funil atual
                            </label>
                        </div>
                        <div class="form-group">
                            <label class="label">
                                <input type="checkbox" id="set-as-default"> Definir como funil padrão
                            </label>
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary btn-cancel-modal">Cancelar</button>
                    <button type="button" id="btn-confirm-create-funnel" class="btn btn-primary">Criar Funil</button>
                </div>
            </div>
        </div>
    `;

    // Event listeners
    console.log('salesFlowConfig.js: Configurando event listeners...');

    try {
        document.getElementById('generate-sales-flow-form').addEventListener('submit', handleGenerateSalesFlow);
        document.getElementById('sales-flow-form').addEventListener('submit', handleSalesFlowSubmit);
        document.getElementById('add-sales-flow-stage-btn').addEventListener('click', addStage);

        // Funnel selector events
        const btnNewFunnel = document.getElementById('btn-new-funnel');
        if (btnNewFunnel) {
            btnNewFunnel.addEventListener('click', () => {
                console.log('salesFlowConfig.js: Botão Novo Funil clicado');
                showCreateFunnelModal();
            });
            console.log('salesFlowConfig.js: Event listener btn-new-funnel configurado');
        } else {
            console.error('salesFlowConfig.js: ERRO - btn-new-funnel não encontrado!');
        }

        document.getElementById('funnel-select').addEventListener('change', handleFunnelChange);
        document.getElementById('btn-set-default-funnel').addEventListener('click', handleSetDefaultFunnel);
        document.getElementById('btn-delete-funnel').addEventListener('click', handleDeleteFunnel);

        // Modal events - com verificação de existência
        const modalCloseBtn = document.querySelector('#create-funnel-modal .btn-close-modal');
        const modalCancelBtn = document.querySelector('#create-funnel-modal .btn-cancel-modal');
        const modalOverlay = document.querySelector('#create-funnel-modal .modal-overlay');
        const modalConfirmBtn = document.getElementById('btn-confirm-create-funnel');

        if (modalCloseBtn) modalCloseBtn.addEventListener('click', hideCreateFunnelModal);
        if (modalCancelBtn) modalCancelBtn.addEventListener('click', hideCreateFunnelModal);
        if (modalOverlay) modalOverlay.addEventListener('click', hideCreateFunnelModal);
        if (modalConfirmBtn) modalConfirmBtn.addEventListener('click', handleCreateFunnel);

        console.log('salesFlowConfig.js: Todos os event listeners configurados com sucesso');
    } catch (error) {
        console.error('salesFlowConfig.js: ERRO ao configurar event listeners:', error);
    }

    // Load funnels first, then load the selected funnel's stages
    await loadFunnelsList();
    console.log('salesFlowConfig.js: Página carregada e configurações iniciais buscadas.');
}

async function fetchSalesFlowConfig() {
    const stagesContainer = document.getElementById('sales-flow-stages-container');
    stagesContainer.innerHTML = `<div class="spinner-container"><div class="loading-spinner"></div></div>`;
    try {
        const config = await getSalesFlowConfig();
        salesFlowStages = config.stages || [];
        audioFiles.clear();
        renderSalesFlowStages();
    } catch (error) {
        console.error('Erro ao buscar configuração do funil:', error);
        showFeedback(document.getElementById('sales-flow-feedback'), 'Erro ao carregar o funil de vendas.', 'error');
    }
}

function renderSalesFlowStages() {
    const stagesContainer = document.getElementById('sales-flow-stages-container');
    const saveButton = document.querySelector('#sales-flow-form button[type="submit"]');
    stagesContainer.innerHTML = '';

    // Ordena o array principal. Isso é seguro porque a renderização é sempre completa.
    salesFlowStages.sort((a, b) => a.stage_number - b.stage_number);

    if (salesFlowStages.length === 0) {
        stagesContainer.innerHTML = '<p>Nenhum estágio definido. Adicione um estágio para começar.</p>';
        if (saveButton) {
            saveButton.disabled = true;
        }
    } else {
        salesFlowStages.forEach((stage, index) => {
            const stageElement = createStageElement(stage, index);
            stagesContainer.appendChild(stageElement);
        });
        if (saveButton) {
            saveButton.disabled = false;
        }
    }
    replaceFeatherIcons();
}

function createStageElement(stage, index) {
    const stageCard = createElement('div', { className: 'card editor-item', 'data-stage-index': index }, [
        createElement('div', { className: 'card-header' }, [
            createElement('h3', { className: 'card-title' }, `Estágio ${stage.stage_number}`),
            createElement('button', { type: 'button', className: 'btn btn-icon btn-danger btn-delete-sales-flow-stage', title: 'Remover Estágio' }, [
                createElement('i', { 'data-feather': 'trash' })
            ])
        ]),
        createElement('div', { className: 'card-body' }, [
            createElement('div', { className: 'form-group' }, [
                createElement('label', { className: 'label' }, 'Número do Estágio:'),
                createElement('input', { type: 'number', className: 'input standard-width', value: stage.stage_number, 'data-field': 'stage_number', min: '1' })
            ]),
            createElement('div', { className: 'form-group' }, [
                createElement('label', { className: 'label' }, 'Objetivo do Estágio:'),
                createElement('input', { type: 'text', className: 'input', value: stage.objective, 'data-field': 'objective', placeholder: 'Ex: Qualificar o lead' })
            ]),
            createElement('div', { className: 'form-group' }, [
                createElement('label', { className: 'label' }, 'Descrição do Gatilho:'),
                createElement('input', { type: 'text', className: 'input', value: stage.trigger_description || '', 'data-field': 'trigger_description', placeholder: 'Ex: Cliente respondeu positivamente' })
            ]),
            createElement('div', { className: 'form-group' }, [
                createElement('label', { className: 'label' }, 'Tipo de Ação:'),
                createElement('select', { className: 'select action-type-select', 'data-field': 'action_type' }, [
                    createElement('option', { value: 'sequence' }, 'Sequência de Mensagens'),
                    createElement('option', { value: 'ask_llm' }, 'Perguntar à IA')
                ])
            ]),
            // Action content container will be populated dynamically
            createElement('div', { className: 'action-content-container' })
        ])
    ]);

    // Render the initial action content
    renderActionContent(stageCard, stage, index);

    // Event Listeners for the stage
    stageCard.querySelector('.btn-delete-sales-flow-stage').addEventListener('click', () => removeStage(index));
    
    const actionTypeSelect = stageCard.querySelector('.action-type-select');
    // Garante que o select sempre reflita o valor correto do tipo de ação
    actionTypeSelect.value = stage.action_type;
    actionTypeSelect.addEventListener('change', (e) => {
        const newActionType = e.target.value;
        console.log(`🔄 Mudando tipo de ação do estágio ${index} de "${stage.action_type}" para "${newActionType}"`);
        handleActionTypeChange(index, newActionType, stageCard);
    });
    
    // Event listeners for other fields
    stageCard.querySelectorAll('input[data-field], textarea[data-field]').forEach(input => {
        if (!input.classList.contains('action-type-select')) {
            input.addEventListener('change', (e) => updateStageData(index, e.target));
        }
    });

    return stageCard;
}

// ✅ NOVA FUNÇÃO: Gerencia especificamente a mudança de tipo de ação
function handleActionTypeChange(stageIndex, newActionType, stageCard) {
    const stage = salesFlowStages[stageIndex];
    const oldActionType = stage.action_type;
    
    console.log(`🔄 handleActionTypeChange: Estágio ${stageIndex}, de "${oldActionType}" para "${newActionType}"`);
    
    // Atualiza o tipo de ação no objeto
    stage.action_type = newActionType;
    
    // Reseta e configura os campos de ação baseado no novo tipo
    if (newActionType === 'sequence') {
        // Limpa campos de LLM e inicializa sequência
        stage.action_llm_prompt = null;
        if (!stage.action_sequence || !Array.isArray(stage.action_sequence)) {
            stage.action_sequence = [];
        }
        console.log(`✅ Configurado para sequência. action_sequence:`, stage.action_sequence);
    } else if (newActionType === 'ask_llm') {
        // Limpa sequência e inicializa prompt LLM
        stage.action_sequence = null;
        if (!stage.action_llm_prompt) {
            stage.action_llm_prompt = '';
        }
        console.log(`✅ Configurado para LLM. action_llm_prompt:`, stage.action_llm_prompt);
    }
    
    // Re-renderiza o conteúdo da ação
    renderActionContent(stageCard, stage, stageIndex);
    
    console.log(`✅ Estágio ${stageIndex} atualizado:`, salesFlowStages[stageIndex]);
}

// ✅ NOVA FUNÇÃO: Renderiza o conteúdo da ação dinamicamente
function renderActionContent(stageCard, stage, stageIndex) {
    const actionContainer = stageCard.querySelector('.action-content-container');
    actionContainer.innerHTML = '';
    
    if (stage.action_type === 'sequence') {
        const sequenceEditor = createSequenceEditor(stage.action_sequence || [], stageIndex);
        actionContainer.appendChild(sequenceEditor);
    } else if (stage.action_type === 'ask_llm') {
        const llmPromptEditor = createLlmPromptEditor(stage.action_llm_prompt || '', stageIndex);
        actionContainer.appendChild(llmPromptEditor);
    }
    
    // Re-aplica os ícones Feather
    replaceFeatherIcons();
}

function createSequenceEditor(sequence, stageIndex) {
    const container = createElement('div', { className: 'action-content-editor' });
    const legend = createElement('legend', { className: 'legend' }, 'Sequência de Ações');
    const sequenceContainer = createElement('div', { className: 'sequence-editor' });

    if (sequence.length > 0) {
        sequence.forEach((action, actionIndex) => {
            sequenceContainer.appendChild(createSequenceActionElement(action, stageIndex, actionIndex));
        });
    }

    const addButton = createElement('button', { type: 'button', className: 'btn btn-secondary btn-add-sequence-item' }, [
        createElement('i', { 'data-feather': 'plus' }), ' Adicionar Ação'
    ]);
    addButton.addEventListener('click', () => addSequenceAction(stageIndex));

    container.append(legend, sequenceContainer, addButton);
    return container;
}

function createLlmPromptEditor(prompt, stageIndex) {
    const container = createElement('div', { className: 'action-content-editor' });
    const legend = createElement('legend', { className: 'legend' }, 'Prompt para a IA');
    const textarea = createElement('textarea', {
        className: 'textarea',
        rows: 5,
        'data-field': 'action_llm_prompt',
        placeholder: 'Instruções para a IA neste estágio...'
    }, prompt);
    textarea.addEventListener('change', (e) => updateStageData(stageIndex, e.target));
    container.append(legend, textarea);
    return container;
}

function createSequenceActionElement(action, stageIndex, actionIndex) {
    const actionElement = createElement('div', { className: 'sequence-action-item', 'data-action-index': actionIndex }, [
        createElement('div', { className: 'sequence-item-header' }, [
            createElement('span', {}, `Ação ${actionIndex + 1}`),
            createElement('button', { type: 'button', className: 'btn btn-icon btn-danger btn-remove-sequence-item', title: 'Remover Ação' }, [
                createElement('i', { 'data-feather': 'x' })
            ])
        ]),
        createElement('div', { className: 'form-group' }, [
            createElement('label', { className: 'label' }, 'Tipo de Ação:'),
            createElement('select', { className: 'select', 'data-field': 'type' }, [
                createElement('option', { value: 'send_text' }, 'Enviar Texto'),
                createElement('option', { value: 'send_audio' }, 'Enviar Áudio')
            ])
        ]),
        createElement('div', { className: 'form-group' }, [
            createElement('label', { className: 'label' }, 'Atraso (ms):'),
            createElement('input', { type: 'number', className: 'input standard-width', value: action.delay_ms || 0, 'data-field': 'delay_ms', min: '0' })
        ]),
        // Content fields are conditional
    ]);

    const typeSelect = actionElement.querySelector('select[data-field="type"]');
    // ✅ CORREÇÃO: Define o valor do select diretamente para garantir a seleção correta.
    typeSelect.value = action.type;

    const contentContainer = document.createElement('div');
    
    const renderContentFields = (type) => {
        contentContainer.innerHTML = '';
        if (type === 'send_text') {
            const textarea = createElement('textarea', { className: 'textarea', 'data-field': 'text', rows: 3, placeholder: 'Digite o texto da mensagem...' }, action.text || '');
            contentContainer.appendChild(createElement('div', { className: 'form-group' }, [
                createElement('label', { className: 'label' }, 'Texto:'),
                textarea
            ]));
        } else if (type === 'send_audio') {
            const fileInput = createElement('input', { type: 'file', className: 'input sequence-action-file-input', accept: '.ogg,.mp3,.wav,.m4a' });
            const fileNameDisplay = createElement('p', { className: 'form-text' }, `Arquivo atual: ${action.audio_file || 'Nenhum'}`);
            contentContainer.appendChild(createElement('div', { className: 'form-group' }, [
                createElement('label', { className: 'label' }, 'Arquivo de Áudio:'),
                fileInput,
                fileNameDisplay
            ]));
        }
    };

    renderContentFields(action.type);
    actionElement.appendChild(contentContainer);

    // Event Listeners for the action item
    actionElement.querySelector('.btn-remove-sequence-item').addEventListener('click', () => removeSequenceAction(stageIndex, actionIndex));
    typeSelect.addEventListener('change', (e) => {
        const newType = e.target.value;
        salesFlowStages[stageIndex].action_sequence[actionIndex].type = newType;
        renderContentFields(newType);
        // Re-attach listeners to new fields
        actionElement.querySelectorAll('input, textarea').forEach(input => {
            input.addEventListener('change', (e) => updateSequenceActionData(stageIndex, actionIndex, e.target));
        });
    });
    actionElement.querySelectorAll('input, textarea, select').forEach(input => {
        input.addEventListener('change', (e) => updateSequenceActionData(stageIndex, actionIndex, e.target));
    });

    return actionElement;
}

// --- Data Manipulation Functions ---

// ✅ FUNÇÃO CORRIGIDA: Não interfere mais com mudanças de action_type
function updateStageData(stageIndex, target) {
    const field = target.dataset.field;
    let value = target.type === 'number' ? parseInt(target.value) : target.value;
    
    // ✅ REMOVIDO: A lógica de mudança de action_type foi movida para handleActionTypeChange()
    // Agora esta função apenas atualiza campos simples
    
    salesFlowStages[stageIndex][field] = value;
    console.log(`📝 Campo "${field}" do estágio ${stageIndex} atualizado para:`, value);
}

function updateSequenceActionData(stageIndex, actionIndex, target) {
    const field = target.dataset.field;
    let value = target.value;

    if (target.type === 'file') {
        const file = target.files;
        if (file) {
            const uniqueFileName = `${Date.now()}_${file.name}`;
            audioFiles.set(uniqueFileName, file);
            salesFlowStages[stageIndex].action_sequence[actionIndex]['audio_file'] = uniqueFileName;
            // Update display
            target.nextElementSibling.textContent = `Novo arquivo: ${file.name}`;
        }
        return;
    }
    
    if (target.type === 'number') {
        value = parseInt(value);
    }

    salesFlowStages[stageIndex].action_sequence[actionIndex][field] = value;
    console.log(`Action ${stageIndex}-${actionIndex} updated:`, salesFlowStages[stageIndex].action_sequence[actionIndex]);
}

function addStage() {
    const newStageNumber = salesFlowStages.length > 0 ? Math.max(...salesFlowStages.map(s => s.stage_number)) + 1 : 1;
    salesFlowStages.push({
        stage_number: newStageNumber,
        objective: '',
        trigger_description: '',
        action_type: 'sequence',
        action_sequence: [],
        action_llm_prompt: null
    });
    renderSalesFlowStages();
}

function removeStage(index) {
    if (confirm(`Tem certeza que deseja remover o Estágio ${salesFlowStages[index].stage_number}?`)) {
        salesFlowStages.splice(index, 1);
        renderSalesFlowStages();
    }
}

function addSequenceAction(stageIndex) {
    // ✅ CORREÇÃO: Garantir que action_sequence existe antes de adicionar
    if (!salesFlowStages[stageIndex].action_sequence) {
        salesFlowStages[stageIndex].action_sequence = [];
    }
    
    salesFlowStages[stageIndex].action_sequence.push({
        type: 'send_text',
        delay_ms: 2000,
        text: '',
        audio_file: null
    });
    renderSalesFlowStages();
}

function removeSequenceAction(stageIndex, actionIndex) {
    salesFlowStages[stageIndex].action_sequence.splice(actionIndex, 1);
    renderSalesFlowStages();
}

// --- Funnel Management Functions ---

async function loadFunnelsList() {
    const select = document.getElementById('funnel-select');
    const feedbackContainer = document.getElementById('funnel-selector-feedback');

    try {
        // First, try to migrate legacy funnel if needed
        try {
            await migrateLegacyFunnel();
        } catch (e) {
            console.log('No legacy funnel migration needed or already migrated');
        }

        const response = await getFunnelsList();
        allFunnels = response.funnels || [];

        select.innerHTML = '';

        if (allFunnels.length === 0) {
            select.innerHTML = '<option value="">Nenhum funil encontrado</option>';
            showFeedback(feedbackContainer, 'Crie seu primeiro funil de vendas!', 'info');
            return;
        }

        allFunnels.forEach(funnel => {
            const option = document.createElement('option');
            option.value = funnel.funnel_id;
            option.textContent = funnel.name + (funnel.is_default ? ' ⭐' : '') + ` (${funnel.stages_count} estágios)`;
            option.dataset.isDefault = funnel.is_default;
            select.appendChild(option);
        });

        // Select the default funnel or the first one
        const defaultFunnel = allFunnels.find(f => f.is_default) || allFunnels[0];
        if (defaultFunnel) {
            select.value = defaultFunnel.funnel_id;
            currentFunnelId = defaultFunnel.funnel_id;
            await loadFunnelStages(defaultFunnel.funnel_id);
        }

        updateFunnelButtonStates();
        replaceFeatherIcons();

    } catch (error) {
        console.error('Erro ao carregar lista de funis:', error);
        select.innerHTML = '<option value="">Erro ao carregar funis</option>';
        showFeedback(feedbackContainer, 'Erro ao carregar funis: ' + error.message, 'error');
    }
}

async function loadFunnelStages(funnelId) {
    const stagesContainer = document.getElementById('sales-flow-stages-container');
    stagesContainer.innerHTML = `<div class="spinner-container"><div class="loading-spinner"></div></div>`;

    try {
        const funnel = await getFunnel(funnelId);
        salesFlowStages = funnel.stages || [];
        currentFunnelId = funnelId;
        audioFiles.clear();
        renderSalesFlowStages();
        console.log(`Loaded ${salesFlowStages.length} stages from funnel "${funnel.name}"`);
    } catch (error) {
        console.error('Erro ao carregar estágios do funil:', error);
        showFeedback(document.getElementById('sales-flow-feedback'), 'Erro ao carregar estágios do funil.', 'error');
    }
}

async function handleFunnelChange(event) {
    const funnelId = event.target.value;
    if (funnelId && funnelId !== currentFunnelId) {
        await loadFunnelStages(funnelId);
        updateFunnelButtonStates();
    }
}

function updateFunnelButtonStates() {
    const select = document.getElementById('funnel-select');
    const selectedOption = select.options[select.selectedIndex];
    const setDefaultBtn = document.getElementById('btn-set-default-funnel');
    const deleteBtn = document.getElementById('btn-delete-funnel');

    if (selectedOption) {
        const isDefault = selectedOption.dataset.isDefault === 'true';
        setDefaultBtn.disabled = isDefault;
        setDefaultBtn.title = isDefault ? 'Este já é o funil padrão' : 'Definir como Padrão';
        deleteBtn.disabled = isDefault;
        deleteBtn.title = isDefault ? 'Não é possível excluir o funil padrão' : 'Excluir Funil';
    }
}

function showCreateFunnelModal() {
    console.log('salesFlowConfig.js: showCreateFunnelModal() chamada');
    const modal = document.getElementById('create-funnel-modal');

    if (!modal) {
        console.error('salesFlowConfig.js: ERRO - Modal #create-funnel-modal não encontrado!');
        return;
    }

    console.log('salesFlowConfig.js: Modal encontrado, definindo display para flex');
    modal.style.display = 'flex';

    // Limpar campos do formulário
    const nameInput = document.getElementById('new-funnel-name');
    const descInput = document.getElementById('new-funnel-description');
    const copyCheckbox = document.getElementById('copy-from-current');
    const defaultCheckbox = document.getElementById('set-as-default');

    if (nameInput) nameInput.value = '';
    if (descInput) descInput.value = '';
    if (copyCheckbox) copyCheckbox.checked = false;
    if (defaultCheckbox) defaultCheckbox.checked = false;

    console.log('salesFlowConfig.js: Modal aberto com sucesso');
}

function hideCreateFunnelModal() {
    const modal = document.getElementById('create-funnel-modal');
    modal.style.display = 'none';
}

async function handleCreateFunnel() {
    const name = document.getElementById('new-funnel-name').value.trim();
    const description = document.getElementById('new-funnel-description').value.trim();
    const copyFromCurrent = document.getElementById('copy-from-current').checked;
    const setAsDefault = document.getElementById('set-as-default').checked;
    const feedbackContainer = document.getElementById('funnel-selector-feedback');
    const btn = document.getElementById('btn-confirm-create-funnel');

    if (!name) {
        showFeedback(feedbackContainer, 'Por favor, insira um nome para o funil.', 'error');
        return;
    }

    setLoadingState(btn, true);

    try {
        const payload = {
            name,
            description: description || null,
            copy_from_funnel_id: copyFromCurrent ? currentFunnelId : null,
            set_as_default: setAsDefault
        };

        const response = await createFunnel(payload);

        hideCreateFunnelModal();
        showFeedback(feedbackContainer, response.message || 'Funil criado com sucesso!', 'success');

        // Reload funnels list and select the new one
        await loadFunnelsList();
        const select = document.getElementById('funnel-select');
        if (response.funnel) {
            select.value = response.funnel.funnel_id;
            currentFunnelId = response.funnel.funnel_id;
            await loadFunnelStages(response.funnel.funnel_id);
        }

    } catch (error) {
        console.error('Erro ao criar funil:', error);
        showFeedback(feedbackContainer, 'Erro ao criar funil: ' + error.message, 'error');
    } finally {
        setLoadingState(btn, false);
    }
}

async function handleSetDefaultFunnel() {
    const select = document.getElementById('funnel-select');
    const funnelId = select.value;
    const feedbackContainer = document.getElementById('funnel-selector-feedback');

    if (!funnelId) {
        showFeedback(feedbackContainer, 'Selecione um funil primeiro.', 'error');
        return;
    }

    const btn = document.getElementById('btn-set-default-funnel');
    setLoadingState(btn, true);

    try {
        const response = await setDefaultFunnel(funnelId);
        showFeedback(feedbackContainer, response.message || 'Funil definido como padrão!', 'success');
        await loadFunnelsList();
    } catch (error) {
        console.error('Erro ao definir funil padrão:', error);
        showFeedback(feedbackContainer, 'Erro ao definir funil padrão: ' + error.message, 'error');
    } finally {
        setLoadingState(btn, false);
    }
}

async function handleDeleteFunnel() {
    const select = document.getElementById('funnel-select');
    const funnelId = select.value;
    const selectedOption = select.options[select.selectedIndex];
    const funnelName = selectedOption ? selectedOption.textContent : funnelId;
    const feedbackContainer = document.getElementById('funnel-selector-feedback');

    if (!funnelId) {
        showFeedback(feedbackContainer, 'Selecione um funil primeiro.', 'error');
        return;
    }

    const isDefault = selectedOption?.dataset.isDefault === 'true';
    if (isDefault) {
        showFeedback(feedbackContainer, 'Não é possível excluir o funil padrão. Defina outro funil como padrão primeiro.', 'error');
        return;
    }

    if (!confirm(`Tem certeza que deseja excluir o funil "${funnelName}"?\n\nEsta ação não pode ser desfeita.`)) {
        return;
    }

    const btn = document.getElementById('btn-delete-funnel');
    setLoadingState(btn, true);

    try {
        const response = await deleteFunnel(funnelId);
        showFeedback(feedbackContainer, response.message || 'Funil excluído com sucesso!', 'success');
        await loadFunnelsList();
    } catch (error) {
        console.error('Erro ao excluir funil:', error);
        showFeedback(feedbackContainer, 'Erro ao excluir funil: ' + error.message, 'error');
    } finally {
        setLoadingState(btn, false);
    }
}

// --- Form Submission Handlers ---

async function handleGenerateSalesFlow(event) {
    event.preventDefault();
    const btn = document.querySelector('.btn-gerar-funil-ia');
    const feedbackContainer = document.getElementById('sales-flow-feedback');
    setLoadingState(btn, true);
    clearFeedback(feedbackContainer);

    const tips = document.getElementById('ai-funnel-tips').value;

    try {
        await generateSalesFlowTemplate(tips);
        showFeedback(feedbackContainer, 'Funil de vendas gerado com sucesso! A página será recarregada.', 'success');
        setTimeout(() => window.location.reload(), 2000);
    } catch (error) {
        console.error('Erro ao gerar funil de vendas com IA:', error);
        showFeedback(feedbackContainer, error.message || 'Falha ao gerar funil de vendas.', 'error');
        setLoadingState(btn, false);
    }
}

async function handleSalesFlowSubmit(event) {
    event.preventDefault();
    const btn = document.querySelector('#sales-flow-form button[type="submit"]');
    const feedbackContainer = document.getElementById('sales-flow-feedback');
    setLoadingState(btn, true);
    clearFeedback(feedbackContainer);

    // Validação: impedir envio se não houver estágios
    if (salesFlowStages.length === 0) {
        showFeedback(feedbackContainer, 'Adicione pelo menos um estágio ao funil antes de salvar.', 'error');
        setLoadingState(btn, false);
        return;
    }

    try {
        // ✅ VALIDAÇÃO ADICIONAL: Garantir que os dados estão corretos antes de enviar
        console.log('🔍 Dados do funil antes do envio:', JSON.stringify(salesFlowStages, null, 2));

        // Create a clean version of stages for the JSON payload
        const stagesForPayload = salesFlowStages.map(stage => {
            const cleanStage = {...stage};

            // ✅ LÓGICA CORRIGIDA: Limpeza condicional baseada no action_type
            if (cleanStage.action_type === 'sequence') {
                // Remove campos LLM e garante que action_sequence existe
                delete cleanStage.action_llm_prompt;
                if (!cleanStage.action_sequence) {
                    cleanStage.action_sequence = [];
                }
            } else if (cleanStage.action_type === 'ask_llm') {
                // Remove campos de sequência e garante que action_llm_prompt existe
                delete cleanStage.action_sequence;
                if (!cleanStage.action_llm_prompt) {
                    cleanStage.action_llm_prompt = '';
                }
            }
            return cleanStage;
        });

        console.log('📤 Payload limpo para envio:', JSON.stringify(stagesForPayload, null, 2));

        // Use the new multiple funnels API if a funnel is selected
        if (currentFunnelId) {
            // Save to the selected funnel via the new API
            await updateFunnel(currentFunnelId, { stages: stagesForPayload });
            showFeedback(feedbackContainer, 'Funil de vendas salvo com sucesso!', 'success');

            // Refresh funnels list to update stages count
            await loadFunnelsList();
        } else {
            // Fallback to legacy API (for backwards compatibility)
            const stagesJson = JSON.stringify(stagesForPayload);
            const filesToUpload = Array.from(audioFiles.values());
            await setSalesFlowConfig(stagesJson, filesToUpload);
            showFeedback(feedbackContainer, 'Funil de vendas salvo com sucesso!', 'success');
            await fetchSalesFlowConfig(); // Refresh data
        }
    } catch (error) {
        console.error('Erro ao salvar funil de vendas:', error);
        showFeedback(feedbackContainer, error.message || 'Falha ao salvar o funil de vendas.', 'error');
    } finally {
        setLoadingState(btn, false);
    }
}
