// static/js/pages/professionals.js
import {
    getProfessionals, createProfessional, updateProfessional, deleteProfessional,
    getProfessionalById, getProfessionalsStats, getSpecialties, getRooms,
    getProfessionalServices, createService, getProfessionalAvailability,
    createScheduleBlock, getScheduleBlocks, deleteScheduleBlock,
    getProfessionalCalendarStatus, disconnectProfessionalCalendar
} from '../api.js';
import { showFeedback, clearFeedback, setLoadingState } from '../utils.js';

// Cores disponíveis para profissionais
const PROFESSIONAL_COLORS = [
    '#0D9488', '#0EA5E9', '#8B5CF6', '#EC4899',
    '#F59E0B', '#10B981', '#EF4444', '#6366F1'
];

// Disponibilidade padrão
const DEFAULT_AVAILABILITY = {
    monday: [{ start: '08:00', end: '12:00' }, { start: '14:00', end: '18:00' }],
    tuesday: [{ start: '08:00', end: '12:00' }, { start: '14:00', end: '18:00' }],
    wednesday: [{ start: '08:00', end: '12:00' }, { start: '14:00', end: '18:00' }],
    thursday: [{ start: '08:00', end: '12:00' }, { start: '14:00', end: '18:00' }],
    friday: [{ start: '08:00', end: '12:00' }, { start: '14:00', end: '18:00' }],
    saturday: [],
    sunday: []
};

const DAY_NAMES = {
    monday: 'Segunda-feira',
    tuesday: 'Terça-feira',
    wednesday: 'Quarta-feira',
    thursday: 'Quinta-feira',
    friday: 'Sexta-feira',
    saturday: 'Sábado',
    sunday: 'Domingo'
};

// Referência global ao container para uso nas funções
let pageContainer = null;

