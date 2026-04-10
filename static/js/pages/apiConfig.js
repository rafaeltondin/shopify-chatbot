// static/js/pages/apiConfig.js
import { getEvolutionConfig, setEvolutionConfig, getLLMConfig, setLLMConfig, exportAllConfigs, importAllConfigs } from '../api.js';
import { showFeedback, clearFeedback, setLoadingState } from '../utils.js';

export async function loadAPIConfigPage(container) {
    console.log('apiConfig.js: Carregando página de Configuração de API...');
    container.innerHTML = `
        <header class="page-header">
            <h1 class="page-title"><i data-feather="zap" class="feather-title"></i> Config. API</h1>
            <p class="page-description">Configure as credenciais para a Evolution API.</p>
        </header>

        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="key" class="feather-title-sm"></i> Credenciais da Evolution API</h3>
            </div>
            <div class="card-body">
                <form id="evolution-api-config-form" class="form">
                    <div class="form-group">
                        <label for="evolution-url" class="label">URL da Evolution API:</label>
                        <input type="url" id="evolution-url" class="input" placeholder="Ex: http://localhost:8080" required>
                        <p class="form-text">A URL base da sua instância da Evolution API.</p>
                    </div>
                    <div class="form-group">
                        <label for="evolution-api-key" class="label">Chave API:</label>
                        <input type="password" id="evolution-api-key" class="input" placeholder="Deixe em branco para não alterar">
                        <p class="form-text">Sua chave API para autenticação na Evolution API. Deixe em branco para manter a chave existente.</p>
                        <p id="evolution-key-status" class="form-text"></p>
                    </div>
                    <div class="form-group">
                        <label for="evolution-instance-name" class="label">Nome da Instância:</label>
                        <input type="text" id="evolution-instance-name" class="input" placeholder="Ex: my-instance" required>
                        <p class="form-text">O nome da instância que você configurou na Evolution API.</p>
                    </div>
                    <div id="evolution-api-feedback" class="feedback-message"></div>
                    <button type="submit" class="btn btn-primary">
                        <i data-feather="save"></i> Salvar Configurações
                    </button>
                </form>
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="cpu" class="feather-title-sm"></i> Configuração do Modelo de Linguagem (LLM)</h3>
            </div>
            <div class="card-body">
                <form id="llm-config-form" class="form">
                    <div class="form-group">
                        <label for="llm-model-preference" class="label">Modelo de LLM:</label>
                        <select id="llm-model-preference" class="select" required>
                            <option value="google/gemini-flash-1.5">Google Gemini 1.5 Flash</option>
                            <option value="google/gemini-2.5-flash">Google Gemini 2.5 Flash</option>
                            <option value="google/gemini-2.5-flash-lite-preview-06-17">Google Gemini 2.5 Flash Lite (Preview)</option>
                            <option value="google/gemini-2.5-flash-preview-05-20">Google Gemini 2.5 Flash (Preview)</option>
                            <option value="anthropic/claude-3.5-sonnet">Anthropic Claude 3.5 Sonnet</option>
                            <option value="anthropic/claude-3-haiku">Anthropic Claude 3 Haiku</option>
                            <option value="anthropic/claude-3.5-haiku">Anthropic Claude 3.5 Haiku</option>
                        </select>
                        <p class="form-text">Escolha o modelo de linguagem para o agente.</p>
                    </div>
                    <div class="form-group">
                        <label for="llm-temperature" class="label">Temperatura:</label>
                        <div class="slider-container">
                            <input type="range" id="llm-temperature" class="slider" min="0" max="2" step="0.01">
                            <span id="temperature-value" class="slider-value">1.00</span>
                        </div>
                        <p class="form-text">Controle a criatividade do modelo. Valores mais baixos são mais determinísticos.</p>
                    </div>
                    <div id="llm-config-feedback" class="feedback-message"></div>
                    <button type="submit" class="btn btn-primary">
                        <i data-feather="save"></i> Salvar Configurações do LLM
                    </button>
                </form>
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i data-feather="database" class="feather-title-sm"></i> Backup e Restauração</h3>
            </div>
            <div class="card-body">
                <p class="form-text">Exporte todas as suas configurações para um arquivo JSON ou importe um backup para restaurar suas configurações.</p>
                <div class="backup-restore-controls flex gap-4 mt-4">
                    <button id="export-config-btn" class="btn btn-secondary">
                        <i data-feather="download"></i> Exportar Configurações
                    </button>
                    <input type="file" id="import-config-input" style="display: none;" accept=".json">
                    <button id="import-config-btn" class="btn btn-secondary">
                        <i data-feather="upload"></i> Importar Configurações
                    </button>
                </div>
                <div id="backup-restore-feedback" class="feedback-message mt-4"></div>
            </div>
        </div>

    `;

    // Event Listeners
    document.getElementById('evolution-api-config-form').addEventListener('submit', handleEvolutionAPIConfigSubmit);
    document.getElementById('llm-config-form').addEventListener('submit', handleLLMConfigSubmit);
    document.getElementById('llm-temperature').addEventListener('input', (e) => {
        document.getElementById('temperature-value').textContent = parseFloat(e.target.value).toFixed(2);
    });

    // Backup and Restore Listeners
    document.getElementById('export-config-btn').addEventListener('click', handleExportConfig);
    document.getElementById('import-config-btn').addEventListener('click', () => document.getElementById('import-config-input').click());
    document.getElementById('import-config-input').addEventListener('change', handleImportConfig);

    // Initial load
    await Promise.all([
        fetchEvolutionAPIConfig(),
        fetchLLMConfig()
    ]);

    console.log('apiConfig.js: Página de Configuração de API carregada.');
}

