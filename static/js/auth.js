// static/js/auth.js
import { login as apiLogin, getAppStatus } from './api.js'; // Adicionar getAppStatus
import { showFeedback, clearFeedback, setLoadingState, hideModal } from './utils.js';
import { initRouter } from './router.js'; // Para recarregar a página após login

const LOGIN_TOKEN_KEY = 'innovaFluxoAuthToken'; // Chave para armazenar o token (se usarmos um)
const loginForm = document.getElementById('login-form');
const loginFeedback = document.getElementById('login-feedback');
const loginSubmitBtn = loginForm ? loginForm.querySelector('button[type="submit"]') : null;

/**
 * Verifica se o usuário está autenticado.
 * Por enquanto, apenas verifica se o modal de login está visível.
 * Em uma implementação real, verificaria um token JWT ou sessão.
 * @returns {boolean} True se autenticado, false caso contrário.
 */
export async function checkAuthStatus() {
    // Por enquanto, o login é apenas um "portão". Se o modal não está visível, consideramos autenticado.
    // Em um sistema real, você faria uma requisição para validar um token ou sessão.
    const token = localStorage.getItem(LOGIN_TOKEN_KEY);
    if (token) {
        // Poderíamos fazer uma requisição para /status ou /dashboard/stats
        // para verificar se o token ainda é válido no backend.
        // Por simplicidade, para este briefing, a presença do token é suficiente.
        console.log('auth.js: Token de autenticação encontrado.');
        return true;
    }
    console.log('auth.js: Nenhum token de autenticação encontrado.');
    return false;
}

/**
 * Configura os listeners de evento para o formulário de login.
 */
export function setupAuth() {
    console.log('auth.js: Configurando autenticação...');
    if (loginForm) {
        loginForm.addEventListener('submit', handleLoginSubmit);
        console.log('auth.js: Listener de submit para formulário de login adicionado.');
    } else {
        console.warn('auth.js: Formulário de login (#login-form) não encontrado.');
    }
}

/**
 * Lida com o envio do formulário de login.
 * @param {Event} event O evento de submit.
 */
async function handleLoginSubmit(event) {
    event.preventDefault();
    console.log('auth.js: Formulário de login submetido.');
    clearFeedback(loginFeedback);
    setLoadingState(loginSubmitBtn, true);

    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;

    try {
        const response = await apiLogin(username, password); // apiLogin agora retorna { access_token: "...", token_type: "bearer" }
        if (response.access_token) {
            console.log('auth.js: Login bem-sucedido. Token recebido:', response.access_token);
            localStorage.setItem(LOGIN_TOKEN_KEY, response.access_token); 
            // Opcional: mostrar mensagem de sucesso do backend se houver, ou uma padrão.
            // A API de login agora retorna diretamente o Token, não um objeto com 'success' e 'message'.
            showFeedback(loginFeedback, 'Login realizado com sucesso!', 'success');
            hideModal('login-modal');
            // A página será recarregada ou o conteúdo atualizado pelo router/app.js
            // Se o initRouter() recarregar a página, o checkAuthStatus cuidará do resto.
            // Se não houver recarregamento completo, pode ser necessário forçar uma atualização do estado da UI.
            initRouter(); 
        } else {
            // A API agora levanta uma HTTPException que é capturada no catch.
            // Este else pode não ser alcançado se a API sempre lançar erro em falha.
            // Mas, por segurança, mantemos uma mensagem genérica.
            console.warn('auth.js: Login falhou (token não recebido).');
            showFeedback(loginFeedback, response.detail || 'Usuário ou senha inválidos.', 'error');
        }
    } catch (error) {
        console.error('auth.js: Erro durante o login:', error);
        showFeedback(loginFeedback, error.message || 'Erro ao conectar com o servidor de autenticação.', 'error');
    } finally {
        setLoadingState(loginSubmitBtn, false);
        console.log('auth.js: Processo de login finalizado.');
    }
}

/**
 * Função para simular logout (se necessário no futuro).
 */
export function logout() {
    console.log('auth.js: Realizando logout...');
    localStorage.removeItem(LOGIN_TOKEN_KEY);
    // Redirecionar para a página de login ou recarregar a aplicação
    window.location.hash = ''; // Volta para a rota padrão
    window.location.reload(); // Recarrega a página para exibir o modal de login
}