export async function loadProfessionalsPage(container) {
    pageContainer = container;
    console.log('professionals.js: Carregando página de Profissionais...');

    container.innerHTML = `
        <header class="page-header">
            <h1 class="page-title"><i data-feather="users" class="feather-title"></i> Profissionais</h1>
            <p class="page-description">Gerencie os profissionais da clínica e suas agendas.</p>
        </header>

        <!-- Estatísticas -->
        <div class="stats-grid stats-grid-4">
            <div class="stat-card">
                <div class="stat-icon"><i data-feather="users"></i></div>
                <div class="stat-content">
                    <span class="stat-value" id="stat-total">-</span>
                    <span class="stat-label">Total de Profissionais</span>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i data-feather="user-check"></i></div>
                <div class="stat-content">
                    <span class="stat-value" id="stat-active">-</span>
                    <span class="stat-label">Ativos</span>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i data-feather="briefcase"></i></div>
                <div class="stat-content">
                    <span class="stat-value" id="stat-specialties">-</span>
                    <span class="stat-label">Especialidades</span>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i data-feather="home"></i></div>
                <div class="stat-content">
                    <span class="stat-value" id="stat-rooms">-</span>
                    <span class="stat-label">Salas em Uso</span>
                </div>
            </div>
        </div>

        <!-- Ações e Filtros -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="filter" class="feather-title-sm"></i> Filtros</h3>
                <button id="btn-add-professional" class="btn btn-primary">
                    <i data-feather="plus"></i> Novo Profissional
                </button>
            </div>
            <div class="card-body">
                <div class="filters-row">
                    <div class="filter-group">
                        <label class="label">Especialidade:</label>
                        <select id="filter-specialty" class="input select">
                            <option value="">Todas</option>
                        </select>
                    </div>
                    <div class="filter-group">
                        <label class="label">Sala:</label>
                        <select id="filter-room" class="input select">
                            <option value="">Todas</option>
                        </select>
                    </div>
                    <div class="filter-group">
                        <label class="label">Status:</label>
                        <select id="filter-status" class="input select">
                            <option value="">Todos</option>
                            <option value="true">Ativos</option>
                            <option value="false">Inativos</option>
                        </select>
                    </div>
                    <div class="filter-actions">
                        <button id="btn-apply-filters" class="btn btn-outline btn-sm">
                            <i data-feather="search"></i> Filtrar
                        </button>
                        <button id="btn-clear-filters" class="btn btn-outline btn-sm">
                            <i data-feather="x"></i> Limpar
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Lista de Profissionais -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="list" class="feather-title-sm"></i> Lista de Profissionais</h3>
                <button id="btn-refresh-list" class="btn btn-outline btn-sm">
                    <i data-feather="refresh-cw"></i> Atualizar
                </button>
            </div>
            <div class="card-body">
                <div id="professionals-loading" class="loading-indicator">
                    <div class="spinner"></div>
                    <span>Carregando profissionais...</span>
                </div>
                <div id="professionals-empty" class="empty-state" style="display: none;">
                    <i data-feather="users" class="empty-icon"></i>
                    <p>Nenhum profissional cadastrado.</p>
                    <button class="btn btn-primary btn-sm btn-add-first">
                        <i data-feather="plus"></i> Cadastrar Primeiro Profissional
                    </button>
                </div>
                <div id="professionals-grid" class="professionals-grid" style="display: none;">
                    <!-- Cards de profissionais serão inseridos aqui -->
                </div>
            </div>
        </div>

        <!-- Modal de Adicionar/Editar Profissional -->
        <div id="professional-modal" class="modal" style="display: none;">
            <div class="modal-overlay"></div>
            <div class="modal-content modal-lg">
                <div class="modal-header">
                    <h3 id="modal-title">Novo Profissional</h3>
                    <button class="modal-close btn-icon" id="btn-modal-close">
                        <i data-feather="x"></i>
                    </button>
                </div>
                <div class="modal-body">
                    <form id="professional-form">
                        <input type="hidden" id="form-professional-id">

                        <!-- Abas -->
                        <div class="tabs">
                            <button type="button" class="tab-btn active" data-tab="tab-info">
                                <i data-feather="user"></i> Informações
                            </button>
                            <button type="button" class="tab-btn" data-tab="tab-schedule">
                                <i data-feather="calendar"></i> Horários
                            </button>
                            <button type="button" class="tab-btn" data-tab="tab-services">
                                <i data-feather="clipboard"></i> Serviços
                            </button>
                            <button type="button" class="tab-btn" data-tab="tab-google-calendar">
                                <i data-feather="link"></i> Google Calendar
                            </button>
                        </div>

                        <!-- Tab: Informações Básicas -->
                        <div id="tab-info" class="tab-content active">
                            <div class="form-row">
                                <div class="form-group form-group-lg">
                                    <label class="label required">Nome Completo:</label>
                                    <input type="text" id="form-name" class="input" required
                                           placeholder="Dr. João Silva" maxlength="255">
                                </div>
                                <div class="form-group">
                                    <label class="label">Cor:</label>
                                    <div class="color-picker" id="color-picker">
                                        ${PROFESSIONAL_COLORS.map((c, i) => `
                                            <span class="color-option ${i === 0 ? 'selected' : ''}"
                                                  data-color="${c}"
                                                  style="background-color: ${c}"></span>
                                        `).join('')}
                                    </div>
                                    <input type="hidden" id="form-color" value="${PROFESSIONAL_COLORS[0]}">
                                </div>
                            </div>

                            <div class="form-row">
                                <div class="form-group">
                                    <label class="label">Especialidade:</label>
                                    <input type="text" id="form-specialty" class="input"
                                           placeholder="Dentista, Nutricionista..." maxlength="255">
                                </div>
                                <div class="form-group">
                                    <label class="label">Registro (CRM/CRO/etc):</label>
                                    <input type="text" id="form-registration" class="input"
                                           placeholder="CRM 12345" maxlength="100">
                                </div>
                            </div>

                            <div class="form-row">
                                <div class="form-group">
                                    <label class="label">Email:</label>
                                    <input type="email" id="form-email" class="input"
                                           placeholder="email@clinica.com" maxlength="255">
                                </div>
                                <div class="form-group">
                                    <label class="label">Telefone:</label>
                                    <input type="tel" id="form-phone" class="input"
                                           placeholder="(11) 99999-9999" maxlength="50">
                                </div>
                            </div>

                            <div class="form-row">
                                <div class="form-group">
                                    <label class="label">Sala/Consultório:</label>
                                    <input type="text" id="form-room-name" class="input"
                                           placeholder="Sala 1, Consultório A" maxlength="100">
                                </div>
                                <div class="form-group">
                                    <label class="label">Número da Sala:</label>
                                    <input type="text" id="form-room-number" class="input"
                                           placeholder="101" maxlength="50">
                                </div>
                            </div>

                            <div class="form-row">
                                <div class="form-group">
                                    <label class="label">Duração da Consulta (min):</label>
                                    <input type="number" id="form-duration" class="input"
                                           value="30" min="5" max="480">
                                </div>
                                <div class="form-group">
                                    <label class="label">Intervalo entre Consultas (min):</label>
                                    <input type="number" id="form-buffer" class="input"
                                           value="10" min="0" max="60">
                                </div>
                                <div class="form-group">
                                    <label class="label">Máx. Atendimentos/Dia:</label>
                                    <input type="number" id="form-max-daily" class="input"
                                           value="20" min="1" max="100">
                                </div>
                            </div>

                            <div class="form-group">
                                <label class="label">Biografia/Descrição:</label>
                                <textarea id="form-bio" class="input textarea" rows="3"
                                          placeholder="Breve descrição do profissional..."></textarea>
                            </div>

                            <div class="form-group">
                                <div class="form-check form-switch">
                                    <input class="form-check-input" type="checkbox" id="form-accepts-new" checked>
                                    <label class="form-check-label" for="form-accepts-new">
                                        Aceita novos pacientes
                                    </label>
                                </div>
                            </div>
                        </div>

                        <!-- Tab: Horários -->
                        <div id="tab-schedule" class="tab-content" style="display: none;">
                            <p class="text-muted mb-3">Configure os horários de atendimento para cada dia da semana.</p>

                            <div class="schedule-editor" id="schedule-editor">
                                ${Object.entries(DAY_NAMES).map(([day, name]) => `
                                    <div class="schedule-day" data-day="${day}">
                                        <div class="schedule-day-header">
                                            <div class="form-check form-switch">
                                                <input class="form-check-input day-toggle" type="checkbox"
                                                       id="toggle-${day}" ${['monday', 'tuesday', 'wednesday', 'thursday', 'friday'].includes(day) ? 'checked' : ''}>
                                                <label class="form-check-label" for="toggle-${day}">
                                                    <strong>${name}</strong>
                                                </label>
                                            </div>
                                            <button type="button" class="btn btn-outline btn-xs btn-add-slot" data-day="${day}">
                                                <i data-feather="plus"></i> Período
                                            </button>
                                        </div>
                                        <div class="schedule-slots" id="slots-${day}">
                                            ${['monday', 'tuesday', 'wednesday', 'thursday', 'friday'].includes(day) ? `
                                                <div class="schedule-slot">
                                                    <input type="time" class="input input-sm slot-start" value="08:00">
                                                    <span>às</span>
                                                    <input type="time" class="input input-sm slot-end" value="12:00">
                                                    <button type="button" class="btn btn-icon btn-xs btn-remove-slot">
                                                        <i data-feather="trash-2"></i>
                                                    </button>
                                                </div>
                                                <div class="schedule-slot">
                                                    <input type="time" class="input input-sm slot-start" value="14:00">
                                                    <span>às</span>
                                                    <input type="time" class="input input-sm slot-end" value="18:00">
                                                    <button type="button" class="btn btn-icon btn-xs btn-remove-slot">
                                                        <i data-feather="trash-2"></i>
                                                    </button>
                                                </div>
                                            ` : '<p class="text-muted text-sm">Sem atendimento</p>'}
                                        </div>
                                    </div>
                                `).join('')}
                            </div>
                        </div>

                        <!-- Tab: Serviços -->
                        <div id="tab-services" class="tab-content" style="display: none;">
                            <p class="text-muted mb-3">Cadastre os serviços/procedimentos oferecidos por este profissional.</p>

                            <div id="services-list" class="services-list">
                                <p class="text-muted">Salve o profissional primeiro para adicionar serviços.</p>
                            </div>

                            <div id="add-service-form" class="add-service-form" style="display: none;">
                                <h4>Adicionar Serviço</h4>
                                <div class="form-row">
                                    <div class="form-group form-group-lg">
                                        <input type="text" id="service-name" class="input"
                                               placeholder="Nome do serviço" maxlength="255">
                                    </div>
                                    <div class="form-group">
                                        <input type="number" id="service-duration" class="input"
                                               placeholder="Duração (min)" value="30" min="5" max="480">
                                    </div>
                                    <div class="form-group">
                                        <input type="number" id="service-price" class="input"
                                               placeholder="Preço (R$)" step="0.01" min="0">
                                    </div>
                                    <div class="form-group">
                                        <button type="button" id="btn-add-service" class="btn btn-primary btn-sm">
                                            <i data-feather="plus"></i> Adicionar
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Tab: Google Calendar -->
                        <div id="tab-google-calendar" class="tab-content" style="display: none;">
                            <div class="google-calendar-section">
                                <div class="calendar-status-card">
                                    <div class="calendar-icon">
                                        <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                                            <path d="M37.5 8H10.5C8.01 8 6 10.01 6 12.5V37.5C6 39.99 8.01 42 10.5 42H37.5C39.99 42 42 39.99 42 37.5V12.5C42 10.01 39.99 8 37.5 8Z" fill="#fff" stroke="#4285F4" stroke-width="2"/>
                                            <path d="M6 18H42" stroke="#4285F4" stroke-width="2"/>
                                            <path d="M18 8V42" stroke="#4285F4" stroke-width="2"/>
                                            <circle cx="30" cy="30" r="8" fill="#34A853"/>
                                            <path d="M28 30L30 32L34 28" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                        </svg>
                                    </div>
                                    <h4>Integração com Google Calendar</h4>
                                    <p class="text-muted mb-3">
                                        Conecte o Google Calendar deste profissional para sincronizar automaticamente
                                        os agendamentos e verificar disponibilidade em tempo real.
                                    </p>

                                    <div id="calendar-status-loading" class="loading-indicator" style="display: none;">
                                        <div class="spinner"></div>
                                        <span>Verificando conexão...</span>
                                    </div>

                                    <div id="calendar-not-connected" style="display: none;">
                                        <div class="alert alert-info mb-3">
                                            <i data-feather="info"></i>
                                            <span>Google Calendar não conectado.</span>
                                        </div>
                                        <p id="calendar-save-first" class="text-muted mb-3" style="display: none;">
                                            Salve o profissional primeiro para poder conectar o Google Calendar.
                                        </p>
                                        <button type="button" id="btn-connect-calendar" class="btn btn-primary" style="display: none;">
                                            <i data-feather="link"></i> Conectar Google Calendar
                                        </button>
                                    </div>

                                    <div id="calendar-connected" style="display: none;">
                                        <div class="alert alert-success mb-3">
                                            <i data-feather="check-circle"></i>
                                            <span>Google Calendar conectado com sucesso!</span>
                                        </div>
                                        <div class="connected-info">
                                            <p><strong>Email conectado:</strong> <span id="connected-email">-</span></p>
                                            <p><strong>Última atualização:</strong> <span id="connected-updated">-</span></p>
                                        </div>
                                        <button type="button" id="btn-disconnect-calendar" class="btn btn-outline btn-danger mt-3">
                                            <i data-feather="unlink"></i> Desconectar Google Calendar
                                        </button>
                                    </div>
                                </div>

                                <div class="calendar-info mt-4">
                                    <h5>Como funciona:</h5>
                                    <ul class="feature-list">
                                        <li><i data-feather="check"></i> Os horários ocupados no Google Calendar são automaticamente bloqueados para novos agendamentos</li>
                                        <li><i data-feather="check"></i> Novos agendamentos são criados diretamente no calendário do profissional</li>
                                        <li><i data-feather="check"></i> A disponibilidade é verificada em tempo real ao oferecer horários aos clientes</li>
                                    </ul>
                                </div>
                            </div>
                        </div>

                        <div id="form-feedback" class="feedback-message"></div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline" id="btn-cancel">Cancelar</button>
                    <button type="submit" form="professional-form" class="btn btn-primary" id="btn-save">
                        <i data-feather="save"></i> Salvar
                    </button>
                </div>
            </div>
        </div>
    `;

    // Event Listeners - usando container para escopo correto
    const btnAddProfessional = container.querySelector('#btn-add-professional');
    const btnModalClose = container.querySelector('#btn-modal-close');
    const btnCancel = container.querySelector('#btn-cancel');
    const modalOverlay = container.querySelector('.modal-overlay');
    const professionalForm = container.querySelector('#professional-form');
    const btnRefreshList = container.querySelector('#btn-refresh-list');
    const btnApplyFilters = container.querySelector('#btn-apply-filters');
    const btnClearFilters = container.querySelector('#btn-clear-filters');
    const colorPicker = container.querySelector('#color-picker');
    const scheduleEditor = container.querySelector('#schedule-editor');
    const btnAddService = container.querySelector('#btn-add-service');
    const addFirstBtn = container.querySelector('.btn-add-first');

    console.log('professionals.js: Configurando event listeners...');

    if (btnAddProfessional) {
        btnAddProfessional.addEventListener('click', (e) => {
            e.preventDefault();
            console.log('professionals.js: Botão Novo Profissional clicado');
            openModal();
        });
    } else {
        console.error('professionals.js: Botão btn-add-professional não encontrado');
    }

    if (btnModalClose) btnModalClose.addEventListener('click', closeModal);
    if (btnCancel) btnCancel.addEventListener('click', closeModal);
    if (modalOverlay) modalOverlay.addEventListener('click', closeModal);

    if (professionalForm) {
        professionalForm.addEventListener('submit', handleSaveProfessional);
    }

    if (btnRefreshList) btnRefreshList.addEventListener('click', loadProfessionalsList);
    if (btnApplyFilters) btnApplyFilters.addEventListener('click', loadProfessionalsList);
    if (btnClearFilters) btnClearFilters.addEventListener('click', clearFilters);

    // Tabs
    container.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            switchTab(btn.dataset.tab);
        });
    });

    // Color picker
    if (colorPicker) {
        colorPicker.addEventListener('click', (e) => {
            if (e.target.classList.contains('color-option')) {
                container.querySelectorAll('.color-option').forEach(c => c.classList.remove('selected'));
                e.target.classList.add('selected');
                const formColor = container.querySelector('#form-color');
                if (formColor) formColor.value = e.target.dataset.color;
            }
        });
    }

    // Schedule editor
    if (scheduleEditor) {
        scheduleEditor.addEventListener('click', handleScheduleEditorClick);
    }

    // Empty state button
    if (addFirstBtn) {
        addFirstBtn.addEventListener('click', (e) => {
            e.preventDefault();
            console.log('professionals.js: Botão Cadastrar Primeiro clicado');
            openModal();
        });
    }

    // Add service button
    if (btnAddService) {
        btnAddService.addEventListener('click', handleAddService);
    }

    // Carregar dados iniciais
    try {
        await Promise.all([
            loadStats(),
            loadFilters(),
            loadProfessionalsList()
        ]);
    } catch (error) {
        console.error('professionals.js: Erro ao carregar dados iniciais:', error);
    }

    feather.replace();
    console.log('professionals.js: Página carregada com sucesso.');
}

