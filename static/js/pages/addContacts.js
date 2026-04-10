// static/js/pages/addContacts.js
import { addProspects } from '../api.js';
import { showFeedback, clearFeedback, setLoadingState } from '../utils.js';

export async function loadAddContactsPage(container) {
    console.log('addContacts.js: Carregando página de Adicionar Leads...');
    container.innerHTML = `
        <div class="animate-fade-in">
        <header class="page-header">
            <h1 class="page-title">
                <span class="icon-wrapper">
                    <i data-feather="user-plus"></i>
                </span>
                Inserir Leads
            </h1>
            <p class="page-subtitle">Adicione novos números de telefone para iniciar o processo de prospecção.</p>
        </header>

        <div class="card">
            <div class="card-header">
                <h3 class="card-title">
                    <i data-feather="phone"></i>
                    Inserir Números
                </h3>
            </div>
            <div class="card-body">
                <form id="add-prospects-form" class="form">
                    <div class="form-group">
                        <label for="prospect-numbers" class="label">
                            <i data-feather="hash"></i>
                            Números de Telefone
                        </label>
                        <textarea id="prospect-numbers" name="numbers_with_names" class="textarea" rows="10" placeholder="Ex:&#10;5511987654321,João Silva&#10;+55 (11) 91234-5678,Maria&#10;5511998765432" required></textarea>
                        <p class="form-text">Insira um número por linha, opcionalmente seguido de vírgula e o nome (ex: "número,nome"). Inclua o código do país (ex: 55 para Brasil) e o DDD.</p>
                    </div>
                    <div id="add-prospects-feedback"></div>
                    <button type="submit" class="btn btn-primary">
                        <i data-feather="plus-circle"></i>
                        <span>Adicionar à Fila</span>
                    </button>
                </form>
            </div>
        </div>
        </div>
    `;

    const form = document.getElementById('add-prospects-form');
    const feedbackContainer = document.getElementById('add-prospects-feedback');
    const submitBtn = form.querySelector('button[type="submit"]');

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        console.log('addContacts.js: Formulário de adicionar prospects submetido.');
        clearFeedback(feedbackContainer);
        setLoadingState(submitBtn, true);

        const numbersInput = document.getElementById('prospect-numbers');
        const numbersValue = numbersInput.value.trim();
        // Enviar apenas o texto CSV diretamente, sem encapsular em objeto
        let payload = numbersValue;

        try {
            const response = await addProspects(payload);
            showFeedback(feedbackContainer, `Sucesso! ${response.submitted_count} número(s) adicionado(s) à fila. Tamanho estimado da fila: ${response.current_queue_size}.`, 'success');
            form.reset(); // Limpa o formulário
            console.log('addContacts.js: Prospects adicionados com sucesso.');
        } catch (error) {
            console.error('addContacts.js: Erro ao adicionar prospects:', error);
            showFeedback(feedbackContainer, error.message || 'Erro ao adicionar números à fila.', 'error');
        } finally {
            setLoadingState(submitBtn, false);
        }
    });

    console.log('addContacts.js: Página de Adicionar Leads carregada.');
}
