document.addEventListener('DOMContentLoaded', () => {
  const sidebarPlaceholder = document.getElementById('sidebar-placeholder');
  const toggleBtn = document.getElementById('sidebar-toggle');

  // Função para carregar e configurar a sidebar
  function setupSidebar() {
    fetch('/static/components/sidebar.html')
      .then(response => response.text())
      .then(html => {
        sidebarPlaceholder.innerHTML = html;
        
        const sidebar = document.getElementById('sidebar');

        if (sidebar && toggleBtn) {
          // Evento de TOGGLE (abrir/fechar)
          toggleBtn.addEventListener('click', () => {
            sidebar.classList.toggle('is-open');
          });
        }
      })
      .catch(error => {
        console.error('Erro ao carregar a sidebar:', error);
      });
  }

  // Inicia o processo
  if (sidebarPlaceholder && toggleBtn) {
    setupSidebar();
  }
});