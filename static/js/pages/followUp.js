// static/js/pages/followUp.js
import { getFollowUpConfig, setFollowUpConfig, getSalesFlowConfig, getFunnelsList, getFunnel } from '../api.js';
import { showFeedback, clearFeedback, setLoadingState, createElement, isValidTimeFormat, getStageName } from '../utils.js';

let followUpRules = []; // Variável global para manter o estado das regras
let availableStages = []; // Variável global para armazenar os estágios disponíveis
let availableFunnels = []; // Variável global para armazenar os funis disponíveis
let funnelStagesCache = {}; // Cache de estágios por funil

export async function loadFollowUpPage(container) {
    console.log('followUp.js: Carregando página de Follow-up...');
    container.innerHTML = `
        <header class="page-header">
            <h1 class="page-title"><i data-feather="message-square" class="feather-title"></i> Follow-up</h1>
            <p class="page-description">Configure regras automáticas de follow-up para seus prospects.</p>
        </header>

        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="list" class="feather-title-sm"></i> Regras de Follow-up</h3>
            </div>
            <div class="card-body">
                <form id="follow-up-form" class="form">
                    <div id="follow-up-rules-container">
                        <!-- Regras serão carregadas/adicionadas aqui -->
                        <div class="spinner-container"><div class="loading-spinner"></div></div>
                    </div>
                    <div class="btn-actions-end">
                        <button type="button" id="add-follow-up-rule-btn" class="btn btn-outline">
                            <i data-feather="plus"></i> Adicionar Regra
                        </button>
                        <button type="submit" class="btn btn-primary">
                            <i data-feather="save"></i> Salvar Regras
                        </button>
                    </div>
                    <div id="follow-up-feedback" class="feedback-message"></div>
                </form>
            </div>
        </div>
    `;
    console.log('followUp.js: HTML da página de Follow-up renderizado.');

    // Event Listeners
    document.getElementById('follow-up-form').addEventListener('submit', handleFollowUpSubmit);
    document.getElementById('add-follow-up-rule-btn').addEventListener('click', addFollowUpRule);
    console.log('followUp.js: Event listeners para submit do formulário e botão de adicionar regra adicionados.');

    // Initial load
    await fetchFollowUpConfig();
    console.log('followUp.js: Configurações iniciais de follow-up carregadas.');

    console.log('followUp.js: Página de Follow-up carregada completamente.');
}

async function fetchFollowUpConfig() {
    console.log('followUp.js: fetchFollowUpConfig - Buscando configuração de follow-up...');
    const rulesContainer = document.getElementById('follow-up-rules-container');
    rulesContainer.innerHTML = `<div class="spinner-container"><div class="loading-spinner"></div></div>`;
    console.log('followUp.js: fetchFollowUpConfig - Spinner de loading exibido.');

    try {
        // Primeiro carrega os funis disponíveis
        console.log('followUp.js: fetchFollowUpConfig - Carregando funis disponíveis...');
        const funnelsResponse = await getFunnelsList();
        availableFunnels = funnelsResponse.funnels || [];
        console.log('followUp.js: fetchFollowUpConfig - Funis carregados:', JSON.stringify(availableFunnels));

        // Carrega os estágios do fluxo de vendas padrão (fallback)
        console.log('followUp.js: fetchFollowUpConfig - Carregando estágios do fluxo de vendas...');
        const salesFlowConfig = await getSalesFlowConfig();
        availableStages = salesFlowConfig.stages || [];
        funnelStagesCache['default'] = availableStages;
        console.log('followUp.js: fetchFollowUpConfig - Estágios padrão carregados:', JSON.stringify(availableStages));

        // Depois carrega as regras de follow-up
        console.log('followUp.js: fetchFollowUpConfig - Carregando regras de follow-up...');
        const config = await getFollowUpConfig();
        followUpRules = config.rules || []; // Garante que followUpRules seja um array
        console.log('followUp.js: fetchFollowUpConfig - Regras de follow-up carregadas:', JSON.stringify(followUpRules));
        renderFollowUpRules();
        console.log('followUp.js: fetchFollowUpConfig - Configuração de follow-up carregada e renderizada.');
    } catch (error) {
        console.error('followUp.js: fetchFollowUpConfig - Erro ao buscar configuração de follow-up:', error);
        rulesContainer.innerHTML = `<div class="error-message">Erro ao carregar regras de follow-up. Tente recarregar a página.</div>`;
    }
}

