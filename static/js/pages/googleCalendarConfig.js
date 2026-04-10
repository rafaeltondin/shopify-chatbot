// static/js/pages/googleCalendarConfig.js
import { 
    getGoogleCalendarStatus, disconnectGoogleCalendar,
    getGoogleCalendarAvailability, setGoogleCalendarAvailability,
    GOOGLE_CALENDAR_AUTH_URL
} from '../api.js';
import { showFeedback, clearFeedback, setLoadingState } from '../utils.js';

const weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];
const weekdayTranslations = {
    monday: 'Segunda-feira',
    tuesday: 'Terça-feira',
    wednesday: 'Quarta-feira',
    thursday: 'Quinta-feira',
    friday: 'Sexta-feira',
    saturday: 'Sábado',
    sunday: 'Domingo'
};

export async function loadGoogleCalendarConfigPage(container, params) { // Aceita 'params'
    console.log('googleCalendarConfig.js: Carregando página de Configuração do Google Calendar...');
    container.innerHTML = `
        <header class="page-header">
            <h1 class="page-title"><i data-feather="calendar" class="feather-title"></i> Google Calendar</h1>
            <p class="page-description">Conecte sua conta Google Calendar e defina sua disponibilidade para agendamentos.</p>
        </header>

        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="link" class="feather-title-sm"></i> Conexão com Google Calendar</h3>
            </div>
            <div class="card-body">
                <div id="google-calendar-status-section">
                    <p id="gcal-connection-status">Verificando status da conexão...</p>
                    <div id="gcal-connection-feedback" class="feedback-message" style="margin-top: 10px; margin-bottom: 10px;"></div>
                    <div class="btn-actions">
                        <button id="btn-connect-gcal" class="btn btn-success btn-google-connect" style="display: none;">
                            <i data-feather="zap"></i><span>CONECTAR COM GOOGLE CALENDAR</span>
                        </button>
                        <button id="btn-disconnect-gcal" class="btn btn-danger btn-disconnect-gcal-custom" style="display: none;">
                            <i data-feather="x-circle"></i><span>Desconectar Google Calendar</span>
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="clock" class="feather-title-sm"></i> Configurar Disponibilidade</h3>
            </div>
            <div class="card-body">
                <form id="gcal-availability-form" class="form" style="display: none;">
                    <p class="form-text">Defina os dias e horários em que você está disponível para receber agendamentos. Use o formato HH:MM-HH:MM (ex: 09:00-12:30).</p>
                    ${weekdays.map(day => `
                        <div class="form-group availability-day-group">
                            <label class="label">${weekdayTranslations[day]}:</label>
                            <div id="${day}-intervals" class="time-intervals-container">
                                <!-- Intervalos de tempo serão adicionados aqui -->
                            </div>
                            <button type="button" class="btn btn-outline btn-add-interval" data-day="${day}">
                                <i data-feather="plus-circle"></i> Adicionar Intervalo
                            </button>
                        </div>
                    `).join('')}

                    <div class="form-group">
                        <label class="label" for="gcal-include-video-call">Incluir Videochamada nos Agendamentos:</label>
                        <div class="form-check form-switch">
                            <input class="form-check-input" type="checkbox" id="gcal-include-video-call">
                            <label class="form-check-label" for="gcal-include-video-call">
                                Permitir que a IA agende eventos com Google Meet.
                            </label>
                        </div>
                        <small class="form-text text-muted">Se marcado, a IA poderá criar eventos com um link do Google Meet. A decisão final por evento pode depender de outras configurações ou do fluxo de interação.</small>
                    </div>

                    <div id="gcal-availability-feedback" class="feedback-message"></div>
                    <button type="submit" class="btn btn-primary">
                        <i data-feather="save"></i> Salvar Disponibilidade
                    </button>
                </form>
            </div>
        </div>
    `;

    // Event Listeners
    document.getElementById('btn-connect-gcal').addEventListener('click', handleConnectGoogleCalendar);
    document.getElementById('btn-disconnect-gcal').addEventListener('click', handleDisconnectGoogleCalendar);
    document.getElementById('gcal-availability-form').addEventListener('submit', handleGCalAvailabilitySubmit);
    
    document.querySelectorAll('.btn-add-interval').forEach(button => {
        button.addEventListener('click', (e) => addIntervalInput(e.target.closest('button').dataset.day));
    });
    
    // Initial load
    await loadGoogleCalendarStatusAndAvailability();

    // Verificar parâmetros da URL (passados pelo router) para feedback do OAuth
    if (params && params.has('gcal_status')) {
        const status = params.get('gcal_status');
        const message = params.get('message');
        const connectionFeedbackEl = document.getElementById('gcal-connection-feedback');
        
        if (status === 'success') {
            showFeedback(connectionFeedbackEl, 'Google Calendar conectado com sucesso!', 'success');
            // O status será atualizado automaticamente pela chamada loadGoogleCalendarStatusAndAvailability
        } else if (status === 'error') {
            showFeedback(connectionFeedbackEl, `Falha ao conectar Google Calendar: ${message || 'Erro desconhecido.'}`, 'error');
        }

        // Limpa a URL dos parâmetros para evitar que a mensagem apareça em reloads da página (F5)
        // A navegação para outras âncoras já resolve isso naturalmente.
        if (window.history.replaceState) {
            const cleanURL = window.location.pathname + window.location.hash.split('?')[0];
            window.history.replaceState({ path: cleanURL }, '', cleanURL);
        }
    }
    
    feather.replace();
    console.log('googleCalendarConfig.js: Página de Configuração do Google Calendar carregada e listeners configurados.');
}

