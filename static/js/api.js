// static/js/api.js
import { showFeedback, clearFeedback, showNoCreditPopup } from './utils.js'; // Adicionado showNoCreditPopup

const API_BASE_URL = '/api'; // Prefixo da API definido no main.py
const AUTH_BASE_URL = '/auth'; // Prefixo para rotas de autenticação como Google

async function request(endpoint, method = 'GET', data = null, isFormData = false, isAuthRoute = false) {
    const baseUrl = isAuthRoute ? AUTH_BASE_URL : API_BASE_URL;
    console.log(`api.js: Fazendo requisição ${method} para ${baseUrl}${endpoint}`);
    const url = `${baseUrl}${endpoint}`;
    const headers = {
        'Content-Type': 'application/json',
    };

    // Adicionar token de autenticação se não for a rota de login e o token existir
    const token = localStorage.getItem('innovaFluxoAuthToken');
    if (token && endpoint !== '/login') { // Não enviar token para o próprio endpoint de login
        headers['Authorization'] = `Bearer ${token}`;
        console.log(`api.js: Token JWT adicionado ao header para ${endpoint}`);
    }

    const options = {
        method: method,
        headers: headers,
    };

    if (endpoint === '/login' && data && method === 'POST') {
        // Para OAuth2PasswordRequestForm, os dados devem ser form-urlencoded
        options.headers['Content-Type'] = 'application/x-www-form-urlencoded';
        const formBody = [];
        for (const property in data) {
            const encodedKey = encodeURIComponent(property);
            const encodedValue = encodeURIComponent(data[property]);
            formBody.push(encodedKey + "=" + encodedValue);
        }
        options.body = formBody.join("&");
        console.log('api.js: Dados de login formatados como x-www-form-urlencoded:', options.body);
    } else if (isFormData && typeof isFormData === 'boolean') {
        options.body = data; // FormData não precisa de Content-Type
        delete options.headers['Content-Type']; // O browser define o Content-Type para FormData
    } else if (typeof isFormData === 'string') { // Se isFormData for string (como 'text/csv')
        headers['Content-Type'] = isFormData;
        options.body = data;
    } else if (data) {
        options.body = JSON.stringify(data);
    }

    // Obter o elemento container para feedback
    const feedbackContainer = document.getElementById('global-feedback-container');
    if (!feedbackContainer) {
        console.warn('api.js: Elemento #global-feedback-container não encontrado. Mensagens de feedback não serão exibidas.');
    } else {
        clearFeedback(feedbackContainer); // Limpa mensagens anteriores antes de uma nova requisição
    }

    try {
        const response = await fetch(url, options);
        // Para redirecionamentos (como o início do fluxo OAuth), não esperamos JSON.
        if (response.redirected && endpoint.startsWith('/google/calendar') && method === 'GET' && isAuthRoute) {
            console.log(`api.js: Requisição ${method} ${url} resultou em redirecionamento para ${response.url}.`);
            // O navegador seguirá o redirecionamento automaticamente.
            // Não há corpo JSON para processar aqui.
            return { success: true, redirected_to: response.url }; 
        }
        
        const responseData = await response.json();

        if (!response.ok) {
            console.error(`api.js: Erro na requisição ${method} ${url}:`, response.status, responseData);
            const errorMessage = responseData.detail || 'Ocorreu um erro na API.';
            
            if (response.status === 401) { // Unauthorized
                // Apenas recarrega a página se um token existia.
                // Isso diferencia uma sessão expirada de um estado "não logado".
                if (token) {
                    console.log('api.js: Recebido erro 401 com token existente. Provavelmente expirado. Deslogando...');
                    localStorage.removeItem('innovaFluxoAuthToken');
                    if (feedbackContainer) {
                        showFeedback(feedbackContainer, 'Sua sessão expirou. Por favor, faça login novamente.', 'error');
                    }
                    setTimeout(() => {
                        window.location.reload();
                    }, 3000);
                } else {
                    // Se não havia token, o usuário simplesmente não está logado. Não faz nada,
                    // pois a UI já deve estar mostrando a tela de login.
                    console.log('api.js: Recebido erro 401 sem token. O usuário não está logado. Não haverá recarregamento.');
                }
            } else if (response.status === 402) { // Payment Required
                showNoCreditPopup(errorMessage); // Chama a função importada
            } else if (feedbackContainer) {
                showFeedback(feedbackContainer, `Erro: ${errorMessage}`, 'error');
            }
            throw new Error(errorMessage);
        }
        console.log(`api.js: Requisição ${method} ${url} bem-sucedida.`, responseData);
        if (feedbackContainer && (method === 'POST' || method === 'PUT' || method === 'DELETE')) {
            // Para clearAllHistory, generateSalesFlowTemplate e login, a mensagem de sucesso é tratada no JS da página/auth para ser mais específica.
            // Evitar mostrar a mensagem genérica "Alterações salvas com sucesso!" aqui.
            if (endpoint !== '/dashboard/clear-history' && endpoint !== '/sales-flow/generate-template' && endpoint !== '/login') {
                 showFeedback(feedbackContainer, responseData.message || 'Alterações salvas com sucesso!', 'success');
                 // Opcional: Limpar a mensagem de sucesso após alguns segundos
                 setTimeout(() => clearFeedback(feedbackContainer), 5000);
            }
        }
        return responseData;
    } catch (error) {
        console.error(`api.js: Erro de rede ou processamento para ${url}:`, error);
        const errorMessage = error.message || 'Erro de conexão ou processamento.';
        if (feedbackContainer && !(error instanceof SyntaxError && error.message.includes("Unexpected end of JSON input"))) { // Não mostrar erro de JSON parse para redirecionamentos
            showFeedback(feedbackContainer, `Erro: ${errorMessage}`, 'error');
        }
        throw error; // Re-lança o erro para ser tratado no nível da UI
    }
}