async function getStagesForFunnel(funnelId) {
    // Se não há funil específico, usa os estágios padrão
    if (!funnelId) {
        return availableStages;
    }

    // Verificar cache
    if (funnelStagesCache[funnelId]) {
        return funnelStagesCache[funnelId];
    }

    try {
        console.log(`followUp.js: getStagesForFunnel - Carregando estágios do funil ${funnelId}...`);
        const funnel = await getFunnel(funnelId);
        const stages = funnel.stages || [];
        funnelStagesCache[funnelId] = stages;
        console.log(`followUp.js: getStagesForFunnel - Estágios do funil ${funnelId} carregados:`, stages.length);
        return stages;
    } catch (error) {
        console.error(`followUp.js: getStagesForFunnel - Erro ao carregar estágios do funil ${funnelId}:`, error);
        return availableStages; // Fallback para estágios padrão
    }
}

function renderFollowUpRules() {
    console.log('followUp.js: renderFollowUpRules - Renderizando regras de follow-up...');
    const rulesContainer = document.getElementById('follow-up-rules-container');
    rulesContainer.innerHTML = ''; // Limpa conteúdo existente
    console.log('followUp.js: renderFollowUpRules - Container de regras limpo.');

    if (!followUpRules || followUpRules.length === 0) {
        rulesContainer.innerHTML = `<p class="text-center">Nenhuma regra de follow-up configurada. Adicione uma nova regra.</p>`;
        console.log('followUp.js: renderFollowUpRules - Nenhuma regra para renderizar.');
        return;
    }

    followUpRules.forEach((rule, index) => {
        console.log(`followUp.js: renderFollowUpRules - Renderizando regra ${index + 1}:`, JSON.stringify(rule));

        // Cria as opções do select de funil
        const funnelOptions = [
            createElement('option', {
                value: '',
                selected: !rule.funnel_id
            }, '🌐 Todos os Funis')
        ];
        availableFunnels.forEach(funnel => {
            funnelOptions.push(
                createElement('option', {
                    value: funnel.funnel_id,
                    selected: rule.funnel_id === funnel.funnel_id
                }, `${funnel.is_default ? '⭐ ' : ''}${funnel.name}`)
            );
        });

        // Determinar estágios a usar baseado no funil da regra
        const stagesToUse = rule.funnel_id && funnelStagesCache[rule.funnel_id]
            ? funnelStagesCache[rule.funnel_id]
            : availableStages;

        // Cria as opções do select dinamicamente baseado nos estágios configurados
        const stageOptions = [];
        if (stagesToUse.length > 0) {
            stagesToUse.forEach(stage => {
                stageOptions.push(
                    createElement('option', {
                        value: stage.stage_number.toString(),
                        selected: rule.stage === stage.stage_number
                    }, `Estágio ${stage.stage_number}: ${stage.objective || 'Sem descrição'}`)
                );
            });
        } else {
            // Fallback para estágios padrões se não houver configuração
            for (let i = 1; i <= 6; i++) {
                stageOptions.push(
                    createElement('option', {
                        value: i.toString(),
                        selected: rule.stage === i
                    }, getStageName(i))
                );
            }
        }
        console.log(`followUp.js: renderFollowUpRules - Opções de estágio para regra ${index + 1} criadas.`);

        const ruleCard = createElement('div', { className: 'card follow-up-rule' }, [
            createElement('div', { className: 'card-header' }, [
                createElement('h3', { className: 'card-title' }, `Regra ${index + 1}`),
                createElement('div', { className: 'card-actions' }, [
                    createElement('button', {
                        type: 'button',
                        className: `btn ${rule.enabled ? 'btn-success' : 'btn-secondary'} btn-toggle-rule`,
                        title: rule.enabled ? 'Desativar Regra' : 'Ativar Regra',
                        dataset: { index: index }
                    }, [
                        createElement('i', {
                            'data-feather': rule.enabled ? 'check-circle' : 'circle'
                        }),
                        ` ${rule.enabled ? 'Ativa' : 'Inativa'}`
                    ]),
                    createElement('button', {
                        type: 'button',
                        className: 'btn btn-icon btn-danger btn-delete-follow-up',
                        title: 'Remover Regra',
                        dataset: { index: index }
                    }, [createElement('i', { 'data-feather': 'trash' })])
                ])
            ]),
            createElement('div', { className: 'card-body' }, [
                createElement('div', { className: 'form-group' }, [
                    createElement('label', { htmlFor: `rule-${index}-funnel`, className: 'label' }, [
                        createElement('i', { 'data-feather': 'git-branch', style: 'width: 14px; height: 14px; margin-right: 4px;' }),
                        ' Funil de Vendas:'
                    ]),
                    createElement('select', {
                        id: `rule-${index}-funnel`,
                        className: 'select',
                        dataset: { index: index, field: 'funnel_id' }
                    }, funnelOptions)
                ]),
                createElement('div', { className: 'form-group' }, [
                    createElement('label', { htmlFor: `rule-${index}-stage`, className: 'label' }, 'Estágio do Prospect:'),
                    createElement('select', {
                        id: `rule-${index}-stage`,
                        className: 'select',
                        dataset: { index: index, field: 'stage' },
                        required: true
                    }, stageOptions)
                ]),
                createElement('div', { className: 'form-group' }, [ // Campo Atraso
                    createElement('label', { htmlFor: `rule-${index}-delay-value`, className: 'label' }, 'Atraso após última interação:'),
                    createElement('input', {
                        type: 'number',
                        id: `rule-${index}-delay-value`,
                        className: 'input standard-width',
                        value: rule.delay_value,
                        min: 1,
                        required: true,
                        dataset: { index: index, field: 'delay_value' }
                    })
                ]),
                createElement('div', { className: 'form-group' }, [ // Campo Unidade
                    createElement('label', { htmlFor: `rule-${index}-delay-unit`, className: 'label' }, 'Unidade:'),
                    createElement('select', {
                        id: `rule-${index}-delay-unit`,
                        className: 'select standard-width',
                        dataset: { index: index, field: 'delay_unit' },
                        required: true
                    }, [
                        createElement('option', { value: 'days', selected: rule.delay_unit === 'days' }, 'Dias'),
                        createElement('option', { value: 'minutes', selected: rule.delay_unit === 'minutes' }, 'Minutos')
                    ])
                ]),
                createElement('div', { className: 'time-fields-container' }, [
                    createElement('div', { className: 'form-group form-group-time' }, [
                        createElement('label', { htmlFor: `rule-${index}-start-time`, className: 'label' }, 'Horário de Início:'),
                        createElement('input', {
                            type: 'time',
                            id: `rule-${index}-start-time`,
                            className: 'input config-time-input',
                            value: rule.start_time,
                            required: true,
                            dataset: { index: index, field: 'start_time' }
                        })
                    ]),
                    createElement('div', { className: 'form-group form-group-time' }, [
                        createElement('label', { htmlFor: `rule-${index}-end-time`, className: 'label' }, 'Horário de Fim:'),
                        createElement('input', {
                            type: 'time',
                            id: `rule-${index}-end-time`,
                            className: 'input config-time-input',
                            value: rule.end_time,
                            required: true,
                            dataset: { index: index, field: 'end_time' }
                        })
                    ])
                ]),
                createElement('div', { className: 'form-group' }, [
                    createElement('label', { htmlFor: `rule-${index}-message`, className: 'label' }, 'Mensagem de Follow-up:'),
                    createElement('textarea', {
                        id: `rule-${index}-message`,
                        className: 'textarea',
                        rows: 4,
                        placeholder: 'Digite a mensagem de follow-up...',
                        required: true,
                        dataset: { index: index, field: 'message' }
                    }, rule.message || '')
                ])
            ])
        ]);
        rulesContainer.appendChild(ruleCard);
        console.log(`followUp.js: renderFollowUpRules - Card da regra ${index + 1} adicionado ao container.`);
    });

    // Adicionar listeners para campos de input e select
    rulesContainer.querySelectorAll('input, select, textarea').forEach(input => {
        input.addEventListener('change', handleRuleInputChange);
        input.addEventListener('input', handleRuleInputChange); // Para inputs de texto/número
    });
    rulesContainer.querySelectorAll('.btn-delete-follow-up').forEach(button => {
        button.addEventListener('click', handleDeleteFollowUpRule);
    });
    rulesContainer.querySelectorAll('.btn-toggle-rule').forEach(button => {
        button.addEventListener('click', handleToggleRule);
    });
    console.log('followUp.js: renderFollowUpRules - Event listeners para inputs e botões das regras adicionados.');
    
    // Re-initialize Feather icons after rendering new content
    if (typeof feather !== 'undefined') {
        feather.replace();
        console.log('followUp.js: renderFollowUpRules - Feather icons re-renderizados.');
    }
    
    console.log('followUp.js: renderFollowUpRules - Regras de follow-up renderizadas completamente.');
}

