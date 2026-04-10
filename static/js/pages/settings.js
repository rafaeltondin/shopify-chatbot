import { loadProductContextPage } from './productContext.js';
import { loadWalletPage } from './wallet.js';
import { loadSalesFlowConfigPage } from './salesFlowConfig.js';
import { loadFollowUpPage } from './followUp.js';
import { loadSystemPromptPage } from './systemPrompt.js';
import { loadProspectingConfigPage } from './prospectingConfig.js';
import { loadAPIConfigPage } from './apiConfig.js';
import { loadAppointmentConfirmationsPage } from './appointmentConfirmations.js';
import { loadProfessionalsPage } from './professionals.js';
import { loadStageNotificationConfigPage } from './stageNotificationConfig.js';
import { loadInsufficientContextConfigPage } from './insufficientContextConfig.js';
import { replaceFeatherIcons } from '../utils.js';

const subPages = {
    'product-context': loadProductContextPage,
    'wallet': loadWalletPage,
    'sales-flow': loadSalesFlowConfigPage,
    'follow-up': loadFollowUpPage,
    'appointment-confirmations': loadAppointmentConfirmationsPage,
    'professionals': loadProfessionalsPage,
    'system-prompt': loadSystemPromptPage,
    'prospecting-config': loadProspectingConfigPage,
    'api-config': loadAPIConfigPage,
    'stage-notification': loadStageNotificationConfigPage,
    'insufficient-context': loadInsufficientContextConfigPage,
};

const settingsPage = {
    render: () => {
        return `
            <div class="settings-container animate-fade-in">
                <header class="page-header">
                    <h1 class="page-title">
                        <span class="icon-wrapper">
                            <i data-feather="settings"></i>
                        </span>
                        Configurações
                    </h1>
                    <p class="page-subtitle">Ajuste as configurações do sistema.</p>
                </header>

                <div class="settings-layout">
                    <aside class="settings-sidebar">
                        <nav class="settings-nav">
                            <h2 class="settings-nav-title">MY BUSINESS</h2>
                            <ul class="settings-nav-list">
                                <li><a href="#settings?page=product-context" class="settings-nav-link" data-page="product-context">Informações do Produto</a></li>
                                <li><a href="#settings?page=wallet" class="settings-nav-link" data-page="wallet">Carteira</a></li>
                            </ul>

                            <h2 class="settings-nav-title">BUSINESS SERVICES</h2>
                            <ul class="settings-nav-list">
                                <li><a href="#settings?page=professionals" class="settings-nav-link" data-page="professionals">Profissionais</a></li>
                                <li><a href="#settings?page=sales-flow" class="settings-nav-link" data-page="sales-flow">Editor do Funil</a></li>
                                <li><a href="#settings?page=follow-up" class="settings-nav-link" data-page="follow-up">Config. Follow-up</a></li>
                                <li><a href="#settings?page=stage-notification" class="settings-nav-link" data-page="stage-notification">Notificacoes de Etapa</a></li>
                                <li><a href="#settings?page=insufficient-context" class="settings-nav-link" data-page="insufficient-context">Notif. Contexto Insuficiente</a></li>
                                <li><a href="#settings?page=appointment-confirmations" class="settings-nav-link" data-page="appointment-confirmations">Confirmacoes de Agendamento</a></li>
                                <li><a href="#settings?page=system-prompt" class="settings-nav-link" data-page="system-prompt">Config. Agente de IA</a></li>
                            </ul>

                            <h2 class="settings-nav-title">OTHER SETTINGS</h2>
                            <ul class="settings-nav-list">
                                <li><a href="#settings?page=prospecting-config" class="settings-nav-link" data-page="prospecting-config">Config. Horários</a></li>
                                <li><a href="#settings?page=api-config" class="settings-nav-link" data-page="api-config">Config. API</a></li>
                            </ul>
                        </nav>
                    </aside>
                    <main class="settings-content">
                        <div id="settings-content-area">
                            <p>Selecione uma opção de configuração no menu à esquerda.</p>
                        </div>
                    </main>
                </div>
            </div>
        `;
    },
    after_render: async (container, params) => {
        const settingsContentArea = document.getElementById('settings-content-area');
        const navLinks = document.querySelectorAll('.settings-nav-link');

        const loadSubPage = async (page) => {
            const handler = subPages[page];
            if (handler) {
                settingsContentArea.innerHTML = '<div class="loading-spinner"></div>';
                await handler(settingsContentArea);
                replaceFeatherIcons();

                navLinks.forEach(link => {
                    link.classList.toggle('active', link.dataset.page === page);
                });
            }
        };

        navLinks.forEach(link => {
            link.addEventListener('click', (event) => {
                event.preventDefault();
                const page = event.currentTarget.dataset.page;
                history.pushState(null, '', `#settings?page=${page}`);
                loadSubPage(page);
            });
        });

        const initialPage = params.get('page');
        if (initialPage && subPages[initialPage]) {
            loadSubPage(initialPage);
        }
    }
};

export default settingsPage;