// --- Funções de API específicas ---

// Autenticação
export const login = (username, password) => request('/login', 'POST', { username, password });
console.log('api.js: Função login exportada.');

// Dashboard
export const getDashboardStats = (initiatorFilter = null) => {
    let endpoint = '/dashboard/stats';
    if (initiatorFilter && initiatorFilter !== 'all') { // 'all' é tratado como sem filtro no backend (None)
        endpoint += `?initiator_filter=${initiatorFilter}`;
    }
    return request(endpoint);
};
console.log('api.js: Função getDashboardStats exportada.');
export const getDashboardFunnel = (initiator = null) => {
    let endpoint = '/dashboard/funnel';
    if (initiator && initiator !== 'all') { // 'all' é tratado como sem filtro no backend (None)
        endpoint += `?initiator=${initiator}`;
    }
    return request(endpoint);
};
console.log('api.js: Função getDashboardFunnel exportada.');
export const getDashboardAnalytics = (initiator = null) => {
    let endpoint = '/dashboard/analytics';
    if (initiator && initiator !== 'all') {
        endpoint += `?initiator=${initiator}`;
    }
    return request(endpoint);
};
console.log('api.js: Função getDashboardAnalytics exportada.');
export const clearAllHistory = () => request('/dashboard/clear-history', 'POST');
console.log('api.js: Função clearAllHistory exportada.');


// Prospects
export const addProspects = (numbersWithNames) => request('/prospect', 'POST', numbersWithNames, 'text/csv');
console.log('api.js: Função addProspects exportada.');
export const getProspectsList = (params) => {
    let endpoint = '/prospects';
    if (params && Object.keys(params).length > 0) {
        const queryString = new URLSearchParams(params).toString();
        if (queryString) {
            endpoint += `?${queryString}`;
        }
    }
    return request(endpoint);
};
console.log('api.js: Função getProspectsList exportada.');
export const getProspectHistory = (jid) => request(`/prospects/${jid}/history`);
console.log('api.js: Função getProspectHistory exportada.');
export const toggleProspectLLMPause = (jid, llm_paused) => request(`/prospects/${jid}/toggle-llm-pause`, 'POST', { llm_paused });
console.log('api.js: Função toggleProspectLLMPause exportada.');
export const getProspectProfilePicture = (jid) => request(`/prospects/${jid}/profile-picture`);
console.log('api.js: Função getProspectProfilePicture exportada.');

// Queue
export const getQueueStatus = () => request('/queue/status');
console.log('api.js: Função getQueueStatus exportada.');
export const pauseQueue = () => request('/queue/pause', 'POST');
console.log('api.js: Função pauseQueue exportada.');
export const resumeQueue = () => request('/queue/resume', 'POST');
console.log('api.js: Função resumeQueue exportada.');
export const clearQueue = () => request('/queue/clear', 'POST');
console.log('api.js: Função clearQueue exportada.');