async function loadGoogleCalendarStatusAndAvailability() {
    console.log('googleCalendarConfig.js: Carregando status e disponibilidade do Google Calendar...');
    const statusElement = document.getElementById('gcal-connection-status');
    const connectBtn = document.getElementById('btn-connect-gcal');
    const disconnectBtn = document.getElementById('btn-disconnect-gcal');
    const availabilityForm = document.getElementById('gcal-availability-form');
    const connectionFeedbackEl = document.getElementById('gcal-connection-feedback');
    clearFeedback(connectionFeedbackEl);

    try {
        const status = await getGoogleCalendarStatus();
        console.log('googleCalendarConfig.js: Status da conexão com Google Calendar:', status);
        if (status.is_connected) {
            statusElement.innerHTML = `<i data-feather="check-circle" class="feather-sm text-success"></i> Conectado como: ${status.email}`;
            connectBtn.style.display = 'none';
            disconnectBtn.style.display = ''; // Remove o display inline-block, usa o display da classe .btn (inline-flex)
            availabilityForm.style.display = 'block';
            await loadAvailabilityForm();
        } else {
            statusElement.textContent = status.message || 'Não conectado ao Google Calendar.';
            connectBtn.style.display = 'inline-flex'; // Alterado de inline-block para inline-flex
            disconnectBtn.style.display = 'none';
            availabilityForm.style.display = 'none';
        }
    } catch (error) {
        console.error('googleCalendarConfig.js: Erro ao buscar status do Google Calendar:', error);
        statusElement.textContent = 'Erro ao verificar status da conexão.';
        showFeedback(connectionFeedbackEl, error.message || 'Erro ao carregar status do Google Calendar.', 'error');
        connectBtn.style.display = 'inline-flex'; // Alterado de inline-block para inline-flex
        disconnectBtn.style.display = 'none';
        availabilityForm.style.display = 'none';
    }
    feather.replace();
}

function handleConnectGoogleCalendar() {
    console.log('googleCalendarConfig.js: Botão Conectar Google Calendar clicado.');
    window.location.href = GOOGLE_CALENDAR_AUTH_URL;
}

async function handleDisconnectGoogleCalendar() {
    console.log('googleCalendarConfig.js: Botão Desconectar Google Calendar clicado.');
    const connectionFeedbackEl = document.getElementById('gcal-connection-feedback'); 
    clearFeedback(connectionFeedbackEl); // Limpa o feedback específico da conexão
    if (!confirm('Tem certeza que deseja desconectar sua conta do Google Calendar?')) {
        return;
    }
    const submitBtn = document.getElementById('btn-disconnect-gcal');
    setLoadingState(submitBtn, true, "Desconectando...");
    try {
        const response = await disconnectGoogleCalendar(); // Captura a resposta da API
        showFeedback(connectionFeedbackEl, response.message || 'Google Calendar desconectado com sucesso.', 'success');
        await loadGoogleCalendarStatusAndAvailability(); 
        console.log('googleCalendarConfig.js: Google Calendar desconectado.');
    } catch (error) {
        console.error('googleCalendarConfig.js: Erro ao desconectar Google Calendar:', error);
        showFeedback(connectionFeedbackEl, error.message || 'Erro ao desconectar Google Calendar.', 'error');
    } finally {
        setLoadingState(submitBtn, false, "Desconectar Google Calendar");
         feather.replace();
    }
}