async function fetchEvolutionAPIConfig(preserveFeedback = false) {
    console.log('apiConfig.js: Buscando configuração da Evolution API...');
    const form = document.getElementById('evolution-api-config-form');
    const feedbackContainer = document.getElementById('evolution-api-feedback');
    
    if (!preserveFeedback) {
        clearFeedback(feedbackContainer);
    }

    try {
        const config = await getEvolutionConfig();
        document.getElementById('evolution-url').value = config.url || '';
        document.getElementById('evolution-instance-name').value = config.instance_name || '';
        
        const apiKeyInput = document.getElementById('evolution-api-key');
        const keyStatusElement = document.getElementById('evolution-key-status');
        
        if (config.api_key) {
            // Não preenchemos o campo de senha por segurança, mas indicamos que está salvo.
            apiKeyInput.placeholder = "Chave API salva. Preencha para alterar.";
            keyStatusElement.textContent = 'Uma chave API está configurada. Para alterá-la, insira uma nova chave.';
            keyStatusElement.className = 'form-text success-message';
        } else {
            apiKeyInput.placeholder = "Insira sua chave API aqui";
            keyStatusElement.textContent = 'Nenhuma chave API configurada.';
            keyStatusElement.className = 'form-text error-message';
        }
        console.log('apiConfig.js: Configuração da Evolution API carregada.');
    } catch (error) {
        console.error('apiConfig.js: Erro ao buscar configuração da Evolution API:', error);
        showFeedback(feedbackContainer, error.message || 'Erro ao carregar configurações da Evolution API.', 'error');
    }
}

async function handleEvolutionAPIConfigSubmit(event) {
    event.preventDefault();
    console.log('apiConfig.js: Formulário de configuração da Evolution API submetido.');
    const feedbackContainer = document.getElementById('evolution-api-feedback');
    const submitBtn = event.currentTarget.querySelector('button[type="submit"]');
    setLoadingState(submitBtn, true);
    clearFeedback(feedbackContainer);

    const url = document.getElementById('evolution-url').value.trim();
    const apiKey = document.getElementById('evolution-api-key').value.trim();
    const instanceName = document.getElementById('evolution-instance-name').value.trim();

    // Validações
    if (!url || !instanceName) {
        showFeedback(feedbackContainer, 'URL da Evolution API e Nome da Instância são obrigatórios.', 'error');
        setLoadingState(submitBtn, false);
        return;
    }
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
        showFeedback(feedbackContainer, 'A URL da Evolution API deve começar com "http://" ou "https://".', 'error');
        setLoadingState(submitBtn, false);
        return;
    }

    const configData = {
        url: url,
        api_key: apiKey, // Envia a chave apenas se preenchida
        instance_name: instanceName
    };

    try {
        const response = await setEvolutionConfig(configData);
        // Mostrar feedback do 'set' primeiro
        showFeedback(feedbackContainer, response.message, 'success');
        console.log('apiConfig.js: Configurações da Evolution API salvas com sucesso.');

        // Depois, atualizar a UI. O fetch não deve limpar o feedback de sucesso anterior.
        // Se o fetch falhar, ele DEVE mostrar seu próprio erro, que substituirá a msg de sucesso.
        await fetchEvolutionAPIConfig(true); // Passa true para preserveFeedback
    } catch (error) {
        console.error('apiConfig.js: Erro ao salvar ou recarregar configurações da Evolution API:', error);
        showFeedback(feedbackContainer, error.message || 'Erro ao salvar ou recarregar configurações.', 'error');
    } finally {
        setLoadingState(submitBtn, false);
    }
}