// Configurações
export const getProspectingConfig = () => request('/config/prospecting');
console.log('api.js: Função getProspectingConfig exportada.');
export const setProspectingConfig = (config) => request('/config/prospecting', 'POST', config);
console.log('api.js: Função setProspectingConfig exportada.');

export const getSalesFlowConfig = () => request('/config/sales-flow');
console.log('api.js: Função getSalesFlowConfig exportada.');

export const setSalesFlowConfig = (stagesJson, files) => {
    console.log('api.js: setSalesFlowConfig chamada com stagesJson e files.');
    const formData = new FormData();
    formData.append('stages_json', stagesJson);
    if (files && files.length > 0) {
        files.forEach(file => {
            formData.append('files', file); 
            console.log(`api.js: Arquivo ${file.name} adicionado ao FormData.`);
        });
    }
    return request('/config/sales-flow', 'POST', formData, true); 
};
console.log('api.js: Função setSalesFlowConfig exportada.');

export const generateSalesFlowTemplate = (aiFunnelTips = '') => request('/sales-flow/generate-template', 'POST', { ai_funnel_tips: aiFunnelTips });
console.log('api.js: Função generateSalesFlowTemplate exportada.');

export const getEvolutionConfig = () => request('/config/evolution');
console.log('api.js: Função getEvolutionConfig exportada.');
export const setEvolutionConfig = (config) => request('/config/evolution', 'POST', config);
console.log('api.js: Função setEvolutionConfig exportada.');

export const getFollowUpConfig = () => request('/config/follow-up');
console.log('api.js: Função getFollowUpConfig exportada.');
export const setFollowUpConfig = (config) => request('/config/follow-up', 'POST', config);
console.log('api.js: Função setFollowUpConfig exportada.');

export const getLLMConfig = () => request('/config/llm');
console.log('api.js: Função getLLMConfig exportada.');
export const setLLMConfig = (config) => request('/config/llm', 'POST', config);
console.log('api.js: Função setLLMConfig exportada.');

export const getProductContext = () => request('/config/product-context');
console.log('api.js: Função getProductContext exportada.');
export const setProductContext = (payload) => request('/config/product-context', 'POST', payload);
console.log('api.js: Função setProductContext exportada.');

export const getSystemPrompt = () => request('/config/system-prompt');
console.log('api.js: Função getSystemPrompt exportada.');
export const setSystemPrompt = (system_prompt) => request('/config/system-prompt', 'POST', { system_prompt });
console.log('api.js: Função setSystemPrompt exportada.');

// Status
export const getAppStatus = () => request('/status');
console.log('api.js: Função getAppStatus exportada.');

// Wallet API
export const getWalletBalance = () => request('/wallet/balance');
console.log('api.js: Função getWalletBalance exportada.');
export const getWalletHistory = (params) => {
    let endpoint = '/wallet/history';
    if (params && Object.keys(params).length > 0) {
        const queryString = new URLSearchParams(params).toString();
        if (queryString) {
            endpoint += `?${queryString}`;
        }
    }
    return request(endpoint);
};
console.log('api.js: Função getWalletHistory exportada.');
export const initiateAddCredit = (amount) => request('/wallet/add-credit/initiate', 'POST', { amount }); // payment_method removido por enquanto
console.log('api.js: Função initiateAddCredit exportada.');


// Google Calendar API
export const getGoogleCalendarStatus = () => request('/calendar/status');
console.log('api.js: Função getGoogleCalendarStatus exportada.');

export const disconnectGoogleCalendar = () => request('/calendar/disconnect', 'POST');
console.log('api.js: Função disconnectGoogleCalendar exportada.');

export const getGoogleCalendarAvailability = () => request('/calendar/availability');
console.log('api.js: Função getGoogleCalendarAvailability exportada.');

export const setGoogleCalendarAvailability = (availability) => request('/calendar/availability', 'POST', availability);
console.log('api.js: Função setGoogleCalendarAvailability exportada.');

