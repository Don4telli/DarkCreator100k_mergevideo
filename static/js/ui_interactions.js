document.addEventListener('DOMContentLoaded', () => {
  // Lógica dos botões de Aspect Ratio (que você já tem)
  const selector = document.querySelector('.aspect-ratio-selector');
  if (selector) {
    const buttons = selector.querySelectorAll('.aspect-btn');
    const hiddenInput = selector.querySelector('input[name="aspect_ratio"]');

    buttons.forEach(button => {
      button.addEventListener('click', () => {
        // 1. Remove a classe 'active' de TODOS os botões
        buttons.forEach(btn => btn.classList.remove('active'));

        // 2. Adiciona a classe 'active' apenas ao botão clicado
        button.classList.add('active');

        // 3. Atualiza o valor do input oculto com o data-value do botão
        hiddenInput.value = button.dataset.value;
        
      });
    });
  }

  // --- NOVA LÓGICA PARA O TOGGLE DE GREEN SCREEN ---
    const greenScreenBtn = document.getElementById('greenScreenToggle');
    const greenDurationInput = document.querySelector('input[name="green_duration"]');
    const greenScreenStatus = document.getElementById('greenScreenStatus'); // << Pega o SPAN

    if (greenScreenBtn && greenDurationInput && greenScreenStatus) { // << Garante que o SPAN existe
    greenScreenBtn.addEventListener('click', () => {
        const currentState = greenScreenBtn.dataset.status;

        if (currentState === 'off') {
        // Ligar
        greenScreenBtn.dataset.status = 'on';
        greenScreenBtn.classList.add('is-on');
        greenDurationInput.value = '10';
        greenScreenStatus.textContent = 'ON'; // << Altera o texto APENAS do span
        } else {
        // Desligar
        greenScreenBtn.dataset.status = 'off';
        greenScreenBtn.classList.remove('is-on');
        greenDurationInput.value = '0';
        greenScreenStatus.textContent = 'OFF'; // << Altera o texto APENAS do span
        }
    });
  }
});