async function handleExportConfig(event) {
    const exportBtn = event.currentTarget;
    const feedbackContainer = document.getElementById('backup-restore-feedback');
    setLoadingState(exportBtn, true);
    clearFeedback(feedbackContainer);

    try {
        await exportAllConfigs();
        showFeedback(feedbackContainer, 'Backup gerado e download iniciado.', 'success');
    } catch (error) {
        console.error('apiConfig.js: Erro ao exportar configurações:', error);
        showFeedback(feedbackContainer, error.message || 'Falha ao exportar configurações.', 'error');
    } finally {
        setLoadingState(exportBtn, false);
    }
}

async function handleImportConfig(event) {
    const importBtn = document.getElementById('import-config-btn');
    const fileInput = event.currentTarget;
    const feedbackContainer = document.getElementById('backup-restore-feedback');
    const file = fileInput.files[0];

    if (!file) {
        return; // No file selected
    }

    if (!confirm(`Tem certeza que deseja importar o arquivo "${file.name}"? Todas as configurações atuais serão sobrescritas.`)) {
        fileInput.value = ''; // Reset file input
        return;
    }

    setLoadingState(importBtn, true);
    clearFeedback(feedbackContainer);

    try {
        const response = await importAllConfigs(file);
        showFeedback(feedbackContainer, response.message, 'success');
        // Reload the page to reflect all imported settings
        setTimeout(() => {
            window.location.reload();
        }, 2000);
    } catch (error) {
        console.error('apiConfig.js: Erro ao importar configurações:', error);
        showFeedback(feedbackContainer, error.message || 'Falha ao importar configurações.', 'error');
        setLoadingState(importBtn, false);
    } finally {
        fileInput.value = ''; // Reset file input
    }
}

async function fetchLLMConfig() {
    console.log('apiConfig.js: Buscando configuração do LLM...');
    const feedbackContainer = document.getElementById('llm-config-feedback');
    try {
        const config = await getLLMConfig();
        document.getElementById('llm-model-preference').value = config.llm_model_preference;
        const temperatureSlider = document.getElementById('llm-temperature');
        temperatureSlider.value = config.llm_temperature;
        document.getElementById('temperature-value').textContent = parseFloat(config.llm_temperature).toFixed(2);
        console.log('apiConfig.js: Configuração do LLM carregada.');
    } catch (error) {
        console.error('apiConfig.js: Erro ao buscar configuração do LLM:', error);
        showFeedback(feedbackContainer, error.message || 'Erro ao carregar configurações do LLM.', 'error');
    }
}

async function handleLLMConfigSubmit(event) {
    event.preventDefault();
    console.log('apiConfig.js: Formulário de configuração do LLM submetido.');
    const feedbackContainer = document.getElementById('llm-config-feedback');
    const submitBtn = event.currentTarget.querySelector('button[type="submit"]');
    setLoadingState(submitBtn, true);
    clearFeedback(feedbackContainer);

    const model = document.getElementById('llm-model-preference').value;
    const temperature = parseFloat(document.getElementById('llm-temperature').value);

    const configData = {
        llm_model_preference: model,
        llm_temperature: temperature
    };

    try {
        const response = await setLLMConfig(configData);
        showFeedback(feedbackContainer, response.message, 'success');
        console.log('apiConfig.js: Configurações do LLM salvas com sucesso.');
    } catch (error) {
        console.error('apiConfig.js: Erro ao salvar configurações do LLM:', error);
        showFeedback(feedbackContainer, error.message || 'Erro ao salvar configurações do LLM.', 'error');
    } finally {
        setLoadingState(submitBtn, false);
    }
}