export const scheduleGoogleCalendarMeeting = (meetingDetails) => request('/calendar/schedule_meeting', 'POST', meetingDetails);
console.log('api.js: Função scheduleGoogleCalendarMeeting exportada.');

// A rota de autenticação do Google Calendar é um GET que redireciona,
// então o frontend simplesmente fará um window.location.href para ela.
// Ex: window.location.href = '/api/auth/google/calendar'; // Corrigido
// Não precisa de uma função `request` específica aqui, mas a URL base é útil.
export const GOOGLE_CALENDAR_AUTH_URL = `/api/auth/google/calendar`; // Corrigido
console.log(`api.js: GOOGLE_CALENDAR_AUTH_URL definida como ${GOOGLE_CALENDAR_AUTH_URL}`);


export const getFirstMessageConfig = () => request('/config/first-message');
console.log('api.js: Função getFirstMessageConfig exportada.');

export const setFirstMessageConfig = (config) => request('/config/first-message', 'POST', config);
console.log('api.js: Função setFirstMessageConfig exportada.');

export const getAiQueueOnlyStatus = () => request('/dashboard/ai-queue-only');
console.log('api.js: Função getAiQueueOnlyStatus exportada.');

export const toggleAiQueueOnly = (enable) => request('/dashboard/ai-queue-only', 'POST', { enable });
console.log('api.js: Função toggleAiQueueOnly exportada.');

// Tags
export const getTagDefinitions = () => request('/tags/definitions');
console.log('api.js: Função getTagDefinitions exportada.');

// Leads
export const getLeadsList = (params = {}) => {
    const queryParams = new URLSearchParams();
    if (params.status) queryParams.append('status', params.status);
    if (params.stage) queryParams.append('stage', params.stage);
    if (params.tag) queryParams.append('tag', params.tag);
    if (params.search) queryParams.append('search', params.search);
    if (params.funnel_id) queryParams.append('funnel_id', params.funnel_id);
    if (params.initiator) queryParams.append('initiator', params.initiator);
    if (params.page) queryParams.append('page', params.page);
    if (params.limit) queryParams.append('limit', params.limit);
    const queryString = queryParams.toString();
    return request(`/leads${queryString ? '?' + queryString : ''}`);
};
console.log('api.js: Função getLeadsList exportada.');

export const getLeadsStats = () => request('/leads/stats');
console.log('api.js: Função getLeadsStats exportada.');

// Backup and Restore
export const exportAllConfigs = async () => {
    const url = `${API_BASE_URL}/config/export`;
    const token = localStorage.getItem('innovaFluxoAuthToken');
    const headers = {};
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    try {
        const response = await fetch(url, { headers });
        if (!response.ok) {
            if (response.status === 401 && token) {
                console.log('api.js: Recebido erro 401 ao exportar configurações. Token expirado. Deslogando...');
                localStorage.removeItem('innovaFluxoAuthToken');
                const feedbackContainer = document.getElementById('global-feedback-container');
                if (feedbackContainer) {
                    showFeedback(feedbackContainer, 'Sua sessão expirou. Por favor, faça login novamente.', 'error');
                }
                setTimeout(() => {
                    window.location.reload();
                }, 3000);
                return;
            }
            const errorData = await response.json();
            throw new Error(errorData.detail || `Erro ${response.status} ao exportar configurações.`);
        }
        
        const blob = await response.blob();
        const contentDisposition = response.headers.get('content-disposition');
        let filename = 'backup.json';
        if (contentDisposition) {
            const filenameMatch = contentDisposition.match(/filename="?(.+)"?/);
            if (filenameMatch && filenameMatch.length > 1) {
                filename = filenameMatch[1];
            }
        }
        
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(downloadUrl);
        return { success: true, message: 'Download do backup iniciado.' };
    } catch (error) {
        console.error('api.js: Erro ao exportar configurações:', error);
        throw error;
    }
};
console.log('api.js: Função exportAllConfigs exportada.');

export const importAllConfigs = (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return request('/config/import', 'POST', formData, true); // isFormData = true
};
console.log('api.js: Função importAllConfigs exportada.');

// Insufficient Context Notification
export const getInsufficientContextNotificationConfig = () => request('/config/insufficient-context-notification');
console.log('api.js: Função getInsufficientContextNotificationConfig exportada.');

