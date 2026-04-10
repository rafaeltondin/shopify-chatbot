// static/js/pages/insufficientContextConfig.js
import { getInsufficientContextNotificationConfig, setInsufficientContextNotificationConfig } from '../api.js';
import { showFeedback, clearFeedback, setLoadingState } from '../utils.js';

export async function loadInsufficientContextConfigPage(container) {
    console.log('insufficientContextConfig.js: Carregando página...');

    container.innerHTML = `
        <header class="page-header">
            <h1 class="page-title"><i data-feather="alert-triangle" class="feather-title"></i> Notificação de Contexto Insuficiente</h1>
            <p class="page-description">Configure alertas quando o agente de IA não tiver informações suficientes para responder.</p>
        </header>

        <!-- Info Card -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="info" class="feather-title-sm"></i> Como Funciona</h3>
            </div>
            <div class="card-body">
                <div class="alert alert-info mb-0">
                    <i class="alert-icon" data-feather="help-circle"></i>
                    <div class="alert-content">
                        <div class="alert-title">O que é "Contexto Insuficiente"?</div>
                        <div class="alert-description">
                            Quando um cliente faz uma pergunta e o agente de IA não encontra informações suficientes
                            no contexto do produto/serviço para responder adequadamente, você pode ser notificado
                            para intervir manualmente.
                        </div>
                    </div>
                </div>
                <div class="flow-steps">
                    <div class="flow-step">
                        <i data-feather="message-circle"></i>
                        <span>Cliente pergunta</span>
                    </div>
                    <div class="flow-arrow"><i data-feather="chevron-right"></i></div>
                    <div class="flow-step">
                        <i data-feather="search"></i>
                        <span>IA busca contexto</span>
                    </div>
                    <div class="flow-arrow"><i data-feather="chevron-right"></i></div>
                    <div class="flow-step">
                        <i data-feather="alert-circle"></i>
                        <span>Não encontra</span>
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
                <form id="insufficient-context-form" class="form">
                    <!-- Toggle -->
                    <div class="form-group">
                        <div class="form-check form-switch">
                            <input class="form-check-input" type="checkbox" id="insufficient-context-enabled">
                            <label class="form-check-label" for="insufficient-context-enabled">
                                <strong>Ativar Notificações de Contexto Insuficiente</strong>
                            </label>
                        </div>
                        <small class="form-text text-muted">Receba alertas quando o agente não souber responder.</small>
                    </div>

                    <hr class="form-divider">

                    <div id="config-fields">
                        <!-- Número WhatsApp -->
                        <div class="form-group">
                            <label for="notification-whatsapp-number" class="label">Número WhatsApp para Notificação:</label>
                            <input type="tel" id="notification-whatsapp-number" class="input" placeholder="Ex: 5511999999999">
                            <p class="form-text">Número que receberá as notificações. Use formato: código do país + DDD + número (apenas números).</p>
                        </div>

                        <!-- Mensagem de Fallback -->
                        <div class="form-group">
                            <label for="customer-fallback-message" class="label">Mensagem de Fallback para o Cliente:</label>
                            <textarea id="customer-fallback-message" class="textarea" rows="3" placeholder="Mensagem enviada ao cliente quando o agente não souber responder"></textarea>
                            <p class="form-text">Esta mensagem será enviada ao cliente quando o agente detectar que não tem contexto suficiente.</p>
                        </div>

                        <!-- Suprimir Resposta -->
                        <div class="form-group">
                            <div class="form-check form-switch">
                                <input class="form-check-input" type="checkbox" id="suppress-response">
                                <label class="form-check-label" for="suppress-response">
                                    Suprimir resposta ao cliente
                                </label>
                            </div>
                            <small class="form-text text-muted">Se marcado, o agente não envia nenhuma resposta ao cliente (apenas notifica você).</small>
                        </div>

                        <!-- Template da Notificação -->
                        <div class="form-group">
                            <label for="notification-message-template" class="label">Template da Mensagem de Notificação:</label>
                            <textarea id="notification-message-template" class="textarea" rows="8" placeholder="Template da mensagem enviada ao número de notificação"></textarea>
                            <p class="form-text">
                                Variáveis disponíveis: <code>{customer_phone}</code>, <code>{customer_name}</code>, <code>{customer_message}</code>, <code>{timestamp}</code>, <code>{detection_reason}</code>
                            </p>
                            <div class="variable-buttons" style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem;">
                                <button type="button" class="btn btn-outline btn-xs variable-btn" data-variable="{customer_phone}">{customer_phone}</button>
                                <button type="button" class="btn btn-outline btn-xs variable-btn" data-variable="{customer_name}">{customer_name}</button>
                                <button type="button" class="btn btn-outline btn-xs variable-btn" data-variable="{customer_message}">{customer_message}</button>
                                <button type="button" class="btn btn-outline btn-xs variable-btn" data-variable="{timestamp}">{timestamp}</button>
                                <button type="button" class="btn btn-outline btn-xs variable-btn" data-variable="{detection_reason}">{detection_reason}</button>
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
            @media (max-width: 768px) {
                .flow-steps {
                    flex-direction: column;
                    align-items: stretch;
                }
                .flow-arrow {
                    transform: rotate(90deg);
                    align-self: center;
                }
            }
        </style>
    `;

    // Event Listeners
    setupEventListeners();

    // Carregar configuração
    await fetchConfig();

    // Initialize Feather icons
    if (typeof feather !== 'undefined') {
        feather.replace();
    }

    console.log('insufficientContextConfig.js: Página carregada.');
}