async function loadStats() {
    if (!pageContainer) return;

    const setText = (id, val) => {
        const el = pageContainer.querySelector(`#${id}`);
        if (el) el.textContent = val;
    };

    try {
        const stats = await getProfessionalsStats();
        setText('stat-total', stats.total || 0);
        setText('stat-active', stats.active || 0);
        setText('stat-specialties', Object.keys(stats.by_specialty || {}).length);
        setText('stat-rooms', stats.rooms_in_use || 0);
    } catch (error) {
        console.error('Erro ao carregar estatísticas:', error);
    }
}

async function loadFilters() {
    if (!pageContainer) return;

    try {
        const [specialties, rooms] = await Promise.all([
            getSpecialties(),
            getRooms()
        ]);

        const specialtySelect = pageContainer.querySelector('#filter-specialty');
        if (specialtySelect && specialties) {
            specialties.forEach(s => {
                const option = document.createElement('option');
                option.value = s;
                option.textContent = s;
                specialtySelect.appendChild(option);
            });
        }

        const roomSelect = pageContainer.querySelector('#filter-room');
        if (roomSelect && rooms) {
            rooms.forEach(r => {
                const option = document.createElement('option');
                option.value = r.room_name;
                option.textContent = r.room_name + (r.room_number ? ` (${r.room_number})` : '');
                roomSelect.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Erro ao carregar filtros:', error);
    }
}

async function loadProfessionalsList() {
    if (!pageContainer) return;

    const getVal = (id) => {
        const el = pageContainer.querySelector(`#${id}`);
        return el ? el.value : '';
    };

    const loadingEl = pageContainer.querySelector('#professionals-loading');
    const emptyEl = pageContainer.querySelector('#professionals-empty');
    const gridEl = pageContainer.querySelector('#professionals-grid');

    if (loadingEl) loadingEl.style.display = 'flex';
    if (emptyEl) emptyEl.style.display = 'none';
    if (gridEl) gridEl.style.display = 'none';

    try {
        const specialty = getVal('filter-specialty');
        const room = getVal('filter-room');
        const statusValue = getVal('filter-status');
        const isActive = statusValue === '' ? null : statusValue === 'true';

        const result = await getProfessionals({
            specialty: specialty || null,
            room_name: room || null,
            is_active: isActive
        });

        const professionals = result.items || [];

        if (loadingEl) loadingEl.style.display = 'none';

        if (professionals.length === 0) {
            if (emptyEl) emptyEl.style.display = 'flex';
            return;
        }

        if (gridEl) {
            gridEl.style.display = 'grid';
            gridEl.innerHTML = professionals.map(p => createProfessionalCard(p)).join('');

            // Event listeners para botões
            gridEl.querySelectorAll('.btn-edit-professional').forEach(btn => {
                btn.addEventListener('click', () => openModal(parseInt(btn.dataset.id)));
            });

            gridEl.querySelectorAll('.btn-delete-professional').forEach(btn => {
                btn.addEventListener('click', () => handleDeleteProfessional(parseInt(btn.dataset.id)));
            });
        }

        feather.replace();

    } catch (error) {
        console.error('Erro ao carregar profissionais:', error);
        if (loadingEl) loadingEl.style.display = 'none';
        if (emptyEl) {
            emptyEl.style.display = 'flex';
            const errorP = emptyEl.querySelector('p');
            if (errorP) errorP.textContent = 'Erro ao carregar profissionais.';
        }
    }
}

function createProfessionalCard(professional) {
    const statusBadge = professional.is_active
        ? '<span class="badge badge-success">Ativo</span>'
        : '<span class="badge badge-error">Inativo</span>';

    const acceptsBadge = professional.accepts_new_patients
        ? '<span class="badge badge-primary badge-sm">Aceita novos</span>'
        : '<span class="badge badge-secondary badge-sm">Agenda fechada</span>';

    return `
        <div class="professional-card" style="border-left: 4px solid ${professional.color || '#0D9488'}">
            <div class="professional-card-header">
                <div class="professional-avatar" style="background-color: ${professional.color || '#0D9488'}">
                    ${professional.name.charAt(0).toUpperCase()}
                </div>
                <div class="professional-info">
                    <h4 class="professional-name">${professional.name}</h4>
                    <p class="professional-specialty">${professional.specialty || 'Sem especialidade'}</p>
                </div>
                ${statusBadge}
            </div>
            <div class="professional-card-body">
                ${professional.room_name ? `
                    <div class="professional-detail">
                        <i data-feather="home" class="feather-xs"></i>
                        <span>${professional.room_name}${professional.room_number ? ` (${professional.room_number})` : ''}</span>
                    </div>
                ` : ''}
                ${professional.registration_number ? `
                    <div class="professional-detail">
                        <i data-feather="award" class="feather-xs"></i>
                        <span>${professional.registration_number}</span>
                    </div>
                ` : ''}
                <div class="professional-detail">
                    <i data-feather="clock" class="feather-xs"></i>
                    <span>${professional.appointment_duration || 30} min/consulta</span>
                </div>
                ${acceptsBadge}
            </div>
            <div class="professional-card-footer">
                <button class="btn btn-outline btn-sm btn-edit-professional" data-id="${professional.id}">
                    <i data-feather="edit-2"></i> Editar
                </button>
                <button class="btn btn-outline btn-sm btn-delete-professional" data-id="${professional.id}">
                    <i data-feather="trash-2"></i>
                </button>
            </div>
        </div>
    `;
}

async function openModal(professionalId = null) {
    if (!pageContainer) {
        console.error('professionals.js: pageContainer não definido');
        return;
    }

    const modal = pageContainer.querySelector('#professional-modal');
    const title = pageContainer.querySelector('#modal-title');
    const form = pageContainer.querySelector('#professional-form');

    if (!modal || !title || !form) {
        console.error('professionals.js: Elementos do modal não encontrados', { modal, title, form });
        return;
    }

    console.log('professionals.js: Abrindo modal...');

    // Reset form
    form.reset();
    const formProfessionalId = pageContainer.querySelector('#form-professional-id');
    const formColor = pageContainer.querySelector('#form-color');
    if (formProfessionalId) formProfessionalId.value = '';
    if (formColor) formColor.value = PROFESSIONAL_COLORS[0];

    pageContainer.querySelectorAll('.color-option').forEach((c, i) => {
        c.classList.toggle('selected', i === 0);
    });
    switchTab('tab-info');

    const formFeedback = pageContainer.querySelector('#form-feedback');
    if (formFeedback) clearFeedback(formFeedback);

    // Reset schedule to default
    resetScheduleEditor();

    if (professionalId) {
        title.textContent = 'Editar Profissional';
        try {
            const professional = await getProfessionalById(professionalId);
            fillForm(professional);

            // Show services tab and load services
            const addServiceForm = pageContainer.querySelector('#add-service-form');
            if (addServiceForm) addServiceForm.style.display = 'block';
            await loadProfessionalServices(professionalId);

            // Load Google Calendar status
            await loadCalendarStatus(professionalId);
        } catch (error) {
            console.error('Erro ao carregar profissional:', error);
            if (formFeedback) showFeedback(formFeedback, 'Erro ao carregar dados', 'error');
        }
    } else {
        title.textContent = 'Novo Profissional';
        const addServiceForm = pageContainer.querySelector('#add-service-form');
        const servicesList = pageContainer.querySelector('#services-list');
        if (addServiceForm) addServiceForm.style.display = 'none';
        if (servicesList) servicesList.innerHTML = '<p class="text-muted">Salve o profissional primeiro para adicionar serviços.</p>';

        // Reset calendar status for new professional
        await loadCalendarStatus(null);
    }

    modal.style.display = 'flex';
    // Adiciona classe visible após um pequeno delay para permitir a transição CSS
    requestAnimationFrame(() => {
        modal.classList.add('visible');
    });
    feather.replace();
    console.log('professionals.js: Modal aberto com sucesso');
}

function closeModal() {
    if (!pageContainer) return;
    const modal = pageContainer.querySelector('#professional-modal');
    if (modal) {
        modal.classList.remove('visible');
        // Aguarda a transição CSS antes de ocultar completamente
        setTimeout(() => {
            modal.style.display = 'none';
        }, 200);
    }
}

function switchTab(tabId) {
    if (!pageContainer) return;
    pageContainer.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    pageContainer.querySelectorAll('.tab-content').forEach(content => {
        content.style.display = content.id === tabId ? 'block' : 'none';
    });
    feather.replace();
}

function fillForm(professional) {
    if (!pageContainer) return;

    const setVal = (id, val) => {
        const el = pageContainer.querySelector(`#${id}`);
        if (el) el.value = val;
    };

    const setCheck = (id, val) => {
        const el = pageContainer.querySelector(`#${id}`);
        if (el) el.checked = val;
    };

    setVal('form-professional-id', professional.id);
    setVal('form-name', professional.name || '');
    setVal('form-specialty', professional.specialty || '');
    setVal('form-registration', professional.registration_number || '');
    setVal('form-email', professional.email || '');
    setVal('form-phone', professional.phone || '');
    setVal('form-room-name', professional.room_name || '');
    setVal('form-room-number', professional.room_number || '');
    setVal('form-duration', professional.appointment_duration || 30);
    setVal('form-buffer', professional.buffer_time || 10);
    setVal('form-max-daily', professional.max_daily_appointments || 20);
    setVal('form-bio', professional.bio || '');
    setCheck('form-accepts-new', professional.accepts_new_patients !== false);

    // Color
    const color = professional.color || PROFESSIONAL_COLORS[0];
    setVal('form-color', color);
    pageContainer.querySelectorAll('.color-option').forEach(c => {
        c.classList.toggle('selected', c.dataset.color === color);
    });

    // Schedule
    if (professional.availability_schedule) {
        fillScheduleEditor(professional.availability_schedule);
    }
}

function resetScheduleEditor() {
    if (!pageContainer) return;

    Object.keys(DAY_NAMES).forEach(day => {
        const toggle = pageContainer.querySelector(`#toggle-${day}`);
        const slotsContainer = pageContainer.querySelector(`#slots-${day}`);

        if (!toggle || !slotsContainer) return;

        const isWeekday = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'].includes(day);
        toggle.checked = isWeekday;

        if (isWeekday) {
            slotsContainer.innerHTML = `
                <div class="schedule-slot">
                    <input type="time" class="input input-sm slot-start" value="08:00">
                    <span>às</span>
                    <input type="time" class="input input-sm slot-end" value="12:00">
                    <button type="button" class="btn btn-icon btn-xs btn-remove-slot">
                        <i data-feather="trash-2"></i>
                    </button>
                </div>
                <div class="schedule-slot">
                    <input type="time" class="input input-sm slot-start" value="14:00">
                    <span>às</span>
                    <input type="time" class="input input-sm slot-end" value="18:00">
                    <button type="button" class="btn btn-icon btn-xs btn-remove-slot">
                        <i data-feather="trash-2"></i>
                    </button>
                </div>
            `;
        } else {
            slotsContainer.innerHTML = '<p class="text-muted text-sm">Sem atendimento</p>';
        }
    });
    feather.replace();
}

function fillScheduleEditor(schedule) {
    if (!pageContainer) return;

    Object.keys(DAY_NAMES).forEach(day => {
        const toggle = pageContainer.querySelector(`#toggle-${day}`);
        const slotsContainer = pageContainer.querySelector(`#slots-${day}`);
        const daySlots = schedule[day] || [];

        if (!toggle || !slotsContainer) return;

        toggle.checked = daySlots.length > 0;

        if (daySlots.length > 0) {
            slotsContainer.innerHTML = daySlots.map(slot => `
                <div class="schedule-slot">
                    <input type="time" class="input input-sm slot-start" value="${slot.start}">
                    <span>às</span>
                    <input type="time" class="input input-sm slot-end" value="${slot.end}">
                    <button type="button" class="btn btn-icon btn-xs btn-remove-slot">
                        <i data-feather="trash-2"></i>
                    </button>
                </div>
            `).join('');
        } else {
            slotsContainer.innerHTML = '<p class="text-muted text-sm">Sem atendimento</p>';
        }
    });
    feather.replace();
}

function getScheduleFromEditor() {
    if (!pageContainer) return {};

    const schedule = {};

    Object.keys(DAY_NAMES).forEach(day => {
        const toggle = pageContainer.querySelector(`#toggle-${day}`);
        const slotsContainer = pageContainer.querySelector(`#slots-${day}`);

        if (!toggle.checked) {
            schedule[day] = [];
            return;
        }

        const slots = [];
        slotsContainer.querySelectorAll('.schedule-slot').forEach(slotEl => {
            const start = slotEl.querySelector('.slot-start')?.value;
            const end = slotEl.querySelector('.slot-end')?.value;
            if (start && end) {
                slots.push({ start, end });
            }
        });

        schedule[day] = slots;
    });

    return schedule;
}

function handleScheduleEditorClick(e) {
    if (e.target.closest('.btn-add-slot')) {
        const day = e.target.closest('.btn-add-slot').dataset.day;
        addScheduleSlot(day);
    } else if (e.target.closest('.btn-remove-slot')) {
        const slot = e.target.closest('.schedule-slot');
        slot.remove();
    }
}

function addScheduleSlot(day) {
    if (!pageContainer) return;

    const slotsContainer = pageContainer.querySelector(`#slots-${day}`);
    if (!slotsContainer) return;

    // Remove "Sem atendimento" message if present
    const noSlotMsg = slotsContainer.querySelector('p.text-muted');
    if (noSlotMsg) noSlotMsg.remove();

    const slotHtml = `
        <div class="schedule-slot">
            <input type="time" class="input input-sm slot-start" value="09:00">
            <span>às</span>
            <input type="time" class="input input-sm slot-end" value="12:00">
            <button type="button" class="btn btn-icon btn-xs btn-remove-slot">
                <i data-feather="trash-2"></i>
            </button>
        </div>
    `;
    slotsContainer.insertAdjacentHTML('beforeend', slotHtml);

    // Enable toggle if not enabled
    const toggle = pageContainer.querySelector(`#toggle-${day}`);
    if (toggle) toggle.checked = true;

    feather.replace();
}

async function handleSaveProfessional(e) {
    e.preventDefault();

    if (!pageContainer) return;

    const getVal = (id) => {
        const el = pageContainer.querySelector(`#${id}`);
        return el ? el.value : '';
    };

    const getCheck = (id) => {
        const el = pageContainer.querySelector(`#${id}`);
        return el ? el.checked : false;
    };

    const feedbackEl = pageContainer.querySelector('#form-feedback');
    const saveBtn = pageContainer.querySelector('#btn-save');
    const professionalId = getVal('form-professional-id');

    if (feedbackEl) clearFeedback(feedbackEl);
    if (saveBtn) setLoadingState(saveBtn, true, 'Salvando...');

    try {
        const data = {
            name: getVal('form-name').trim(),
            specialty: getVal('form-specialty').trim() || null,
            registration_number: getVal('form-registration').trim() || null,
            email: getVal('form-email').trim() || null,
            phone: getVal('form-phone').trim() || null,
            room_name: getVal('form-room-name').trim() || null,
            room_number: getVal('form-room-number').trim() || null,
            color: getVal('form-color'),
            bio: getVal('form-bio').trim() || null,
            appointment_duration: parseInt(getVal('form-duration')) || 30,
            buffer_time: parseInt(getVal('form-buffer')) || 10,
            max_daily_appointments: parseInt(getVal('form-max-daily')) || 20,
            accepts_new_patients: getCheck('form-accepts-new'),
            availability_schedule: getScheduleFromEditor()
        };

        if (!data.name) {
            if (feedbackEl) showFeedback(feedbackEl, 'Nome é obrigatório', 'error');
            return;
        }

        if (professionalId) {
            await updateProfessional(parseInt(professionalId), data);
            if (feedbackEl) showFeedback(feedbackEl, 'Profissional atualizado com sucesso!', 'success');
        } else {
            const result = await createProfessional(data);
            const formProfId = pageContainer.querySelector('#form-professional-id');
            const addServiceForm = pageContainer.querySelector('#add-service-form');
            if (formProfId) formProfId.value = result.data.id;
            if (addServiceForm) addServiceForm.style.display = 'block';
            if (feedbackEl) showFeedback(feedbackEl, 'Profissional criado com sucesso!', 'success');
        }

        await loadProfessionalsList();
        await loadStats();

    } catch (error) {
        console.error('Erro ao salvar profissional:', error);
        if (feedbackEl) showFeedback(feedbackEl, error.message || 'Erro ao salvar profissional', 'error');
    } finally {
        if (saveBtn) setLoadingState(saveBtn, false, 'Salvar');
        feather.replace();
    }
}

async function handleDeleteProfessional(professionalId) {
    if (!confirm('Tem certeza que deseja desativar este profissional?')) return;

    try {
        await deleteProfessional(professionalId);
        await loadProfessionalsList();
        await loadStats();
    } catch (error) {
        console.error('Erro ao desativar profissional:', error);
        alert(error.message || 'Erro ao desativar profissional');
    }
}

async function loadProfessionalServices(professionalId) {
    if (!pageContainer) return;

    const servicesContainer = pageContainer.querySelector('#services-list');
    if (!servicesContainer) return;

    try {
        const services = await getProfessionalServices(professionalId);

        if (services.length === 0) {
            servicesContainer.innerHTML = '<p class="text-muted">Nenhum serviço cadastrado.</p>';
            return;
        }

        servicesContainer.innerHTML = services.map(s => `
            <div class="service-item">
                <div class="service-info">
                    <strong>${s.service_name}</strong>
                    <span class="text-muted">${s.duration_minutes} min</span>
                    ${s.price ? `<span class="service-price">R$ ${parseFloat(s.price).toFixed(2)}</span>` : ''}
                </div>
                <span class="badge ${s.is_active ? 'badge-success' : 'badge-secondary'}">${s.is_active ? 'Ativo' : 'Inativo'}</span>
            </div>
        `).join('');

    } catch (error) {
        console.error('Erro ao carregar serviços:', error);
        servicesContainer.innerHTML = '<p class="text-muted text-error">Erro ao carregar serviços.</p>';
    }
}

async function handleAddService() {
    if (!pageContainer) return;

    const getVal = (id) => {
        const el = pageContainer.querySelector(`#${id}`);
        return el ? el.value : '';
    };

    const setVal = (id, val) => {
        const el = pageContainer.querySelector(`#${id}`);
        if (el) el.value = val;
    };

    const professionalId = getVal('form-professional-id');
    if (!professionalId) {
        alert('Salve o profissional primeiro');
        return;
    }

    const serviceName = getVal('service-name').trim();
    const duration = parseInt(getVal('service-duration')) || 30;
    const price = parseFloat(getVal('service-price')) || null;

    if (!serviceName) {
        alert('Nome do serviço é obrigatório');
        return;
    }

    try {
        await createService({
            professional_id: parseInt(professionalId),
            service_name: serviceName,
            duration_minutes: duration,
            price: price
        });

        setVal('service-name', '');
        setVal('service-duration', '30');
        setVal('service-price', '');

        await loadProfessionalServices(parseInt(professionalId));

    } catch (error) {
        console.error('Erro ao adicionar serviço:', error);
        alert(error.message || 'Erro ao adicionar serviço');
    }
}

function clearFilters() {
    if (!pageContainer) return;

    const setVal = (id, val) => {
        const el = pageContainer.querySelector(`#${id}`);
        if (el) el.value = val;
    };

    setVal('filter-specialty', '');
    setVal('filter-room', '');
    setVal('filter-status', '');
    loadProfessionalsList();
}

// ========== Google Calendar Functions ==========

async function loadCalendarStatus(professionalId) {
    if (!pageContainer) return;

    const loadingEl = pageContainer.querySelector('#calendar-status-loading');
    const notConnectedEl = pageContainer.querySelector('#calendar-not-connected');
    const connectedEl = pageContainer.querySelector('#calendar-connected');
    const saveFirstEl = pageContainer.querySelector('#calendar-save-first');
    const connectBtn = pageContainer.querySelector('#btn-connect-calendar');

    // Reset visibility
    if (loadingEl) loadingEl.style.display = 'none';
    if (notConnectedEl) notConnectedEl.style.display = 'none';
    if (connectedEl) connectedEl.style.display = 'none';

    // If no professional ID, show save first message
    if (!professionalId) {
        if (notConnectedEl) notConnectedEl.style.display = 'block';
        if (saveFirstEl) saveFirstEl.style.display = 'block';
        if (connectBtn) connectBtn.style.display = 'none';
        return;
    }

    // Show loading
    if (loadingEl) loadingEl.style.display = 'flex';

    try {
        const status = await getProfessionalCalendarStatus(professionalId);
        console.log('professionals.js: Calendar status:', status);

        if (loadingEl) loadingEl.style.display = 'none';

        if (status.is_connected) {
            if (connectedEl) connectedEl.style.display = 'block';
            const emailEl = pageContainer.querySelector('#connected-email');
            const updatedEl = pageContainer.querySelector('#connected-updated');
            if (emailEl) emailEl.textContent = status.email || '-';
            if (updatedEl) {
                // Formatação com timezone America/Sao_Paulo (GMT-3)
                updatedEl.textContent = status.last_updated
                    ? new Date(status.last_updated).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' })
                    : '-';
            }
        } else {
            if (notConnectedEl) notConnectedEl.style.display = 'block';
            if (saveFirstEl) saveFirstEl.style.display = 'none';
            if (connectBtn) connectBtn.style.display = 'inline-flex';
        }

        // Setup event listeners for calendar buttons
        setupCalendarEventListeners(professionalId);

    } catch (error) {
        console.error('professionals.js: Error loading calendar status:', error);
        if (loadingEl) loadingEl.style.display = 'none';
        if (notConnectedEl) notConnectedEl.style.display = 'block';
        if (saveFirstEl) saveFirstEl.style.display = 'none';
        if (connectBtn) connectBtn.style.display = 'inline-flex';
        setupCalendarEventListeners(professionalId);
    }

    feather.replace();
}

function setupCalendarEventListeners(professionalId) {
    if (!pageContainer) return;

    const connectBtn = pageContainer.querySelector('#btn-connect-calendar');
    const disconnectBtn = pageContainer.querySelector('#btn-disconnect-calendar');

    // Remove existing listeners by cloning
    if (connectBtn) {
        const newConnectBtn = connectBtn.cloneNode(true);
        connectBtn.parentNode.replaceChild(newConnectBtn, connectBtn);
        newConnectBtn.addEventListener('click', () => handleConnectCalendar(professionalId));
    }

    if (disconnectBtn) {
        const newDisconnectBtn = disconnectBtn.cloneNode(true);
        disconnectBtn.parentNode.replaceChild(newDisconnectBtn, disconnectBtn);
        newDisconnectBtn.addEventListener('click', () => handleDisconnectCalendar(professionalId));
    }

    feather.replace();
}

function handleConnectCalendar(professionalId) {
    if (!professionalId) {
        alert('Salve o profissional primeiro para conectar o Google Calendar.');
        return;
    }

    console.log('professionals.js: Connecting calendar for professional', professionalId);

    // Open OAuth in a new window/tab
    const authUrl = `/api/professionals/${professionalId}/calendar/auth`;
    window.open(authUrl, '_blank');

    // Show message to user
    const feedbackEl = pageContainer?.querySelector('#form-feedback');
    if (feedbackEl) {
        showFeedback(feedbackEl, 'Uma nova janela foi aberta para autenticação. Após autorizar, atualize esta página.', 'info');
    }
}

async function handleDisconnectCalendar(professionalId) {
    if (!confirm('Deseja desconectar o Google Calendar deste profissional?')) return;

    console.log('professionals.js: Disconnecting calendar for professional', professionalId);

    try {
        await disconnectProfessionalCalendar(professionalId);

        const feedbackEl = pageContainer?.querySelector('#form-feedback');
        if (feedbackEl) {
            showFeedback(feedbackEl, 'Google Calendar desconectado com sucesso!', 'success');
        }

        // Reload calendar status
        await loadCalendarStatus(professionalId);

    } catch (error) {
        console.error('professionals.js: Error disconnecting calendar:', error);
        const feedbackEl = pageContainer?.querySelector('#form-feedback');
        if (feedbackEl) {
            showFeedback(feedbackEl, 'Erro ao desconectar Google Calendar.', 'error');
        }
    }
}

console.log('professionals.js: Módulo carregado.');
