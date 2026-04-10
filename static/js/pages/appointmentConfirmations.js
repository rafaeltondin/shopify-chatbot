// static/js/pages/appointmentConfirmations.js
import {
    getConfirmationConfig, saveConfirmationConfig,
    getSchedulerStatus, pauseScheduler, resumeScheduler, triggerManualCheck,
    getUpcomingAppointments, getAppointmentsStats, sendManualConfirmation
} from '../api.js';
import { showFeedback, clearFeedback, setLoadingState } from '../utils.js';

const DEFAULT_MESSAGE_24H = `Olá {nome}! 👋

Passando para lembrar do seu agendamento *amanhã*:

📅 *Data:* {data}
🕐 *Horário:* {horario}
{link_video}

Por favor, confirme sua presença respondendo:
✅ *SIM* - Confirmo minha presença
❌ *NÃO* - Preciso cancelar/reagendar

Aguardamos você! 🙂`;

const DEFAULT_MESSAGE_1H = `Olá {nome}! ⏰

Seu agendamento é *daqui a 1 hora*:

🕐 *Horário:* {horario}
{link_video}

Estamos te esperando! 🙂`;

export async function loadAppointmentConfirmationsPage(container) {
    console.log('appointmentConfirmations.js: Carregando página de Confirmações de Agendamento...');

    container.innerHTML = `
        <header class="page-header">
            <h1 class="page-title"><i data-feather="bell" class="feather-title"></i> Confirmações de Agendamento</h1>
            <p class="page-description">Configure o envio automático de confirmações 24h e 1h antes dos agendamentos.</p>
        </header>

        <!-- Estatísticas -->
        <div class="stats-grid stats-grid-4">
            <div class="stat-card">
                <div class="stat-icon"><i data-feather="calendar"></i></div>
                <div class="stat-content">
                    <span class="stat-value" id="stat-today">-</span>
                    <span class="stat-label">Agendamentos Hoje</span>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i data-feather="clock"></i></div>
                <div class="stat-content">
                    <span class="stat-value" id="stat-week">-</span>
                    <span class="stat-label">Esta Semana</span>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i data-feather="send"></i></div>
                <div class="stat-content">
                    <span class="stat-value" id="stat-confirmations-sent">-</span>
                    <span class="stat-label">Confirmações Enviadas</span>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i data-feather="check-circle"></i></div>
                <div class="stat-content">
                    <span class="stat-value" id="stat-confirmation-rate">-</span>
                    <span class="stat-label">Taxa de Confirmação</span>
                </div>
            </div>
        </div>

        <!-- Status do Scheduler -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="activity" class="feather-title-sm"></i> Status do Sistema</h3>
            </div>
            <div class="card-body">
                <div class="scheduler-status-row">
                    <div class="scheduler-status-info">
                        <span id="scheduler-status-badge" class="badge badge-success">Ativo</span>
                        <span id="scheduler-status-text">Sistema de confirmações funcionando normalmente</span>
                    </div>
                    <div class="btn-actions">
                        <button id="btn-pause-scheduler" class="btn btn-warning btn-sm">
                            <i data-feather="pause"></i> Pausar
                        </button>
                        <button id="btn-resume-scheduler" class="btn btn-success btn-sm" style="display: none;">
                            <i data-feather="play"></i> Retomar
                        </button>
                        <button id="btn-trigger-check" class="btn btn-outline btn-sm">
                            <i data-feather="refresh-cw"></i> Verificar Agora
                        </button>
                    </div>
                </div>
                <div id="scheduler-feedback" class="feedback-message" style="margin-top: 10px;"></div>
            </div>
        </div>

        <!-- Configurações -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="settings" class="feather-title-sm"></i> Configurações de Confirmação</h3>
            </div>
            <div class="card-body">
                <form id="confirmation-config-form" class="form">
                    <!-- Toggle Principal -->
                    <div class="form-group">
                        <div class="form-check form-switch">
                            <input class="form-check-input" type="checkbox" id="config-enabled" checked>
                            <label class="form-check-label" for="config-enabled">
                                <strong>Confirmações Automáticas Habilitadas</strong>
                            </label>
                        </div>
                        <small class="form-text text-muted">Ative para enviar confirmações automáticas de agendamento.</small>
                    </div>

                    <hr class="form-divider">

                    <!-- Confirmação 24h -->
                    <div class="form-section">
                        <h4 class="form-section-title"><i data-feather="clock" class="feather-sm"></i> Confirmação 24 horas antes</h4>

                        <div class="form-group">
                            <div class="form-check form-switch">
                                <input class="form-check-input" type="checkbox" id="config-send-24h" checked>
                                <label class="form-check-label" for="config-send-24h">
                                    Enviar confirmação 24h antes do agendamento
                                </label>
                            </div>
                        </div>

                        <div class="form-group">
                            <label class="label" for="config-message-24h">Mensagem (24h antes):</label>
                            <textarea id="config-message-24h" class="input textarea" rows="10" placeholder="Digite a mensagem de confirmação...">${DEFAULT_MESSAGE_24H}</textarea>
                            <small class="form-text text-muted">
                                Variáveis disponíveis: <code>{nome}</code>, <code>{data}</code>, <code>{horario}</code>, <code>{link_video}</code>
                            </small>
                        </div>
                    </div>

                    <hr class="form-divider">

                    <!-- Confirmação 1h -->
                    <div class="form-section">
                        <h4 class="form-section-title"><i data-feather="alert-circle" class="feather-sm"></i> Confirmação 1 hora antes</h4>

                        <div class="form-group">
                            <div class="form-check form-switch">
                                <input class="form-check-input" type="checkbox" id="config-send-1h" checked>
                                <label class="form-check-label" for="config-send-1h">
                                    Enviar confirmação 1h antes do agendamento
                                </label>
                            </div>
                        </div>

                        <div class="form-group">
                            <label class="label" for="config-message-1h">Mensagem (1h antes):</label>
                            <textarea id="config-message-1h" class="input textarea" rows="8" placeholder="Digite a mensagem de confirmação...">${DEFAULT_MESSAGE_1H}</textarea>
                            <small class="form-text text-muted">
                                Variáveis disponíveis: <code>{nome}</code>, <code>{data}</code>, <code>{horario}</code>, <code>{link_video}</code>
                            </small>
                        </div>
                    </div>

                    <div id="config-feedback" class="feedback-message"></div>

                    <div class="form-actions">
                        <button type="submit" class="btn btn-primary">
                            <i data-feather="save"></i> Salvar Configurações
                        </button>
                        <button type="button" id="btn-reset-defaults" class="btn btn-outline">
                            <i data-feather="rotate-ccw"></i> Restaurar Padrões
                        </button>
                    </div>
                </form>
            </div>
        </div>

        <!-- Próximos Agendamentos -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="list" class="feather-title-sm"></i> Próximos Agendamentos</h3>
                <button id="btn-refresh-appointments" class="btn btn-outline btn-sm">
                    <i data-feather="refresh-cw"></i> Atualizar
                </button>
            </div>
            <div class="card-body">
                <div id="appointments-loading" class="loading-indicator">
                    <div class="spinner"></div>
                    <span>Carregando agendamentos...</span>
                </div>
                <div id="appointments-empty" class="empty-state" style="display: none;">
                    <i data-feather="calendar" class="empty-icon"></i>
                    <p>Nenhum agendamento encontrado para os próximos 7 dias.</p>
                </div>
                <div id="appointments-table-container" style="display: none;">
                    <table class="table">
                        <thead>
                            <tr>
                                <th>Paciente</th>
                                <th>Data/Hora</th>
                                <th>Confirmação 24h</th>
                                <th>Confirmação 1h</th>
                                <th>Status</th>
                                <th>Ações</th>
                            </tr>
                        </thead>
                        <tbody id="appointments-tbody">
                            <!-- Linhas serão inseridas aqui -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;

    // Event Listeners
    document.getElementById('confirmation-config-form').addEventListener('submit', handleSaveConfig);
    document.getElementById('btn-reset-defaults').addEventListener('click', handleResetDefaults);
    document.getElementById('btn-pause-scheduler').addEventListener('click', handlePauseScheduler);
    document.getElementById('btn-resume-scheduler').addEventListener('click', handleResumeScheduler);
    document.getElementById('btn-trigger-check').addEventListener('click', handleTriggerCheck);
    document.getElementById('btn-refresh-appointments').addEventListener('click', loadUpcomingAppointments);

    // Carregar dados iniciais
    await Promise.all([
        loadSchedulerStatus(),
        loadConfirmationConfig(),
        loadStats(),
        loadUpcomingAppointments()
    ]);

    feather.replace();
    console.log('appointmentConfirmations.js: Página carregada com sucesso.');
}

async function loadSchedulerStatus() {
    try {
        const status = await getSchedulerStatus();
        updateSchedulerStatusUI(status);
    } catch (error) {
        console.error('Erro ao carregar status do scheduler:', error);
    }
}

function updateSchedulerStatusUI(status) {
    const badge = document.getElementById('scheduler-status-badge');
    const text = document.getElementById('scheduler-status-text');
    const pauseBtn = document.getElementById('btn-pause-scheduler');
    const resumeBtn = document.getElementById('btn-resume-scheduler');

    if (!status.running) {
        badge.className = 'badge badge-error';
        badge.textContent = 'Parado';
        text.textContent = 'Sistema de confirmações não está em execução';
        pauseBtn.style.display = 'none';
        resumeBtn.style.display = 'none';
    } else if (status.paused) {
        badge.className = 'badge badge-warning';
        badge.textContent = 'Pausado';
        text.textContent = 'Sistema de confirmações está pausado';
        pauseBtn.style.display = 'none';
        resumeBtn.style.display = '';
    } else {
        badge.className = 'badge badge-success';
        badge.textContent = 'Ativo';
        text.textContent = `Sistema funcionando (verificação a cada ${status.check_interval_seconds}s)`;
        pauseBtn.style.display = '';
        resumeBtn.style.display = 'none';
    }
    feather.replace();
}

async function loadConfirmationConfig() {
    try {
        const config = await getConfirmationConfig();

        document.getElementById('config-enabled').checked = config.enabled !== false;
        document.getElementById('config-send-24h').checked = config.send_24h_before !== false;
        document.getElementById('config-send-1h').checked = config.send_1h_before !== false;
        document.getElementById('config-message-24h').value = config.message_24h || DEFAULT_MESSAGE_24H;
        document.getElementById('config-message-1h').value = config.message_1h || DEFAULT_MESSAGE_1H;

    } catch (error) {
        console.error('Erro ao carregar configurações:', error);
        showFeedback(document.getElementById('config-feedback'), 'Erro ao carregar configurações', 'error');
    }
}

async function loadStats() {
    try {
        const stats = await getAppointmentsStats();

        document.getElementById('stat-today').textContent = stats.today || 0;
        document.getElementById('stat-week').textContent = stats.this_week || 0;
        document.getElementById('stat-confirmations-sent').textContent =
            (stats.confirmations_24h_sent || 0) + (stats.confirmations_1h_sent || 0);
        document.getElementById('stat-confirmation-rate').textContent =
            `${stats.confirmation_rate || 0}%`;

    } catch (error) {
        console.error('Erro ao carregar estatísticas:', error);
    }
}

async function loadUpcomingAppointments() {
    const loadingEl = document.getElementById('appointments-loading');
    const emptyEl = document.getElementById('appointments-empty');
    const tableContainer = document.getElementById('appointments-table-container');
    const tbody = document.getElementById('appointments-tbody');

    loadingEl.style.display = 'flex';
    emptyEl.style.display = 'none';
    tableContainer.style.display = 'none';

    try {
        const result = await getUpcomingAppointments(7);
        const appointments = result.items || [];

        loadingEl.style.display = 'none';

        if (appointments.length === 0) {
            emptyEl.style.display = 'flex';
            return;
        }

        tableContainer.style.display = 'block';
        tbody.innerHTML = appointments.map(apt => createAppointmentRow(apt)).join('');

        // Event listeners para botões de ação
        tbody.querySelectorAll('.btn-send-confirmation').forEach(btn => {
            btn.addEventListener('click', handleSendManualConfirmation);
        });

        feather.replace();

    } catch (error) {
        console.error('Erro ao carregar agendamentos:', error);
        loadingEl.style.display = 'none';
        emptyEl.style.display = 'flex';
        emptyEl.querySelector('p').textContent = 'Erro ao carregar agendamentos.';
    }
}

function createAppointmentRow(appointment) {
    const date = new Date(appointment.appointment_datetime);
    // Formatação com timezone America/Sao_Paulo (GMT-3)
    const formattedDate = date.toLocaleDateString('pt-BR', {
        weekday: 'short',
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        timeZone: 'America/Sao_Paulo'
    });

    const statusBadges = {
        scheduled: '<span class="badge badge-primary">Agendado</span>',
        confirmed: '<span class="badge badge-success">Confirmado</span>',
        cancelled: '<span class="badge badge-error">Cancelado</span>',
        completed: '<span class="badge badge-secondary">Concluído</span>',
        no_show: '<span class="badge badge-warning">Faltou</span>'
    };

    const confirmation24h = appointment.confirmation_24h_sent
        ? '<span class="badge badge-success"><i data-feather="check" class="feather-xs"></i> Enviada</span>'
        : '<span class="badge badge-secondary">Pendente</span>';

    const confirmation1h = appointment.confirmation_1h_sent
        ? '<span class="badge badge-success"><i data-feather="check" class="feather-xs"></i> Enviada</span>'
        : '<span class="badge badge-secondary">Pendente</span>';

    return `
        <tr>
            <td>
                <div class="patient-info">
                    <strong>${appointment.prospect_name || 'Sem nome'}</strong>
                    <small class="text-muted">${appointment.prospect_jid}</small>
                </div>
            </td>
            <td>${formattedDate}</td>
            <td>${confirmation24h}</td>
            <td>${confirmation1h}</td>
            <td>${statusBadges[appointment.status] || appointment.status}</td>
            <td>
                <div class="btn-actions-inline">
                    ${!appointment.confirmation_24h_sent ? `
                        <button class="btn btn-outline btn-xs btn-send-confirmation"
                                data-id="${appointment.id}" data-type="24h" title="Enviar confirmação 24h">
                            <i data-feather="send"></i> 24h
                        </button>
                    ` : ''}
                    ${!appointment.confirmation_1h_sent ? `
                        <button class="btn btn-outline btn-xs btn-send-confirmation"
                                data-id="${appointment.id}" data-type="1h" title="Enviar confirmação 1h">
                            <i data-feather="send"></i> 1h
                        </button>
                    ` : ''}
                </div>
            </td>
        </tr>
    `;
}

async function handleSaveConfig(e) {
    e.preventDefault();
    const feedbackEl = document.getElementById('config-feedback');
    const submitBtn = e.target.querySelector('button[type="submit"]');

    clearFeedback(feedbackEl);
    setLoadingState(submitBtn, true, 'Salvando...');

    try {
        const config = {
            enabled: document.getElementById('config-enabled').checked,
            send_24h_before: document.getElementById('config-send-24h').checked,
            send_1h_before: document.getElementById('config-send-1h').checked,
            message_24h: document.getElementById('config-message-24h').value,
            message_1h: document.getElementById('config-message-1h').value
        };

        await saveConfirmationConfig(config);
        showFeedback(feedbackEl, 'Configurações salvas com sucesso!', 'success');

    } catch (error) {
        console.error('Erro ao salvar configurações:', error);
        showFeedback(feedbackEl, error.message || 'Erro ao salvar configurações', 'error');
    } finally {
        setLoadingState(submitBtn, false, 'Salvar Configurações');
        feather.replace();
    }
}

function handleResetDefaults() {
    if (!confirm('Restaurar mensagens para os valores padrão?')) return;

    document.getElementById('config-enabled').checked = true;
    document.getElementById('config-send-24h').checked = true;
    document.getElementById('config-send-1h').checked = true;
    document.getElementById('config-message-24h').value = DEFAULT_MESSAGE_24H;
    document.getElementById('config-message-1h').value = DEFAULT_MESSAGE_1H;

    showFeedback(document.getElementById('config-feedback'), 'Valores padrão restaurados. Clique em "Salvar" para aplicar.', 'info');
}

async function handlePauseScheduler() {
    const feedbackEl = document.getElementById('scheduler-feedback');
    const btn = document.getElementById('btn-pause-scheduler');

    setLoadingState(btn, true, 'Pausando...');
    clearFeedback(feedbackEl);

    try {
        await pauseScheduler();
        await loadSchedulerStatus();
        showFeedback(feedbackEl, 'Scheduler pausado com sucesso', 'success');
    } catch (error) {
        showFeedback(feedbackEl, error.message || 'Erro ao pausar scheduler', 'error');
    } finally {
        setLoadingState(btn, false, 'Pausar');
        feather.replace();
    }
}

async function handleResumeScheduler() {
    const feedbackEl = document.getElementById('scheduler-feedback');
    const btn = document.getElementById('btn-resume-scheduler');

    setLoadingState(btn, true, 'Retomando...');
    clearFeedback(feedbackEl);

    try {
        await resumeScheduler();
        await loadSchedulerStatus();
        showFeedback(feedbackEl, 'Scheduler retomado com sucesso', 'success');
    } catch (error) {
        showFeedback(feedbackEl, error.message || 'Erro ao retomar scheduler', 'error');
    } finally {
        setLoadingState(btn, false, 'Retomar');
        feather.replace();
    }
}

async function handleTriggerCheck() {
    const feedbackEl = document.getElementById('scheduler-feedback');
    const btn = document.getElementById('btn-trigger-check');

    setLoadingState(btn, true, 'Verificando...');
    clearFeedback(feedbackEl);

    try {
        await triggerManualCheck();
        await loadUpcomingAppointments();
        await loadStats();
        showFeedback(feedbackEl, 'Verificação manual concluída', 'success');
    } catch (error) {
        showFeedback(feedbackEl, error.message || 'Erro na verificação', 'error');
    } finally {
        setLoadingState(btn, false, 'Verificar Agora');
        feather.replace();
    }
}

async function handleSendManualConfirmation(e) {
    const btn = e.currentTarget;
    const appointmentId = parseInt(btn.dataset.id);
    const confirmationType = btn.dataset.type;

    if (!confirm(`Enviar confirmação ${confirmationType} manualmente?`)) return;

    setLoadingState(btn, true, '...');

    try {
        await sendManualConfirmation(appointmentId, confirmationType);
        await loadUpcomingAppointments();
        await loadStats();
    } catch (error) {
        console.error('Erro ao enviar confirmação manual:', error);
        alert(error.message || 'Erro ao enviar confirmação');
    } finally {
        setLoadingState(btn, false, confirmationType);
        feather.replace();
    }
}

console.log('appointmentConfirmations.js: Módulo carregado.');