async function handleRuleInputChange(event) {
    const { index, field } = event.target.dataset;
    const ruleIndex = parseInt(index);
    let value;

    if (event.target.type === 'checkbox') {
        value = event.target.checked;
    } else if (event.target.type === 'number') {
        value = parseInt(event.target.value);
    } else {
        value = event.target.value;
    }

    // Ensure delay_value is always an integer
    if (field === 'delay_value') {
        value = parseInt(value);
        if (isNaN(value)) {
            value = 1; // Default to 1 if not a valid number
        }
    }

    // FIX: Ensure stage is always an integer
    if (field === 'stage') {
        value = parseInt(value, 10);
    }

    // Tratar funnel_id: se vazio, deve ser null
    if (field === 'funnel_id') {
        value = value === '' ? null : value;

        // Atualizar os estágios disponíveis para este funil
        if (value) {
            const stages = await getStagesForFunnel(value);
            // Atualizar o select de estágios desta regra
            const stageSelect = document.getElementById(`rule-${ruleIndex}-stage`);
            if (stageSelect && stages.length > 0) {
                stageSelect.innerHTML = '';
                stages.forEach(stage => {
                    const option = document.createElement('option');
                    option.value = stage.stage_number.toString();
                    option.textContent = `Estágio ${stage.stage_number}: ${stage.objective || 'Sem descrição'}`;
                    stageSelect.appendChild(option);
                });
                // Resetar estágio para o primeiro disponível se o atual não existe no novo funil
                const currentStage = followUpRules[ruleIndex].stage;
                const stageExists = stages.some(s => s.stage_number === currentStage);
                if (!stageExists && stages.length > 0) {
                    followUpRules[ruleIndex].stage = stages[0].stage_number;
                    stageSelect.value = stages[0].stage_number.toString();
                }
            }
        } else {
            // Voltar para estágios padrão
            const stageSelect = document.getElementById(`rule-${ruleIndex}-stage`);
            if (stageSelect && availableStages.length > 0) {
                stageSelect.innerHTML = '';
                availableStages.forEach(stage => {
                    const option = document.createElement('option');
                    option.value = stage.stage_number.toString();
                    option.textContent = `Estágio ${stage.stage_number}: ${stage.objective || 'Sem descrição'}`;
                    stageSelect.appendChild(option);
                });
            }
        }
    }

    followUpRules[ruleIndex][field] = value;
    console.log(`followUp.js: handleRuleInputChange - Regra ${ruleIndex}, campo '${field}' atualizado para:`, value);
}