async function loadAvailabilityForm() {
    console.log('googleCalendarConfig.js: Carregando formulário de disponibilidade...');
    const feedbackContainer = document.getElementById('gcal-availability-feedback');
    clearFeedback(feedbackContainer);
    try {
        const availabilityData = await getGoogleCalendarAvailability();
        console.log('googleCalendarConfig.js: Dados de disponibilidade recebidos:', availabilityData);
        console.log(`googleCalendarConfig.js: [DEBUG_GCAL_LOAD_AVAIL] Dados de disponibilidade completos recebidos da API: ${JSON.stringify(availabilityData)}`);
        
        weekdays.forEach(day => {
            const container = document.getElementById(`${day}-intervals`);
            container.innerHTML = ''; 
            const intervals = availabilityData[day] || [];
            if (intervals.length > 0) {
                intervals.forEach(interval => addIntervalInput(day, interval));
            }
        });

        // Carregar o estado do checkbox de videochamada
        const includeVideoCallCheckbox = document.getElementById('gcal-include-video-call');
        if (availabilityData && typeof availabilityData.include_video_call === 'boolean') { 
            includeVideoCallCheckbox.checked = availabilityData.include_video_call; 
            console.log(`googleCalendarConfig.js: [DEBUG_GCAL_LOAD_AVAIL] Checkbox 'gcal-include-video-call' definido para: ${availabilityData.include_video_call} (Tipo: ${typeof availabilityData.include_video_call})`);
        } else {
            includeVideoCallCheckbox.checked = false; // Valor padrão caso não esteja definido
            console.log(`googleCalendarConfig.js: [DEBUG_GCAL_LOAD_AVAIL] 'include_video_call' não encontrado ou tipo inválido em availabilityData. Checkbox definido para false. Dados: ${JSON.stringify(availabilityData)}`);
        }

        console.log('googleCalendarConfig.js: Formulário de disponibilidade preenchido.');
    } catch (error) {
        console.error('googleCalendarConfig.js: Erro ao carregar dados de disponibilidade:', error);
        showFeedback(feedbackContainer, error.message || 'Erro ao carregar disponibilidade.', 'error');
    }
}

function addIntervalInput(day, value = '') {
    console.log(`googleCalendarConfig.js: Adicionando input de intervalo para ${day}, valor: ${value}`);
    const container = document.getElementById(`${day}-intervals`);
    const intervalGroup = document.createElement('div');
    intervalGroup.className = 'time-interval-group';
    
    const timeInput = document.createElement('input');
    timeInput.type = 'text';
    timeInput.className = 'input input-sm time-interval-input';
    timeInput.placeholder = 'HH:MM-HH:MM';
    timeInput.value = value;
    
    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'btn btn-remove-interval';
    removeBtn.innerHTML = '<i data-feather="trash-2"></i>';
    removeBtn.title = 'Remover intervalo';
    removeBtn.onclick = () => {
        container.removeChild(intervalGroup);
        feather.replace();
    };
    
    intervalGroup.appendChild(timeInput);
    intervalGroup.appendChild(removeBtn);
    container.appendChild(intervalGroup);
    feather.replace(); 
}

async function handleGCalAvailabilitySubmit(event) {
    event.preventDefault();
    console.log('googleCalendarConfig.js: Formulário de disponibilidade do Google Calendar submetido.');
    const feedbackContainer = document.getElementById('gcal-availability-feedback');
    const submitBtn = event.currentTarget.querySelector('button[type="submit"]');
    setLoadingState(submitBtn, true);
    clearFeedback(feedbackContainer);

    const availabilityPayload = {};
    let isValid = true;

    // Obter o valor do checkbox de videochamada
    const includeVideoCallCheckbox = document.getElementById('gcal-include-video-call');
    const includeVideoCall = includeVideoCallCheckbox.checked; 
    availabilityPayload.include_video_call = includeVideoCall; 
    console.log(`googleCalendarConfig.js: [DEBUG_GCAL_SUBMIT] Valor do checkbox 'gcal-include-video-call' no momento do submit: ${includeVideoCall} (Tipo: ${typeof includeVideoCall})`);

    weekdays.forEach(day => {
        const intervalsContainer = document.getElementById(`${day}-intervals`);
        const inputs = intervalsContainer.querySelectorAll('.time-interval-input');
        availabilityPayload[day] = [];
        inputs.forEach(input => {
            const value = input.value.trim();
            if (value) {
                if (!/^\d{2}:\d{2}-\d{2}:\d{2}$/.test(value)) {
                    isValid = false;
                    input.classList.add('input-error'); 
                    console.warn(`googleCalendarConfig.js: Formato de intervalo inválido para ${day}: ${value}`);
                } else {
                    const [start, end] = value.split('-');
                    if (start >= end) {
                        isValid = false;
                        input.classList.add('input-error');
                        console.warn(`googleCalendarConfig.js: Horário de início deve ser menor que o de fim para ${day}: ${value}`);
                    } else {
                        input.classList.remove('input-error');
                        availabilityPayload[day].push(value);
                    }
                }
            }
        });
    });

    if (!isValid) {
        showFeedback(feedbackContainer, 'Alguns intervalos de tempo estão em formato inválido (use HH:MM-HH:MM e início < fim).', 'error');
        setLoadingState(submitBtn, false);
        return;
    }
    
    console.log('googleCalendarConfig.js: Payload de disponibilidade a ser enviado:', availabilityPayload);

    try {
        const response = await setGoogleCalendarAvailability(availabilityPayload);
        showFeedback(feedbackContainer, response.message, 'success');
        console.log('googleCalendarConfig.js: Disponibilidade do Google Calendar salva com sucesso.');
    } catch (error) {
        console.error('googleCalendarConfig.js: Erro ao salvar disponibilidade do Google Calendar:', error);
        showFeedback(feedbackContainer, error.message || 'Erro ao salvar disponibilidade.', 'error');
    } finally {
        setLoadingState(submitBtn, false);
    }
}
