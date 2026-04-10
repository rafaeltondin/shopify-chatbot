// static/js/router.js
import { loadDashboardPage } from './pages/dashboard.js';
import { loadAddContactsPage } from './pages/addContacts.js';
import { loadManageProspectsPage } from './pages/manageProspects.js';
import { loadSalesFlowConfigPage } from './pages/salesFlowConfig.js';
import { loadWalletPage } from './pages/wallet.js';
import settingsPage from './pages/settings.js';
import { initTagsConfigPage } from './pages/tagsConfig.js';
import { initAutomationFlowsPage } from './pages/automationFlows.js';
import { loadLeadsPage } from './pages/leads.js';
import { replaceFeatherIcons } from './utils.js';

const contentArea = document.getElementById('content-area');
const sidebarNavLinks = document.querySelectorAll('.sidebar-nav .nav-link');
const initialLoadingSpinner = document.getElementById('initial-loading-spinner');

// Sistema de controle de carregamento para evitar condições de corrida
let currentPageController = null;
let hashChangeTimeout = null;

const routes = {
    '#dashboard': loadDashboardPage,
    '#add-contacts': loadAddContactsPage,
    '#manage-prospects': loadManageProspectsPage,
    '#sales-flow': loadSalesFlowConfigPage,
    '#wallet': loadWalletPage,
    '#settings': async (container, params) => {
        container.innerHTML = settingsPage.render();
        await settingsPage.after_render(container, params);
    },
    '#tags-config': initTagsConfigPage,
    '#automation-flows': initAutomationFlowsPage,
    '#leads': loadLeadsPage,
    // Rota padrão
    '': loadDashboardPage,
};

async function loadPage(path) {
    const [cleanPath, queryString] = path.split('?');
    const routePath = cleanPath || '#dashboard';
    const params = new URLSearchParams(queryString);

    console.log(`router.js: Tentando carregar página. Path original: ${path}, Rota: ${routePath}, Params: ${params}`);
    
    // Cancelar carregamento anterior se ainda estiver em progresso
    if (currentPageController && !currentPageController.signal.aborted) {
        console.log(`router.js: Cancelando carregamento anterior para carregar '${routePath}'.`);
        currentPageController.abort();
    }

    // Criar novo controller para esta página
    currentPageController = new AbortController();
    const currentSignal = currentPageController.signal;
    
    contentArea.classList.add('content-loading'); 
    initialLoadingSpinner.style.display = 'flex'; 

    sidebarNavLinks.forEach(link => {
        link.classList.remove('active');
        if (link.getAttribute('href') === routePath) {
            link.classList.add('active');
        }
    });
    
    if (!document.querySelector('.sidebar-nav .nav-link.active') && (routePath === '' || routePath === '#dashboard')) {
        const dashboardLink = document.querySelector('.sidebar-nav .nav-link[data-page="dashboard"]');
        if (dashboardLink) dashboardLink.classList.add('active');
    }

    const handler = routes[routePath] || routes['']; 
    try {
        // Verificar se foi cancelado antes de prosseguir
        if (currentSignal.aborted) {
            console.log(`router.js: Carregamento de '${routePath}' foi cancelado.`);
            return;
        }

        // Limpeza mais robusta do contentArea
        while (contentArea.firstChild) {
            contentArea.removeChild(contentArea.firstChild);
        }
        console.log(`router.js: contentArea limpo antes de carregar '${routePath}'.`);
        
        // Verificar novamente se foi cancelado após limpeza
        if (currentSignal.aborted) {
            console.log(`router.js: Carregamento de '${routePath}' foi cancelado após limpeza.`);
            return;
        }
        
        await handler(contentArea, params); // Passa os parâmetros para o handler
        
        // Verificar se ainda é a página atual após carregamento
        if (currentSignal.aborted) {
            console.log(`router.js: Carregamento de '${routePath}' foi cancelado após handler.`);
            return;
        }
        
        replaceFeatherIcons(); 
        console.log(`router.js: Página '${routePath}' carregada com sucesso.`);
    } catch (error) {
        // Só mostrar erro se não foi cancelado
        if (!currentSignal.aborted) {
            console.error(`router.js: Erro ao carregar a página '${routePath}':`, error);
            contentArea.innerHTML = `<div class="error-message">Erro ao carregar a página. Por favor, tente novamente.</div>`;
        }
    } finally {
        // Só atualizar UI se não foi cancelado
        if (!currentSignal.aborted) {
            contentArea.classList.remove('content-loading'); 
            initialLoadingSpinner.style.display = 'none'; 
            
            const sidebar = document.getElementById('sidebar');
            const mobileMenuOverlay = document.getElementById('mobile-menu-overlay');
            const mobileMenuToggle = document.getElementById('mobile-menu-toggle');
            if (sidebar.classList.contains('is-open')) {
                sidebar.classList.remove('is-open');
                mobileMenuOverlay.classList.remove('is-visible');
                document.body.classList.remove('modal-open');
                mobileMenuToggle.setAttribute('aria-expanded', false);
            }
        }
    }
}

function handleHashChange() {
    // Throttle para evitar múltiplas chamadas rápidas
    if (hashChangeTimeout) {
        clearTimeout(hashChangeTimeout);
    }
    
    hashChangeTimeout = setTimeout(() => {
        const path = window.location.hash || '#dashboard'; 
        loadPage(path);
    }, 50); // Delay de 50ms para agrupar mudanças rápidas
}

export function initRouter() {
    console.log('router.js: Inicializando roteador...');
    window.addEventListener('hashchange', handleHashChange);
    handleHashChange(); 
    console.log('router.js: Roteador inicializado e listener de hashchange adicionado.');
}