function setupEventListeners() {
    // Toggle enable/disable
    document.getElementById('insufficient-context-enabled').addEventListener('change', handleToggle);

    // Form submit
    document.getElementById('insufficient-context-form').addEventListener('submit', handleFormSubmit);

    // Variable buttons
    document.querySelectorAll('.variable-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const variable = btn.dataset.variable;
            const textarea = document.getElementById('notification-message-template');
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
    const enabled = document.getElementById('insufficient-context-enabled').checked;
    const fieldsContainer = document.getElementById('config-fields');
    fieldsContainer.style.opacity = enabled ? '1' : '0.5';
    fieldsContainer.style.pointerEvents = enabled ? 'auto' : 'none';
}

async function fetchConfig() {
    console.log('insufficientContextConfig.js: Buscando configuração...');
    const feedbackContainer = document.getElementById('form-feedback');

    try {
        const config = await getInsufficientContextNotificationConfig();

        document.getElementById('insufficient-context-enabled').checked = config.enabled !== false;
        document.getElementById('notification-whatsapp-number').value = config.notification_whatsapp_number || '';
        document.getElementById('customer-fallback-message').value =
            config.customer_fallback_message || 'Entendi sua dúvida. Vou verificar essa informação e retorno em breve!';
        document.getElementById('suppress-response').checked = config.suppress_response_to_customer === true;
        document.getElementById('notification-message-template').value =
            config.notification_message_template ||
            "⚠️ *Contexto Insuficiente Detectado*\n\n📱 *Cliente:* {customer_phone}\n👤 *Nome:* {customer_name}\n💬 *Mensagem:* {customer_message}\n\n❓ O agente de IA não encontrou informações suficientes no contexto para responder esta pergunta.\n\n⏰ *Horário:* {timestamp}";

        handleToggle();
        console.log('insufficientContextConfig.js: Configuração carregada.');
    } catch (error) {
        console.error('insufficientContextConfig.js: Erro ao buscar configuração:', error);
        showFeedback(feedbackContainer, error.message || 'Erro ao carregar configuração.', 'error');
    }
}

async function handleFormSubmit(event) {
    event.preventDefault();
    const feedbackContainer = document.getElementById('form-feedback');
    const submitBtn = event.currentTarget.querySelector('button[type="submit"]');

    setLoadingState(submitBtn, true);
    clearFeedback(feedbackContainer);

    const enabled = document.getElementById('insufficient-context-enabled').checked;
    const notificationNumber = document.getElementById('notification-whatsapp-number').value.trim();
    const customerFallbackMessage = document.getElementById('customer-fallback-message').value.trim();
    const suppressResponse = document.getElementById('suppress-response').checked;
    const notificationTemplate = document.getElementById('notification-message-template').value.trim();

    // Validação
    if (enabled && !notificationNumber) {
        showFeedback(feedbackContainer, 'Número de WhatsApp para notificação é obrigatório quando a funcionalidade está habilitada.', 'error');
        setLoadingState(submitBtn, false);
        return;
    }

    const cleanedNumber = notificationNumber.replace(/\D/g, '');
    if (enabled && cleanedNumber && (cleanedNumber.length < 10 || cleanedNumber.length > 15)) {
        showFeedback(feedbackContainer, 'Número de WhatsApp inválido. Deve ter entre 10 e 15 dígitos.', 'error');
        setLoadingState(submitBtn, false);
        return;
    }

    const configData = {
        enabled: enabled,
        notification_whatsapp_number: cleanedNumber || null,
        customer_fallback_message: customerFallbackMessage || 'Entendi sua dúvida. Vou verificar essa informação e retorno em breve!',
        suppress_response_to_customer: suppressResponse,
        notification_message_template: notificationTemplate || "⚠️ *Contexto Insuficiente Detectado*\n\n📱 *Cliente:* {customer_phone}\n👤 *Nome:* {customer_name}\n💬 *Mensagem:* {customer_message}\n\n❓ O agente de IA não encontrou informações suficientes no contexto para responder esta pergunta.\n\n⏰ *Horário:* {timestamp}"
    };

    try {
        const response = await setInsufficientContextNotificationConfig(configData);
        showFeedback(feedbackContainer, response.message || 'Configuração salva com sucesso!', 'success');
        console.log('insufficientContextConfig.js: Configuração salva com sucesso.');
    } catch (error) {
        console.error('insufficientContextConfig.js: Erro ao salvar configuração:', error);
        showFeedback(feedbackContainer, error.message || 'Erro ao salvar configuração.', 'error');
    } finally {
        setLoadingState(submitBtn, false);
    }
}