export const setInsufficientContextNotificationConfig = (config) => request('/config/insufficient-context-notification', 'POST', config);
console.log('api.js: Função setInsufficientContextNotificationConfig exportada.');

// Stage Change Notification
export const getStageChangeNotificationConfig = () => request('/config/stage-change-notification');
console.log('api.js: Função getStageChangeNotificationConfig exportada.');

export const setStageChangeNotificationConfig = (config) => request('/config/stage-change-notification', 'POST', config);
console.log('api.js: Função setStageChangeNotificationConfig exportada.');

// ============ Appointments / Confirmações de Agendamento ============
export const getAppointmentsList = (params = {}) => {
    const queryParams = new URLSearchParams();
    if (params.status) queryParams.append('status', params.status);
    if (params.start_date) queryParams.append('start_date', params.start_date);
    if (params.end_date) queryParams.append('end_date', params.end_date);
    if (params.prospect_jid) queryParams.append('prospect_jid', params.prospect_jid);
    if (params.page) queryParams.append('page', params.page);
    if (params.limit) queryParams.append('limit', params.limit);
    const queryString = queryParams.toString();
    return request(`/appointments${queryString ? '?' + queryString : ''}`);
};
console.log('api.js: Função getAppointmentsList exportada.');

export const getUpcomingAppointments = (days = 7) => request(`/appointments/upcoming?days=${days}`);
console.log('api.js: Função getUpcomingAppointments exportada.');

export const getAppointmentsStats = () => request('/appointments/stats');
console.log('api.js: Função getAppointmentsStats exportada.');

export const getAppointmentById = (id) => request(`/appointments/${id}`);
console.log('api.js: Função getAppointmentById exportada.');

export const updateAppointmentStatus = (id, status) => request(`/appointments/${id}/status`, 'PATCH', { status });
console.log('api.js: Função updateAppointmentStatus exportada.');

export const recordPatientResponse = (id, confirmed, responseText = null) =>
    request(`/appointments/${id}/patient-response`, 'POST', { confirmed, response_text: responseText });
console.log('api.js: Função recordPatientResponse exportada.');

export const getConfirmationConfig = () => request('/appointments/config/confirmations');
console.log('api.js: Função getConfirmationConfig exportada.');

export const saveConfirmationConfig = (config) => request('/appointments/config/confirmations', 'POST', config);
console.log('api.js: Função saveConfirmationConfig exportada.');

export const getSchedulerStatus = () => request('/appointments/scheduler/status');
console.log('api.js: Função getSchedulerStatus exportada.');

export const pauseScheduler = () => request('/appointments/scheduler/pause', 'POST');
console.log('api.js: Função pauseScheduler exportada.');

export const resumeScheduler = () => request('/appointments/scheduler/resume', 'POST');
console.log('api.js: Função resumeScheduler exportada.');

export const triggerManualCheck = () => request('/appointments/scheduler/trigger', 'POST');
console.log('api.js: Função triggerManualCheck exportada.');

export const sendManualConfirmation = (appointmentId, confirmationType) =>
    request('/appointments/send-confirmation', 'POST', { appointment_id: appointmentId, confirmation_type: confirmationType });
console.log('api.js: Função sendManualConfirmation exportada.');


// ============ Professionals / Profissionais ============
export const getProfessionals = (params = {}) => {
    const queryParams = new URLSearchParams();
    if (params.specialty) queryParams.append('specialty', params.specialty);
    if (params.room_name) queryParams.append('room_name', params.room_name);
    if (params.is_active !== null && params.is_active !== undefined) queryParams.append('is_active', params.is_active);
    if (params.accepts_new_patients !== null && params.accepts_new_patients !== undefined) queryParams.append('accepts_new_patients', params.accepts_new_patients);
    if (params.limit) queryParams.append('limit', params.limit);
    if (params.offset) queryParams.append('offset', params.offset);
    const queryString = queryParams.toString();
    return request(`/professionals${queryString ? '?' + queryString : ''}`);
};
console.log('api.js: Função getProfessionals exportada.');

export const getProfessionalById = (id) => request(`/professionals/${id}`);
console.log('api.js: Função getProfessionalById exportada.');

export const createProfessional = (data) => request('/professionals', 'POST', data);
console.log('api.js: Função createProfessional exportada.');

export const updateProfessional = (id, data) => request(`/professionals/${id}`, 'PUT', data);
console.log('api.js: Função updateProfessional exportada.');

