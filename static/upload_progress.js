document.getElementById('videoForm').addEventListener('submit', function (e) {
    e.preventDefault();

    const form = e.target;
    const formData = new FormData(form);
    const xhr = new XMLHttpRequest();

    // Criar barra de progresso
    const progressBar = document.createElement("progress");
    progressBar.max = 100;
    progressBar.value = 0;
    progressBar.style.width = "100%";
    progressBar.style.marginTop = "16px";
    form.appendChild(progressBar);

    xhr.upload.addEventListener("progress", function (e) {
        if (e.lengthComputable) {
            progressBar.value = (e.loaded / e.total) * 100;
        }
    });

    xhr.onreadystatechange = function () {
        if (xhr.readyState === XMLHttpRequest.DONE) {
            form.removeChild(progressBar);
            alert("✅ Vídeo criado com sucesso ou houve erro no servidor.");
        }
    };

    xhr.open("POST", form.action);
    xhr.send(formData);
});
