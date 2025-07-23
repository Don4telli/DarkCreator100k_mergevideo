document.addEventListener('DOMContentLoaded', () => {
    // --- Referências aos Elementos do HTML ---
    const imageInput = document.getElementById('imageUpload');
    const audioInput = document.getElementById('audioUpload');
    const createVideoButton = document.getElementById('create-video-btn');
    const progressContainer = document.getElementById('progress-container');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');
    const downloadLinkContainer = document.getElementById('download-link-container');
    const downloadLink = document.getElementById('download-link');

    // --- Variáveis para guardar o estado dos uploads ---
    let uploadedImageFiles = [];
    let uploadedAudioFile = null;

    // ========================================================================
    // 1. LÓGICA DA INTERFACE (Seu código, que já estava correto)
    // ========================================================================

    // --- Seletor de Aspect Ratio ---
    const selector = document.querySelector('.aspect-ratio-selector');
    if (selector) {
        const buttons = selector.querySelectorAll('.aspect-btn');
        const hiddenInput = selector.querySelector('input[name="aspect_ratio"]');
        buttons.forEach(button => {
            button.addEventListener('click', () => {
                buttons.forEach(btn => btn.classList.remove('active'));
                button.classList.add('active');
                hiddenInput.value = button.dataset.value;
            });
        });
    }

    // --- Toggle de Green Screen ---
    const greenScreenBtn = document.getElementById('greenScreenToggle');
    const greenDurationInput = document.querySelector('input[name="green_duration"]');
    const greenScreenStatus = document.getElementById('greenScreenStatus');
    if (greenScreenBtn && greenDurationInput && greenScreenStatus) {
        greenScreenBtn.addEventListener('click', () => {
            const currentState = greenScreenBtn.dataset.status;
            if (currentState === 'off') {
                greenScreenBtn.dataset.status = 'on';
                greenScreenBtn.classList.add('is-on');
                greenDurationInput.value = '10'; // Valor padrão quando ligado
                greenScreenStatus.textContent = 'ON';
            } else {
                greenScreenBtn.dataset.status = 'off';
                greenScreenBtn.classList.remove('is-on');
                greenDurationInput.value = '0';
                greenScreenStatus.textContent = 'OFF';
            }
        });
    }

    // ========================================================================
    // 2. FUNÇÕES PRINCIPAIS (A parte que faltava e foi corrigida)
    // ========================================================================

    /**
     * **A CORREÇÃO PRINCIPAL ESTÁ AQUI**
     * Esta função "limpa" o nome do arquivo, removendo caracteres
     * especiais e espaços, que são a causa provável do erro.
     */
    function sanitizeFilename(filename) {
        // Remove a extensão para trabalhar só no nome
        const name = filename.substring(0, filename.lastIndexOf('.')) || filename;
        const extension = filename.substring(filename.lastIndexOf('.'));

        const sanitizedName = name
            .replace(/\s+/g, '-') // Substitui espaços por hífens
            .replace(/[^a-zA-Z0-9-]/g, '') // Remove caracteres não alfanuméricos (exceto hífen)
            .replace(/--+/g, '-'); // Remove hífens duplicados

        return sanitizedName + extension;
    }

    /**
     * Função genérica para fazer upload de um arquivo para o Google Cloud Storage.
     * Ela primeiro pede uma URL assinada e depois envia o arquivo.
     */
    async function uploadFile(file, fileType) {
        const cleanFilename = sanitizeFilename(file.name);
        
        try {
            // Passo 1: Pedir a URL assinada para o backend
            const urlResponse = await fetch('/get_signed_url', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename: cleanFilename, file_type: fileType })
            });

            if (!urlResponse.ok) throw new Error('Falha ao obter URL assinada.');
            
            const { signed_url } = await urlResponse.json();

            // Passo 2: Fazer o upload do arquivo para a URL recebida
            const uploadResponse = await fetch(signed_url, {
                method: 'PUT',
                body: file,
                headers: { 'Content-Type': file.type }
            });

            if (!uploadResponse.ok) throw new Error('Falha no upload para o bucket.');
            
            console.log(`Upload de ${cleanFilename} bem-sucedido!`);
            return cleanFilename; // Retorna o nome limpo para ser usado depois

        } catch (error) {
            console.error(`Erro no upload de ${file.name}:`, error);
            // Adicionar feedback visual para o usuário aqui, se desejar
            return null;
        }
    }

    // --- Gatilho para upload de IMAGENS ---
    imageInput.addEventListener('change', async (event) => {
        const files = Array.from(event.target.files);
        createVideoButton.disabled = true; // Desabilita o botão durante o upload

        for (const file of files) {
            const cleanFilename = await uploadFile(file, 'image');
            if (cleanFilename) {
                uploadedImageFiles.push(cleanFilename);
            }
        }
        
        // Habilita o botão apenas se pelo menos uma imagem foi enviada
        if (uploadedImageFiles.length > 0) {
            createVideoButton.disabled = false;
        }
    });

    // --- Gatilho para upload de ÁUDIO ---
    audioInput.addEventListener('change', async (event) => {
        const file = event.target.files[0];
        if (file) {
            const cleanFilename = await uploadFile(file, 'audio');
            if (cleanFilename) {
                uploadedAudioFile = cleanFilename;
            }
        }
    });

    // --- Gatilho para CRIAR O VÍDEO ---
    createVideoButton.addEventListener('click', async () => {
        // Validação: Garante que há imagens para criar o vídeo
        if (uploadedImageFiles.length === 0) {
            alert('Por favor, envie pelo menos uma imagem.');
            return;
        }

        // Mostra a barra de progresso
        progressContainer.style.display = 'block';
        downloadLinkContainer.style.display = 'none';

        // Coleta todos os dados do formulário
        const videoData = {
            image_filenames: uploadedImageFiles, // Usa a lista de nomes de arquivos JÁ LIMPOS
            audio_filename: uploadedAudioFile,
            filename: document.getElementById('filename').value || 'video_gerado',
            aspect_ratio: document.querySelector('input[name="aspect_ratio"]').value,
            green_duration: document.querySelector('input[name="green_duration"]').value
        };

        try {
            const response = await fetch('/create_video', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(videoData) // AQUI O JSON É ENVIADO CORRETAMENTE
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Erro desconhecido no servidor.');
            }

            const { session_id } = await response.json();
            monitorProgress(session_id);

        } catch (error) {
            console.error('Erro ao criar vídeo:', error);
            progressText.textContent = `Erro: ${error.message}`;
        }
    });
    
    // Função que monitora o progresso usando Server-Sent Events (SSE)
    function monitorProgress(sessionId) {
        const eventSource = new EventSource(`/progress/${sessionId}`);

        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            
            progressBar.style.width = `${data.progress || 0}%`;
            progressText.textContent = data.message || `${data.progress || 0}%`;

            if (data.status === 'completed') {
                progressText.textContent = 'Vídeo pronto! Clique para baixar.';
                downloadLink.href = data.download_url;
                downloadLink.textContent = `Baixar ${data.filename}`;
                downloadLinkContainer.style.display = 'block';
                eventSource.close();
            } else if (data.status === 'error') {
                progressText.textContent = `Erro: ${data.message}`;
                eventSource.close();
            }
        };

        eventSource.onerror = () => {
            progressText.textContent = 'Erro de conexão. Tente novamente.';
            eventSource.close();
        };
    }
});