function handleToggleRule(event) {
    const index = parseInt(event.currentTarget.dataset.index);
    console.log(`followUp.js: handleToggleRule - Toggling regra ${index}...`);
    
    followUpRules[index].enabled = !followUpRules[index].enabled;
    console.log(`followUp.js: handleToggleRule - Regra ${index} agora está ${followUpRules[index].enabled ? 'ativa' : 'inativa'}`);
    
    // Re-renderizar para atualizar a aparência do botão
    renderFollowUpRules();
    console.log(`followUp.js: handleToggleRule - Regras re-renderizadas após toggle.`);
}

function addFollowUpRule() {
    console.log('followUp.js: addFollowUpRule - Adicionando nova regra de follow-up...');
    const newRule = {
        stage: availableStages.length > 0 ? availableStages[0].stage_number : 1,
        delay_value: 1,
        delay_unit: 'days', // Default to 'days'
        start_time: '09:00',
        end_time: '18:00',
        message: 'Olá! Estou fazendo um follow-up sobre nosso contato anterior.',
        enabled: true,
        funnel_id: null // null = aplica a todos os funis
    };
    followUpRules.push(newRule);
    renderFollowUpRules();
    console.log('followUp.js: addFollowUpRule - Nova regra de follow-up adicionada e regras re-renderizadas.');
}

