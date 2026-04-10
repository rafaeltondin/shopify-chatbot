// static/js/pages/prospectingConfig.js
import { getProspectingConfig, setProspectingConfig } from '../api.js';
import { showFeedback, clearFeedback, setLoadingState, isValidTimeFormat, createElement } from '../utils.js';

export async function loadProspectingConfigPage(container) {
    console.log('prospectingConfig.js: loadProspectingConfigPage - Iniciando carregamento da página de Configuração de Prospecção...');
    if (!container) {
        console.error('prospectingConfig.js: loadProspectingConfigPage - Container não fornecido. Abortando.');
        return;
    }
    console.log('prospectingConfig.js: loadProspectingConfigPage - Container recebido:', container);

    container.innerHTML = `
        <div class="animate-fade-in">
            <header class="page-header border-b border-subtle mb-8">
                <div class="flex items-center gap-4 mb-4">
                    <div class="p-3 bg-blue-50 rounded-xl">
                        <i data-feather="clock" class="text-blue-600" style="width: 24px; height: 24px;"></i>
                    </div>
                    <div>
                        <h1 class="text-3xl font-bold text-primary mb-1">Configuração de Prospecção</h1>
                        <p class="text-secondary">Defina horários e intervalos para envio de mensagens</p>
                    </div>
                </div>
            </header>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                <!-- Time Configuration -->
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">
                            <i data-feather="calendar"></i>
                            Horários de Funcionamento
                        </h3>
                    </div>
                    <div class="card-body">
                        <form id="prospecting-config-form" class="space-y-6">
                            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <div class="form-group">
                                    <label for="start-time" class="label">
                                        <i data-feather="sunrise"></i>
                                        Horário de Início
                                    </label>
                                    <input type="time" id="start-time" class="input" required>
                                    <p class="form-text">Horário para iniciar envio de mensagens</p>
                                </div>
                                <div class="form-group">
                                    <label for="end-time" class="label">
                                        <i data-feather="sunset"></i>
                                        Horário de Fim
                                    </label>
                                    <input type="time" id="end-time" class="input" required>
                                    <p class="form-text">Horário para parar envio de mensagens</p>
                                </div>
                            </div>

                            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <div class="form-group">
                                    <label for="min-delay" class="label">
                                        <i data-feather="timer"></i>
                                        Intervalo Mínimo (seg)
                                    </label>
                                    <input type="number" id="min-delay" class="input" min="0" required>
                                    <p class="form-text">Tempo mínimo entre mensagens</p>
                                </div>
                                <div class="form-group">
                                    <label for="max-delay" class="label">
                                        <i data-feather="clock"></i>
                                        Intervalo Máximo (seg)
                                    </label>
                                    <input type="number" id="max-delay" class="input" min="0" required>
                                    <p class="form-text">Tempo máximo entre mensagens</p>
                                </div>
                            </div>

                            <div id="prospecting-feedback" class="mt-4"></div>

                            <div class="flex flex-col sm:flex-row gap-3 pt-4 border-t border-subtle">
                                <button type="submit" class="btn btn-primary flex-1">
                                    <i data-feather="save"></i>
                                    Salvar Configurações
                                </button>
                                <button type="button" class="btn btn-secondary" onclick="location.reload()">
                                    <i data-feather="refresh-cw"></i>
                                    Recarregar
                                </button>
                            </div>
                        </form>
                    </div>
                </div>

                <!-- Info Panel -->
                <div class="space-y-6">
                    <div class="card card-info">
                        <div class="card-header">
                            <h3 class="card-title">
                                <i data-feather="info"></i>
                                Informações Importantes
                            </h3>
                        </div>
                        <div class="card-body space-y-4">
                            <div class="alert alert-info">
                                <i class="alert-icon" data-feather="clock"></i>
                                <div class="alert-content">
                                    <div class="alert-title">Horários de Funcionamento</div>
                                    <div class="alert-description">
                                        Mensagens só serão enviadas dentro do horário configurado.
                                        Fora deste período, as mensagens ficam em fila.
                                    </div>
                                </div>
                            </div>

                            <div class="alert alert-warning">
                                <i class="alert-icon" data-feather="zap"></i>
                                <div class="alert-content">
                                    <div class="alert-title">Intervalos Aleatórios</div>
                                    <div class="alert-description">
                                        O sistema escolhe um tempo aleatório entre o mínimo e máximo
                                        para parecer mais natural e evitar bloqueios.
                                    </div>
                                </div>
                            </div>

                            <div class="bg-gray-50 rounded-lg p-4">
                                <h4 class="font-semibold text-sm text-primary mb-3">Sugestões de Configuração</h4>
                                <ul class="space-y-2 text-sm text-secondary">
                                    <li class="flex items-start gap-2">
                                        <i data-feather="check" class="text-green-500 mt-0.5" style="width: 14px; height: 14px;"></i>
                                        <span><strong>Horário:</strong> 08:00 às 20:00 (horário comercial)</span>
                                    </li>
                                    <li class="flex items-start gap-2">
                                        <i data-feather="check" class="text-green-500 mt-0.5" style="width: 14px; height: 14px;"></i>
                                        <span><strong>Intervalo:</strong> 30 a 120 segundos</span>
                                    </li>
                                    <li class="flex items-start gap-2">
                                        <i data-feather="check" class="text-green-500 mt-0.5" style="width: 14px; height: 14px;"></i>
                                        <span><strong>Respeitar:</strong> Finais de semana e feriados</span>
                                    </li>
                                </ul>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
    console.log('prospectingConfig.js: loadProspectingConfigPage - HTML da página de Configuração de Prospecção renderizado.');

    const formElement = document.getElementById('prospecting-config-form');
    if (formElement) {
        formElement.addEventListener('submit', handleProspectingConfigSubmit);
        console.log('prospectingConfig.js: loadProspectingConfigPage - Event listener para submit do formulário adicionado.');
    } else {
        console.error('prospectingConfig.js: loadProspectingConfigPage - Elemento do formulário "prospecting-config-form" não encontrado.');
    }

    console.log('prospectingConfig.js: loadProspectingConfigPage - Tentando carregar configurações iniciais de prospecção...');
    await fetchProspectingConfig();
    console.log('prospectingConfig.js: loadProspectingConfigPage - Configurações iniciais de prospecção carregadas (ou tentativa de carregamento concluída).');

    if (typeof feather !== 'undefined' && feather && typeof feather.replace === 'function') {
        feather.replace();
        console.log('prospectingConfig.js: loadProspectingConfigPage - Feather icons re-renderizados.');
    } else {
        console.warn('prospectingConfig.js: loadProspectingConfigPage - Feather não está definido ou a função replace não existe. Ícones podem não ser renderizados corretamente.');
    }

    console.log('prospectingConfig.js: loadProspectingConfigPage - Página de Configuração de Prospecção carregada completamente.');
}

async function fetchProspectingConfig() {
    console.log('prospectingConfig.js: fetchProspectingConfig - Iniciando busca da configuração de prospecção...');
    const form = document.getElementById('prospecting-config-form');
    const feedbackContainer = document.getElementById('prospecting-feedback');

    if (!form) {
        console.error('prospectingConfig.js: fetchProspectingConfig - Formulário "prospecting-config-form" não encontrado. Não é possível preencher os campos.');
        return;
    }
    if (!feedbackContainer) {
        console.error('prospectingConfig.js: fetchProspectingConfig - Container de feedback "prospecting-feedback" não encontrado.');
        // Prosseguir mesmo sem feedback container, mas logar o erro.
    } else {
        clearFeedback(feedbackContainer);
        console.log('prospectingConfig.js: fetchProspectingConfig - Feedback anterior limpo.');
    }

    try {
        console.log('prospectingConfig.js: fetchProspectingConfig - Chamando API getProspectingConfig...');
        const config = await getProspectingConfig();
        console.log('prospectingConfig.js: fetchProspectingConfig - Configurações recebidas da API:', config);

        if (config) {
            document.getElementById('start-time').value = config.start_time || '09:00';
            document.getElementById('end-time').value = config.end_time || '18:00';
            document.getElementById('min-delay').value = config.min_delay !== null ? config.min_delay : 5;
            document.getElementById('max-delay').value = config.max_delay !== null ? config.max_delay : 15;
            console.log('prospectingConfig.js: fetchProspectingConfig - Campos do formulário preenchidos com os valores da configuração.');
        } else {
            console.warn('prospectingConfig.js: fetchProspectingConfig - API retornou config nula ou indefinida. Usando valores padrão.');
            document.getElementById('start-time').value = '09:00';
            document.getElementById('end-time').value = '18:00';
            document.getElementById('min-delay').value = 5;
            document.getElementById('max-delay').value = 15;
        }
        console.log('prospectingConfig.js: fetchProspectingConfig - Configuração de prospecção carregada e campos preenchidos/padrão definidos.');
    } catch (error) {
        console.error('prospectingConfig.js: fetchProspectingConfig - Erro ao buscar configuração de prospecção:', error);
        if (feedbackContainer) {
            showFeedback(feedbackContainer, error.message || 'Erro ao carregar configurações de prospecção.', 'error');
            console.log('prospectingConfig.js: fetchProspectingConfig - Mensagem de erro exibida no feedback container.');
        }
    }
    console.log('prospectingConfig.js: fetchProspectingConfig - Finalizada busca da configuração de prospecção.');
}

async function handleProspectingConfigSubmit(event) {
    event.preventDefault();
    console.log('prospectingConfig.js: handleProspectingConfigSubmit - Formulário de configuração de prospecção submetido.');
    const feedbackContainer = document.getElementById('prospecting-feedback');
    const submitBtn = event.currentTarget.querySelector('button[type="submit"]');

    if (!feedbackContainer) {
        console.error('prospectingConfig.js: handleProspectingConfigSubmit - Container de feedback "prospecting-feedback" não encontrado. Mensagens de feedback não serão exibidas.');
    }
    if (!submitBtn) {
        console.error('prospectingConfig.js: handleProspectingConfigSubmit - Botão de submit não encontrado. Não é possível gerenciar o estado de loading.');
        // Não retornar aqui, tentar prosseguir, mas o estado de loading não funcionará.
    }

    if (submitBtn) {
        setLoadingState(submitBtn, true);
        console.log('prospectingConfig.js: handleProspectingConfigSubmit - Estado de loading do botão de submit ATIVADO.');
    }
    if (feedbackContainer) {
        clearFeedback(feedbackContainer);
        console.log('prospectingConfig.js: handleProspectingConfigSubmit - Feedback anterior limpo.');
    }

    const startTime = document.getElementById('start-time').value;
    const endTime = document.getElementById('end-time').value;
    const minDelay = parseInt(document.getElementById('min-delay').value);
    const maxDelay = parseInt(document.getElementById('max-delay').value);
    const allowedWeekdays = [1, 2, 3, 4, 5]; // Segunda a Sexta como padrão
    console.log('prospectingConfig.js: handleProspectingConfigSubmit - Valores obtidos do formulário:', { startTime, endTime, minDelay, maxDelay, allowedWeekdays });

    // Validações
    console.log('prospectingConfig.js: handleProspectingConfigSubmit - Iniciando validações dos campos...');
    if (!isValidTimeFormat(startTime) || !isValidTimeFormat(endTime)) {
        console.warn('prospectingConfig.js: handleProspectingConfigSubmit - Validação falhou: Formato de horário inválido.');
        if (feedbackContainer) showFeedback(feedbackContainer, 'Formato de horário inválido (HH:MM).', 'error');
        if (submitBtn) setLoadingState(submitBtn, false);
        console.log('prospectingConfig.js: handleProspectingConfigSubmit - Estado de loading do botão de submit DESATIVADO devido à falha na validação.');
        return;
    }
    console.log('prospectingConfig.js: handleProspectingConfigSubmit - Validação de formato de horário: OK.');

    if (minDelay < 0 || maxDelay < 0) {
        console.warn('prospectingConfig.js: handleProspectingConfigSubmit - Validação falhou: Atrasos mínimo e/ou máximo são negativos.');
        if (feedbackContainer) showFeedback(feedbackContainer, 'Atrasos mínimo e máximo devem ser números positivos.', 'error');
        if (submitBtn) setLoadingState(submitBtn, false);
        console.log('prospectingConfig.js: handleProspectingConfigSubmit - Estado de loading do botão de submit DESATIVADO devido à falha na validação.');
        return;
    }
    console.log('prospectingConfig.js: handleProspectingConfigSubmit - Validação de atrasos positivos: OK.');

    if (minDelay > maxDelay) {
        console.warn('prospectingConfig.js: handleProspectingConfigSubmit - Validação falhou: Atraso mínimo maior que o atraso máximo.');
        if (feedbackContainer) showFeedback(feedbackContainer, 'Atraso mínimo não pode ser maior que o atraso máximo.', 'error');
        if (submitBtn) setLoadingState(submitBtn, false);
        console.log('prospectingConfig.js: handleProspectingConfigSubmit - Estado de loading do botão de submit DESATIVADO devido à falha na validação.');
        return;
    }
    console.log('prospectingConfig.js: handleProspectingConfigSubmit - Validação de atraso mínimo <= máximo: OK.');
    console.log('prospectingConfig.js: handleProspectingConfigSubmit - Todas as validações passaram com sucesso.');

    const configData = {
        start_time: startTime,
        end_time: endTime,
        min_delay: minDelay,
        max_delay: maxDelay,
        allowed_weekdays: allowedWeekdays
    };
    console.log('prospectingConfig.js: handleProspectingConfigSubmit - Dados preparados para enviar à API:', configData);

    try {
        console.log('prospectingConfig.js: handleProspectingConfigSubmit - Chamando API setProspectingConfig...');
        const response = await setProspectingConfig(configData);
        console.log('prospectingConfig.js: handleProspectingConfigSubmit - Resposta recebida da API setProspectingConfig:', response);

        console.log('prospectingConfig.js: handleProspectingConfigSubmit - Tentando recarregar as configurações após o salvamento...');
        await fetchProspectingConfig(); 
        console.log('prospectingConfig.js: handleProspectingConfigSubmit - Configurações de prospecção salvas e recarregadas com sucesso.');

        const successMessage = response && response.message ? response.message : 'Configurações de prospecção salvas com sucesso!';
        console.log('prospectingConfig.js: handleProspectingConfigSubmit - Mensagem de sucesso a ser exibida:', successMessage);
        if (feedbackContainer) {
            showFeedback(feedbackContainer, successMessage, 'success');
            console.log('prospectingConfig.js: handleProspectingConfigSubmit - Mensagem de sucesso exibida no feedback container.');
        } else {
            console.warn('prospectingConfig.js: handleProspectingConfigSubmit - Container de feedback não encontrado, mensagem de sucesso não exibida na UI, mas logada.');
        }

    } catch (error) {
        console.error('prospectingConfig.js: handleProspectingConfigSubmit - Erro ao salvar configurações de prospecção:', error);
        const errorMessage = error && error.message ? error.message : 'Erro ao salvar configurações de prospecção.';
        console.log('prospectingConfig.js: handleProspectingConfigSubmit - Mensagem de erro a ser exibida:', errorMessage);
        if (feedbackContainer) {
            showFeedback(feedbackContainer, errorMessage, 'error');
            console.log('prospectingConfig.js: handleProspectingConfigSubmit - Mensagem de erro exibida no feedback container.');
        } else {
            console.warn('prospectingConfig.js: handleProspectingConfigSubmit - Container de feedback não encontrado, mensagem de erro não exibida na UI, mas logada.');
        }
    } finally {
        if (submitBtn) {
            setLoadingState(submitBtn, false);
            console.log('prospectingConfig.js: handleProspectingConfigSubmit - Estado de loading do botão de submit DESATIVADO no bloco finally.');
        }
        console.log('prospectingConfig.js: handleProspectingConfigSubmit - Finalizado processamento do submit.');
    }
}
