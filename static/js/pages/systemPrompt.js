// static/js/pages/systemPrompt.js
import { getSystemPrompt, setSystemPrompt } from '../api.js';
import { showFeedback, clearFeedback, setLoadingState } from '../utils.js';

export async function loadSystemPromptPage(container) {
    console.log('systemPrompt.js: Carregando página de Prompt do Sistema...');
    container.innerHTML = `
        <header class="page-header">
            <h1 class="page-title"><i data-feather="terminal" class="feather-title"></i> Prompt do Sistema</h1>
            <p class="page-description">Defina as instruções e o papel do Agente de IA para suas interações.</p>
        </header>

        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="code" class="feather-title-sm"></i> Prompt Principal</h3>
            </div>
            <div class="card-body">
                <form id="system-prompt-form" class="form">
                    <div class="form-group">
                        <label for="system-prompt-textarea" class="label">Prompt do Sistema:</label>
                        <textarea id="system-prompt-textarea" class="textarea llm-system-prompt-textarea" rows="15" placeholder="Você é um assistente de vendas amigável e prestativo..."></textarea>
                        <p class="form-text">Este prompt define a personalidade e as diretrizes gerais do Agente de IA.</p>
                    </div>
                    <div id="system-prompt-feedback" class="feedback-message"></div>
                    <button type="submit" class="btn btn-primary">
                        <i data-feather="save"></i> Salvar Prompt
                    </button>
                </form>
            </div>
        </div>
    `;

    // Event Listeners
    document.getElementById('system-prompt-form').addEventListener('submit', handleSystemPromptSubmit);

    // Initial load
    await fetchSystemPrompt();

    console.log('systemPrompt.js: Página de Prompt do Sistema carregada.');
}

async function fetchSystemPrompt() {
    console.log('systemPrompt.js: Buscando prompt do sistema...');
    const form = document.getElementById('system-prompt-form');
    const feedbackContainer = document.getElementById('system-prompt-feedback');
    clearFeedback(feedbackContainer);

    try {
        const config = await getSystemPrompt();
        document.getElementById('system-prompt-textarea').value = config.system_prompt || '';
        console.log('systemPrompt.js: Prompt do sistema carregado.');
    } catch (error) {
        console.error('systemPrompt.js: Erro ao buscar prompt do sistema:', error);
        showFeedback(feedbackContainer, error.message || 'Erro ao carregar prompt do sistema.', 'error');
    }
}

async function handleSystemPromptSubmit(event) {
    event.preventDefault();
    console.log('systemPrompt.js: Formulário de prompt do sistema submetido.');
    const feedbackContainer = document.getElementById('system-prompt-feedback');
    const submitBtn = event.currentTarget.querySelector('button[type="submit"]');
    setLoadingState(submitBtn, true);
    clearFeedback(feedbackContainer);

    const systemPrompt = document.getElementById('system-prompt-textarea').value;

    try {
        const response = await setSystemPrompt(systemPrompt);
        showFeedback(feedbackContainer, response.message, 'success');
        console.log('systemPrompt.js: Prompt do sistema salvo com sucesso.');
    } catch (error) {
        console.error('systemPrompt.js: Erro ao salvar prompt do sistema:', error);
        showFeedback(feedbackContainer, error.message || 'Erro ao salvar prompt do sistema.', 'error');
    } finally {
        setLoadingState(submitBtn, false);
    }
}