function handleDeleteFollowUpRule(event) {
    const indexToDelete = parseInt(event.currentTarget.dataset.index);
    console.log(`followUp.js: handleDeleteFollowUpRule - Removendo regra de follow-up no índice: ${indexToDelete}`);
    followUpRules.splice(indexToDelete, 1);
    renderFollowUpRules();
    console.log('followUp.js: handleDeleteFollowUpRule - Regra de follow-up removida e regras re-renderizadas.');
}

async function handleFollowUpSubmit(event) {
    event.preventDefault();
    console.log('followUp.js: handleFollowUpSubmit - Formulário de follow-up submetido.');
    const feedbackContainer = document.getElementById('follow-up-feedback');
    const submitBtn = event.currentTarget.querySelector('button[type="submit"]');
    setLoadingState(submitBtn, true);
    clearFeedback(feedbackContainer);
    console.log('followUp.js: handleFollowUpSubmit - Estado de loading do botão de submit ativado e feedback limpo.');

    // Validação básica antes de enviar
    for (const rule of followUpRules) {
        if (rule.delay_value < 1) {
            showFeedback(feedbackContainer, 'O valor de atraso deve ser no mínimo 1.', 'error');
            setLoadingState(submitBtn, false);
            console.warn('followUp.js: handleFollowUpSubmit - Validação falhou: Valor de atraso inválido.');
            return;
        }
        if (!['days', 'minutes'].includes(rule.delay_unit)) {
            showFeedback(feedbackContainer, 'A unidade de atraso deve ser "Dias" ou "Minutos".', 'error');
            setLoadingState(submitBtn, false);
            console.warn('followUp.js: handleFollowUpSubmit - Validação falhou: Unidade de atraso inválida.');
            return;
        }
        if (!isValidTimeFormat(rule.start_time) || !isValidTimeFormat(rule.end_time)) {
            showFeedback(feedbackContainer, 'Formato de horário inválido (HH:MM) em uma das regras.', 'error');
            setLoadingState(submitBtn, false);
            console.warn('followUp.js: handleFollowUpSubmit - Validação falhou: Formato de horário inválido.');
            return;
        }
        if (rule.message.trim() === '') {
            showFeedback(feedbackContainer, 'A mensagem de follow-up não pode estar vazia.', 'error');
            setLoadingState(submitBtn, false);
            console.warn('followUp.js: handleFollowUpSubmit - Validação falhou: Mensagem de follow-up vazia.');
            return;
        }
    }
    console.log('followUp.js: handleFollowUpSubmit - Validações básicas passaram.');

    try {
        console.log('followUp.js: handleFollowUpSubmit - Enviando configuração de follow-up para API:', JSON.stringify({ rules: followUpRules }));
        const response = await setFollowUpConfig({ rules: followUpRules });
        console.log('followUp.js: handleFollowUpSubmit - Resposta da API:', response);
        showFeedback(feedbackContainer, response.message || 'Regras de follow-up salvas com sucesso!', 'success');
        // Re-fetch para garantir que o estado local esteja sincronizado com o que o backend salvou
        await fetchFollowUpConfig(); 
        console.log('followUp.js: handleFollowUpSubmit - Regras de follow-up salvas e re-carregadas com sucesso.');
    } catch (error) {
        console.error('followUp.js: handleFollowUpSubmit - Erro ao salvar regras de follow-up:', error);
        showFeedback(feedbackContainer, error.message || 'Erro ao salvar regras de follow-up.', 'error');
    } finally {
        setLoadingState(submitBtn, false);
        console.log('followUp.js: handleFollowUpSubmit - Estado de loading do botão de submit removido.');
    }
}
