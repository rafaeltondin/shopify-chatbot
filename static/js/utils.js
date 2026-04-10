// static/js/utils.js

// =============================================================================
// TOAST NOTIFICATION SYSTEM
// =============================================================================

let toastContainer = null;

/**
 * Cria o container de toasts se não existir
 */
function ensureToastContainer() {
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        toastContainer.className = 'toast-container';
        document.body.appendChild(toastContainer);
    }
    return toastContainer;
}

/**
 * Exibe uma notificação toast no canto superior direito.
 * @param {string} message A mensagem do toast.
 * @param {'success'|'error'|'warning'|'info'} type O tipo do toast.
 * @param {number} [duration=4000] Duração em ms antes de desaparecer.
 */
export function showToast(message, type = 'info', duration = 4000) {
    const container = ensureToastContainer();

    // Ícones por tipo
    const icons = {
        success: 'check-circle',
        error: 'x-circle',
        warning: 'alert-triangle',
        info: 'info'
    };

    // Criar o toast
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <div class="toast-icon">
            <i data-feather="${icons[type] || 'info'}"></i>
        </div>
        <div class="toast-content">
            <span class="toast-message">${message}</span>
        </div>
        <button class="toast-close" aria-label="Fechar">
            <i data-feather="x"></i>
        </button>
    `;

    // Botão de fechar
    const closeBtn = toast.querySelector('.toast-close');
    closeBtn.addEventListener('click', () => removeToast(toast));

    // Adicionar ao container
    container.appendChild(toast);

    // Substituir ícones Feather
    if (typeof feather !== 'undefined') {
        feather.replace();
    }

    // Animar entrada
    requestAnimationFrame(() => {
        toast.classList.add('toast-visible');
    });

    // Auto-remover após duração
    if (duration > 0) {
        setTimeout(() => removeToast(toast), duration);
    }

    return toast;
}

/**
 * Remove um toast com animação
 */
function removeToast(toast) {
    if (!toast || !toast.parentNode) return;

    toast.classList.remove('toast-visible');
    toast.classList.add('toast-hiding');

    setTimeout(() => {
        if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
        }
    }, 300);
}

/**
 * Remove todos os toasts
 */
export function clearAllToasts() {
    const container = document.getElementById('toast-container');
    if (container) {
        container.innerHTML = '';
    }
}

// =============================================================================
// MODAL FUNCTIONS
// =============================================================================

/**
 * Exibe um modal.
 * @param {string} modalId O ID do modal a ser exibido.
 */
export function showModal(modalId) {
    console.log(`utils.js: Exibindo modal: ${modalId}`);
    const modal = document.getElementById(modalId);
    const backdrop = document.getElementById(`${modalId}-backdrop`);
    if (modal && backdrop) {
        modal.classList.add('is-visible');
        modal.setAttribute('aria-hidden', 'false');
        backdrop.classList.add('is-visible');
        backdrop.setAttribute('aria-hidden', 'false');
        document.body.classList.add('modal-open'); // Previne scroll do body
        console.log(`utils.js: Modal ${modalId} exibido.`);
    } else {
        console.warn(`utils.js: Modal ou backdrop não encontrado para ID: ${modalId}`);
    }
}

/**
 * Esconde um modal.
 * @param {string} modalId O ID do modal a ser escondido.
 */
export function hideModal(modalId) {
    console.log(`utils.js: Escondendo modal: ${modalId}`);
    const modal = document.getElementById(modalId);
    const backdrop = document.getElementById(`${modalId}-backdrop`);
    if (modal && backdrop) {
        modal.classList.remove('is-visible');
        modal.setAttribute('aria-hidden', 'true');
        backdrop.classList.remove('is-visible');
        backdrop.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('modal-open'); // Restaura scroll do body
        console.log(`utils.js: Modal ${modalId} escondido.`);
    } else {
        console.warn(`utils.js: Modal ou backdrop não encontrado para ID: ${modalId}`);
    }
}

/**
 * Configura Enter para salvar em um modal.
 * @param {string} modalId O ID do modal.
 * @param {Function} saveCallback Função a ser chamada ao pressionar Enter.
 */
export function setupModalEnterToSave(modalId, saveCallback) {
    const modal = document.getElementById(modalId);
    if (!modal) {
        console.warn(`utils.js: Modal não encontrado para ID: ${modalId}`);
        return;
    }

    // Remover listener anterior se existir
    if (modal._enterHandler) {
        modal.removeEventListener('keydown', modal._enterHandler);
    }

    // Criar novo handler
    modal._enterHandler = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            // Não disparar se estiver em textarea ou select
            if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

            e.preventDefault();
            console.log(`utils.js: Enter pressionado no modal ${modalId}, executando save.`);
            if (typeof saveCallback === 'function') {
                saveCallback();
            }
        }
    };

    modal.addEventListener('keydown', modal._enterHandler);
    console.log(`utils.js: Enter para salvar configurado no modal ${modalId}.`);
}

/**
 * Configura Enter global para todos modais com botão de salvar.
 * Deve ser chamada após o DOM estar carregado.
 */
export function setupGlobalModalEnterToSave() {
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            // Verificar se estamos em um modal visível
            const visibleModal = document.querySelector('.modal.is-visible, .modal.visible');
            if (!visibleModal) return;

            // Não disparar se estiver em textarea ou select
            if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

            // Encontrar botão de salvar no modal
            const saveBtn = visibleModal.querySelector(
                '.modal-footer .btn-primary, ' +
                'button[id*="save"], ' +
                'button[id*="confirm"], ' +
                '.btn-primary[type="submit"]'
            );

            if (saveBtn && !saveBtn.disabled) {
                e.preventDefault();
                console.log('utils.js: Enter global - clicando no botão de salvar do modal.');
                saveBtn.click();
            }
        }
    });
    console.log('utils.js: Enter global para modais configurado.');
}

/**
 * Exibe uma mensagem de feedback (sucesso, erro, aviso, info).
 * @param {HTMLElement} containerElement O elemento onde a mensagem será exibida.
 * @param {string} message O texto da mensagem.
 * @param {'success'|'error'|'warning'|'info'} type O tipo da mensagem.
 * @param {Object} [details] - Detalhes adicionais, como um link.
 * @param {string} [details.linkUrl] - URL para o link.
 * @param {string} [details.linkText] - Texto para o link.
 */
export function showFeedback(containerElement, message, type, details = {}) {
    console.log(`utils.js: Exibindo feedback (${type}): ${message}`, details);
    if (!containerElement) {
        console.error('utils.js: Elemento container para feedback não fornecido.');
        return;
    }
    containerElement.innerHTML = ''; // Limpa conteúdo anterior
    
    const messageSpan = document.createElement('span');
    messageSpan.textContent = message;
    containerElement.appendChild(messageSpan);

    if (details.linkUrl && details.linkText) {
        const linkElement = document.createElement('a');
        linkElement.href = details.linkUrl;
        linkElement.textContent = details.linkText;
        linkElement.target = '_blank'; // Abrir em nova aba
        linkElement.rel = 'noopener noreferrer';
        linkElement.style.marginLeft = '10px';
        linkElement.style.fontWeight = 'bold';
        linkElement.style.textDecoration = 'underline'; // Adiciona sublinhado para parecer mais com link
        containerElement.appendChild(linkElement);
        console.log(`utils.js: Link adicionado ao feedback: ${details.linkText} -> ${details.linkUrl}`);
    }

    containerElement.className = `feedback-message ${type}-message`; // Limpa classes anteriores e adiciona novas
    containerElement.style.display = 'block'; // Garante que seja visível
    containerElement.style.opacity = '1'; // Garante que seja visível
    console.log('utils.js: Feedback exibido.');
}

/**
 * Limpa uma mensagem de feedback.
 * @param {HTMLElement} containerElement O elemento onde a mensagem está sendo exibida.
 */
export function clearFeedback(containerElement) {
    console.log('utils.js: Limpando feedback.');
    if (containerElement) {
        containerElement.textContent = '';
        containerElement.className = 'feedback-message'; // Reseta classes
        containerElement.style.display = 'none'; // Esconde
        containerElement.style.opacity = '0'; // Esconde
        console.log('utils.js: Feedback limpo.');
    }
}

/**
 * Adiciona/remove a classe 'is-loading' a um botão e gerencia o estado 'disabled'.
 * @param {HTMLElement} buttonElement O botão a ser manipulado.
 * @param {boolean} isLoading Se o botão deve estar em estado de carregamento.
 */
export function setLoadingState(buttonElement, isLoading) {
    if (!buttonElement) return;
    console.log(`utils.js: Definindo estado de carregamento para botão: ${isLoading}`);
    if (isLoading) {
        buttonElement.classList.add('is-loading');
        buttonElement.disabled = true;
    } else {
        buttonElement.classList.remove('is-loading');
        buttonElement.disabled = false;
    }
}

/**
 * Substitui os ícones Feather em um elemento ou em todo o documento.
 * @param {HTMLElement} [element=document] O elemento onde os ícones devem ser substituídos.
 */
export function replaceFeatherIcons(element = document) {
    console.log('utils.js: Substituindo ícones Feather...');
    if (typeof feather !== 'undefined' && feather.replace) {
        try {
            feather.replace({ width: '1em', height: '1em', 'stroke-width': 2, class: 'feather' });
            console.log('utils.js: Ícones Feather substituídos com sucesso.');
        } catch (e) {
            console.error('utils.js: Erro ao substituir ícones Feather:', e);
        }
    } else {
        // Tentar novamente após um pequeno delay caso a biblioteca ainda esteja carregando
        console.warn('utils.js: Feather icons library não disponível, tentando novamente em 100ms...');
        setTimeout(() => {
            if (typeof feather !== 'undefined' && feather.replace) {
                try {
                    feather.replace({ width: '1em', height: '1em', 'stroke-width': 2, class: 'feather' });
                    console.log('utils.js: Ícones Feather substituídos (retry).');
                } catch (e) {
                    console.error('utils.js: Erro ao substituir ícones Feather (retry):', e);
                }
            } else {
                console.error('utils.js: Feather icons library não carregada após retry.');
            }
        }, 100);
    }
}

/**
 * Formata um timestamp ISO 8601 para uma string de data e hora legível.
 * @param {string} isoTimestamp O timestamp ISO 8601.
 * @returns {string} A data e hora formatadas.
 */
export function formatTimestamp(isoTimestamp) {
    if (!isoTimestamp) return 'N/A';
    try {
        const date = new Date(isoTimestamp);
        // Formato: DD/MM/YYYY HH:MM:SS - Timezone: America/Sao_Paulo (GMT-3)
        return date.toLocaleString('pt-BR', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            timeZone: 'America/Sao_Paulo'
        });
    } catch (e) {
        console.error('utils.js: Erro ao formatar timestamp:', isoTimestamp, e);
        return isoTimestamp; // Retorna o original em caso de erro
    }
}

/**
 * Formata um número de telefone para exibição.
 * @param {string} jid O JID (ex: 5511987654321@s.whatsapp.net).
 * @returns {string} O número formatado (ex: +55 (11) 98765-4321).
 */
export function formatJidToDisplay(jid) {
    if (!jid) return '';
    const number = jid.split('@')[0]; // Remove o "@s.whatsapp.net"
    // Remove tudo que não for dígito
    const cleaned = number.replace(/\D/g, '');

    // Aplica formatação com base no comprimento
    if (cleaned.length === 13) { // Ex: 5511987654321 (DDI + DDD + 9 + 8 dígitos)
        return `+${cleaned.substring(0, 2)} (${cleaned.substring(2, 4)}) ${cleaned.substring(4, 9)}-${cleaned.substring(9)}`;
    } else if (cleaned.length === 12) { // Ex: 551187654321 (DDI + DDD + 8 dígitos)
        return `+${cleaned.substring(0, 2)} (${cleaned.substring(2, 4)}) ${cleaned.substring(4, 8)}-${cleaned.substring(8)}`;
    } else if (cleaned.length === 11) { // Ex: 11987654321 (DDD + 9 + 8 dígitos)
        return `(${cleaned.substring(0, 2)}) ${cleaned.substring(2, 7)}-${cleaned.substring(7)}`;
    } else if (cleaned.length === 10) { // Ex: 1187654321 (DDD + 8 dígitos)
        return `(${cleaned.substring(0, 2)}) ${cleaned.substring(2, 6)}-${cleaned.substring(6)}`;
    }
    return cleaned; // Retorna o número limpo se não corresponder a um padrão conhecido
}

/**
 * Converte um objeto FormData para um objeto JSON.
 * Útil para depuração ou para enviar dados que não são arquivos.
 * @param {FormData} formData O objeto FormData.
 * @returns {Object} O objeto JSON.
 */
export function formDataToJson(formData) {
    const obj = {};
    for (const [key, value] of formData.entries()) {
        obj[key] = value;
    }
    return obj;
}

/**
 * Valida o formato HH:MM.
 * @param {string} timeString A string de tempo.
 * @returns {boolean} True se o formato for válido, false caso contrário.
 */
export function isValidTimeFormat(timeString) {
    return /^\d{2}:\d{2}$/.test(timeString);
}

/**
 * Valida se um array de weekdays contém apenas números de 0 a 6.
 * @param {Array<number>} weekdays Array de números representando os dias da semana.
 * @returns {boolean} True se válido, false caso contrário.
 */
export function isValidWeekdaysArray(weekdays) {
    if (!Array.isArray(weekdays)) return false;
    return weekdays.every(day => typeof day === 'number' && day >= 0 && day <= 6);
}

/**
 * Converte um array de números de dias da semana para nomes curtos.
 * @param {Array<number>} weekdays Array de números (0=Dom, 1=Seg, etc.).
 * @returns {string} String com nomes curtos dos dias (ex: "Seg, Ter, Qua").
 */
export function weekdaysToShortNames(weekdays) {
    const names = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];
    return weekdays.map(day => names[day]).join(', ');
}

/**
 * Converte um número de estágio para um nome legível.
 * @param {number} stageNumber O número do estágio.
 * @returns {string} O nome do estágio.
 */
export function getStageName(stageNumber) {
    switch (stageNumber) {
        case 0: return 'Novo';
        case 1: return 'Inicial';
        case 2: return 'Qualificação';
        case 3: return 'Proposta';
        case 4: return 'Fechamento';
        case 5: return 'Concluído';
        case 6: return 'Não Qualificado';
        default: return `Estágio ${stageNumber}`;
    }
}

/**
 * Converte um status para um nome legível.
 * @param {string} status O status.
 * @returns {string} O nome do status.
 */
export function getStatusName(status) {
    switch (status) {
        case 'active': return 'Ativo';
        case 'completed': return 'Concluído';
        case 'failed': return 'Falhou';
        case 'unsubscribed': return 'Descadastrado';
        case 'paused': return 'Pausado';
        case 'pending': return 'Pendente';
        case 'scheduled': return 'Agendado'; // Adicionado
        default: return status;
    }
}

/**
 * Cria um elemento HTML com atributos e filhos.
 * @param {string} tagName O nome da tag HTML.
 * @param {Object} [attributes={}] Um objeto de atributos (ex: { class: 'my-class', id: 'my-id' }).
 * @param {Array<HTMLElement|string>|HTMLElement|string} [children=[]] Um array de elementos filhos, um único elemento, ou uma string de texto.
 * @returns {HTMLElement} O elemento HTML criado.
 */
export function createElement(tagName, attributes = {}, children = []) {
    const element = document.createElement(tagName);
    for (const key in attributes) {
        if (attributes.hasOwnProperty(key)) {
            if (key === 'className') { // Para 'class' em JS
                element.className = attributes[key];
            } else if (key === 'dataset') { // Para data-attributes
                for (const dataKey in attributes[key]) {
                    element.dataset[dataKey] = attributes[key][dataKey];
                }
            } else {
                element.setAttribute(key, attributes[key]);
            }
        }
    }

    // Ensure children is always an array
    const childrenArray = Array.isArray(children) ? children : [children];

    childrenArray.forEach(child => {
        if (typeof child === 'string') {
            element.appendChild(document.createTextNode(child));
        } else if (child instanceof HTMLElement) {
            element.appendChild(child);
        }
    });
    return element;
}

/**
 * Converte um tipo de transação para um nome legível em português.
 * @param {string} transactionType O tipo da transação (ex: 'credit', 'debit').
 * @returns {string} O nome do tipo de transação em português.
 */
export function getTransactionTypeName(transactionType) {
    switch (transactionType) {
        case 'credit': return 'Crédito';
        case 'debit': return 'Débito';
        case 'bonus': return 'Bônus';
        case 'refund': return 'Reembolso';
        case 'initial': return 'Inicial';
        default: return transactionType;
    }
}

/**
 * Converte um status de transação para um nome legível em português.
 * @param {string} transactionStatus O status da transação (ex: 'completed', 'pending').
 * @returns {string} O nome do status da transação em português.
 */
export function getTransactionStatusName(transactionStatus) {
    switch (transactionStatus) {
        case 'pending': return 'Pendente';
        case 'completed': return 'Concluído';
        case 'failed': return 'Falhou';
        case 'refunded': return 'Reembolsado';
        case 'cancelled': return 'Cancelado';
        default: return transactionStatus;
    }
}

/**
 * Exibe um modal de "Sem Crédito".
 * @param {string} message A mensagem a ser exibida no popup.
 */
export function showNoCreditPopup(message) {
    console.log('utils.js: Exibindo popup de "Sem Crédito". Mensagem:', message);
    // Tenta encontrar um modal existente, senão cria um novo
    let modal = document.getElementById('no-credit-modal');
    let backdrop = document.getElementById('no-credit-modal-backdrop');

    if (!modal) {
        console.log('utils.js: Modal "no-credit-modal" não existe. Criando...');
        // Criar backdrop
        backdrop = createElement('div', { id: 'no-credit-modal-backdrop', className: 'modal-backdrop' });
        document.body.appendChild(backdrop);

        // Criar modal
        modal = createElement('div', { 
            id: 'no-credit-modal', 
            className: 'modal', 
            role: 'dialog', 
            'aria-modal': 'true', 
            'aria-labelledby': 'no-credit-title' 
        }, [
            createElement('div', { className: 'modal-content', style: 'max-width: 500px; text-align: center;' }, [
                createElement('header', { className: 'modal-header' }, [
                    createElement('h3', { id: 'no-credit-title', className: 'modal-title' }, 'Créditos Insuficientes')
                ]),
                createElement('section', { className: 'modal-body' }, [
                    createElement('i', { 'data-feather': 'alert-triangle', style: 'width: 50px; height: 50px; color: var(--color-error-500); margin-bottom: var(--space-4); display: block; margin-left: auto; margin-right: auto;' }),
                    createElement('p', { id: 'no-credit-message' }, message || 'Seus créditos acabaram. Por favor, recarregue para continuar usando o sistema.')
                ]),
                createElement('footer', { className: 'modal-footer', style: 'justify-content: center;' }, [ // Centralizar botão
                    createElement('button', { type: 'button', className: 'btn btn-primary btn-lg', id: 'recharge-credits-btn' }, [
                        createElement('i', { 'data-feather': 'credit-card', style: 'margin-right: 8px;' }),
                        'Recarregar Créditos'
                    ])
                ])
            ])
        ]);
        document.body.appendChild(modal);
        
        if (typeof feather !== 'undefined') {
            feather.replace(); // Para renderizar o ícone no novo modal
        }

        document.getElementById('recharge-credits-btn').addEventListener('click', () => {
            console.log('utils.js: Botão "Recarregar Créditos" clicado no popup de sem crédito.');
            window.location.hash = '#wallet'; // Redireciona para a página da wallet
            hideModal('no-credit-modal'); // Esconde este modal
        });
        
        // Adicionar listener para fechar o backdrop se clicar nele (opcional, mas bom UX)
        backdrop.addEventListener('click', () => {
            // Poderia ter uma lógica para não fechar se for crítico, mas para "sem crédito" é ok fechar.
            // hideModal('no-credit-modal'); 
            // Decidi não fechar ao clicar no backdrop para este modal específico, forçando o usuário a interagir com o botão.
        });

    } else {
        // Modal já existe, apenas atualiza a mensagem
        const messageElement = document.getElementById('no-credit-message');
        if (messageElement) {
            messageElement.textContent = message || 'Seus créditos acabaram. Por favor, recarregue para continuar usando o sistema.';
        }
        console.log('utils.js: Modal "no-credit-modal" já existe. Mensagem atualizada.');
    }

    // Exibir o modal e o backdrop
    modal.classList.add('is-visible');
    modal.setAttribute('aria-hidden', 'false');
    backdrop.classList.add('is-visible');
    backdrop.setAttribute('aria-hidden', 'false');
    document.body.classList.add('modal-open'); // Previne scroll do body
    console.log('utils.js: Popup de "Sem Crédito" exibido.');
}