export const deleteProfessional = (id) => request(`/professionals/${id}`, 'DELETE');
console.log('api.js: Função deleteProfessional exportada.');

export const getProfessionalsStats = () => request('/professionals/stats');
console.log('api.js: Função getProfessionalsStats exportada.');

export const getSpecialties = () => request('/professionals/specialties');
console.log('api.js: Função getSpecialties exportada.');

export const getRooms = () => request('/professionals/rooms');
console.log('api.js: Função getRooms exportada.');

export const getProfessionalAvailability = (professionalId, date) =>
    request(`/professionals/${professionalId}/availability?date=${date}`);
console.log('api.js: Função getProfessionalAvailability exportada.');

export const getProfessionalServices = (professionalId, activeOnly = true) =>
    request(`/professionals/${professionalId}/services?active_only=${activeOnly}`);
console.log('api.js: Função getProfessionalServices exportada.');

export const createService = (data) => request('/professionals/services', 'POST', data);
console.log('api.js: Função createService exportada.');

export const getScheduleBlocks = (professionalId, startDate, endDate) =>
    request(`/professionals/${professionalId}/blocks?start_date=${startDate}&end_date=${endDate}`);
console.log('api.js: Função getScheduleBlocks exportada.');

export const createScheduleBlock = (data) => request('/professionals/blocks', 'POST', data);
console.log('api.js: Função createScheduleBlock exportada.');

export const deleteScheduleBlock = (blockId) => request(`/professionals/blocks/${blockId}`, 'DELETE');
console.log('api.js: Função deleteScheduleBlock exportada.');

// ========== Professional Google Calendar API ==========
export const getProfessionalCalendarStatus = (professionalId) =>
    request(`/professionals/${professionalId}/calendar/status`);
console.log('api.js: Função getProfessionalCalendarStatus exportada.');

export const disconnectProfessionalCalendar = (professionalId) =>
    request(`/professionals/${professionalId}/calendar/disconnect`, 'POST');
console.log('api.js: Função disconnectProfessionalCalendar exportada.');

export const getConnectedProfessionals = () => request('/professionals/calendar/connected');
console.log('api.js: Função getConnectedProfessionals exportada.');

// Nota: Para conectar o Google Calendar, usa-se redirecionamento direto para:
// /api/professionals/{id}/calendar/auth
// Essa rota redireciona para o OAuth do Google


// ============ Sales Funnels (Multiple Funnels) API ============
export const getFunnelsList = (includeInactive = false) =>
    request(`/config/funnels${includeInactive ? '?include_inactive=true' : ''}`);
console.log('api.js: Função getFunnelsList exportada.');

export const getFunnel = (funnelId) => request(`/config/funnels/${funnelId}`);
console.log('api.js: Função getFunnel exportada.');

export const createFunnel = (data) => request('/config/funnels', 'POST', data);
console.log('api.js: Função createFunnel exportada.');

export const updateFunnel = (funnelId, data) => request(`/config/funnels/${funnelId}`, 'PUT', data);
console.log('api.js: Função updateFunnel exportada.');

export const deleteFunnel = (funnelId) => request(`/config/funnels/${funnelId}`, 'DELETE');
console.log('api.js: Função deleteFunnel exportada.');

export const setDefaultFunnel = (funnelId) => request(`/config/funnels/${funnelId}/set-default`, 'POST');
console.log('api.js: Função setDefaultFunnel exportada.');

export const getDefaultFunnel = () => request('/config/funnels/default/current');
console.log('api.js: Função getDefaultFunnel exportada.');

export const migrateLegacyFunnel = () => request('/config/funnels/migrate-legacy', 'POST');
console.log('api.js: Função migrateLegacyFunnel exportada.');

// Update prospect's funnel
export const updateProspectFunnel = (jid, funnelId, resetStage = true, targetStage = null) => {
    const payload = {
        funnel_id: funnelId,
        reset_stage: resetStage
    };
    if (targetStage) {
        payload.target_stage = targetStage;
    }
    return request(`/prospects/${jid}/funnel`, 'PATCH', payload);
};
console.log('api.js: Função updateProspectFunnel exportada.');


console.log('api.js: Módulo carregado e todas as funções de API exportadas.');
