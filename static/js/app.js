// static/js/app.js
// static/js/app.js
import { initRouter } from './router.js';
import { setupAuth, checkAuthStatus } from './auth.js'; // auth.js será criado para lidar com login
import { showModal, hideModal, setupGlobalModalEnterToSave } from './utils.js'; // Funções utilitárias para modais
import { replaceFeatherIcons } from './utils.js'; // Função para substituir ícones Feather

let socket = null;
let reconnectTimeout = null;
let messageQueue = [];
let lastMessageTime = 0;
const MESSAGE_THROTTLE_MS = 100; // Throttle messages to 100ms

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/api/ws`;
    
    socket = new WebSocket(url);

    socket.onopen = () => {
        console.log('WebSocket connection established.');
        // Clear any pending reconnect
        if (reconnectTimeout) {
            clearTimeout(reconnectTimeout);
            reconnectTimeout = null;
        }
    };

    socket.onmessage = (event) => {
        const now = Date.now();
        const message = JSON.parse(event.data);
        
        // Throttle messages for performance
        if (now - lastMessageTime > MESSAGE_THROTTLE_MS) {
            document.dispatchEvent(new CustomEvent('websocket-message', { detail: message }));
            lastMessageTime = now;
        } else {
            // Queue message for later
            messageQueue.push(message);
            setTimeout(() => {
                if (messageQueue.length > 0) {
                    const queuedMessage = messageQueue.shift();
                    document.dispatchEvent(new CustomEvent('websocket-message', { detail: queuedMessage }));
                }
            }, MESSAGE_THROTTLE_MS);
        }
    };

    socket.onclose = () => {
        console.log('WebSocket connection closed. Attempting to reconnect in 5 seconds...');
        reconnectTimeout = setTimeout(connectWebSocket, 5000);
    };

    socket.onerror = (error) => {
        console.error('WebSocket error:', error);
        socket.close();
    };
}

document.addEventListener('DOMContentLoaded', async () => {
    console.log('app.js: DOM totalmente carregado. Iniciando aplicação...');

    // 1. Inicializar Feather Icons com debounce para performance
    requestAnimationFrame(() => {
        replaceFeatherIcons();
        console.log('app.js: Feather icons inicializados.');
    });

    // 2. Configurar o sistema de autenticação
    setupAuth();
    console.log('app.js: Sistema de autenticação configurado.');

    // 2.1. Configurar Enter para salvar em todos os modais
    setupGlobalModalEnterToSave();
    console.log('app.js: Enter para salvar em modais configurado.');

    // 3. Verificar status de autenticação e exibir modal de login se necessário
    const isAuthenticated = await checkAuthStatus();
    if (!isAuthenticated) {
        console.log('app.js: Usuário não autenticado. Exibindo modal de login.');
        showModal('login-modal');
    } else {
        console.log('app.js: Usuário autenticado. Escondendo modal de login (se visível).');
        hideModal('login-modal');
    }

    // 4. Inicializar o roteador para gerenciar as "páginas"
    initRouter();
    console.log('app.js: Roteador inicializado.');

    // 5. Configurar o botão de menu mobile
    const mobileMenuToggle = document.getElementById('mobile-menu-toggle');
    const sidebar = document.getElementById('sidebar');
    const mobileMenuOverlay = document.getElementById('mobile-menu-overlay');

    if (mobileMenuToggle && sidebar && mobileMenuOverlay) {
        mobileMenuToggle.addEventListener('click', () => {
            // Usar requestAnimationFrame para melhor performance
            requestAnimationFrame(() => {
                sidebar.classList.toggle('is-open');
                mobileMenuOverlay.classList.toggle('is-visible');
                document.body.classList.toggle('modal-open');
                mobileMenuToggle.setAttribute('aria-expanded', sidebar.classList.contains('is-open'));
            });
        });

        mobileMenuOverlay.addEventListener('click', () => {
            requestAnimationFrame(() => {
                sidebar.classList.remove('is-open');
                mobileMenuOverlay.classList.remove('is-visible');
                document.body.classList.remove('modal-open');
                mobileMenuToggle.setAttribute('aria-expanded', false);
            });
        });

        // Adicionar listener para fechar o menu ao clicar em um link da sidebar
        sidebar.addEventListener('click', (event) => {
            // Verificar se o clique foi em um link (<a>) dentro da navegação da sidebar
            const link = event.target.closest('.sidebar-nav .nav-link');
            if (link && sidebar.classList.contains('is-open')) {
                console.log('app.js: Link da sidebar clicado com menu mobile aberto. Fechando menu.');
                sidebar.classList.remove('is-open');
                mobileMenuOverlay.classList.remove('is-visible');
                document.body.classList.remove('modal-open');
                mobileMenuToggle.setAttribute('aria-expanded', false);
                // A navegação para o href do link ocorrerá normalmente
            }
        });
    } else {
        console.warn('app.js: Elementos do menu mobile não encontrados. Verifique o HTML.');
    }

    // 6. Configurar o botão de logout
    const logoutBtn = document.getElementById('logout-btn');
    
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            try {
                // Fazer chamada para endpoint de logout
                const response = await fetch('/api/logout', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                
                if (response.ok) {
                    // Limpar dados locais
                    localStorage.removeItem('authToken');
                    localStorage.removeItem('sidebarCollapsed');
                    
                    // Fechar conexão WebSocket se existir
                    if (socket) {
                        socket.close();
                        socket = null;
                    }
                    
                    // Recarregar página para mostrar tela de login
                    window.location.reload();
                } else {
                    console.error('Erro ao fazer logout:', response.status);
                }
            } catch (error) {
                console.error('Erro ao fazer logout:', error);
                // Em caso de erro, ainda assim limpar dados locais
                localStorage.removeItem('authToken');
                window.location.reload();
            }
        });
    }

    // 7. Configurar o fechamento genérico de modais
    document.addEventListener('click', (event) => {
        // Fechar modal ao clicar no botão de fechar
        if (event.target.closest('.modal-close-btn')) {
            const modal = event.target.closest('.modal');
            if (modal) {
                console.log(`app.js: Botão de fechar clicado para modal: ${modal.id}.`);
                hideModal(modal.id);
            }
        }
        // Fechar modal ao clicar no backdrop
        if (event.target.classList.contains('modal-backdrop')) {
            const modalId = event.target.id.replace('-backdrop', '');
            console.log(`app.js: Backdrop clicado para modal: ${modalId}.`);
            hideModal(modalId);
        }
    });

    // 8. Conectar ao WebSocket
    if (isAuthenticated) {
        connectWebSocket();
    }

    console.log('app.js: Aplicação inicializada com sucesso.');
});
