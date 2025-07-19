
document.getElementById('videoForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  const form = e.target;
  const submitBtn = form.querySelector('button[type="submit"]');
  submitBtn.disabled = true;

  // Inputs — adjust these selectors to match your HTML
  const imageInput = document.getElementById('imageFiles');    // <input type="file" id="imageFiles" multiple>
  const audioInput = document.getElementById('audioFile');     // <input type="file" id="audioFile">
  const aspectRatio  = form.querySelector('[name="aspect_ratio"]').value;
  const greenDuration = parseFloat(form.querySelector('[name="green_duration"]').value) || 5;

  const uploadedImageNames = [];
  let uploadedAudioName = null;

  // Helper to upload one file via signed URL
  async function uploadFile(file, fileType) {
    // 1) get signed URL
    const res1 = await fetch('/get_signed_url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename: file.name,
        file_type: fileType
      })
    });
    if (!res1.ok) throw new Error(`Error fetching signed URL: ${await res1.text()}`);
    const { signed_url, filename } = await res1.json();

    // 2) build progress element
    const p = document.createElement('div');
    p.style.margin = '8px 0';
    p.innerHTML = `<strong>Uploading ${filename}</strong><br>`;
    const bar = document.createElement('progress');
    bar.max = 100;
    bar.value = 0;
    bar.style.width = '100%';
    p.appendChild(bar);
    form.appendChild(p);

    // 3) upload via PUT
    const xhr = new XMLHttpRequest();
    return new Promise((resolve, reject) => {
      xhr.upload.addEventListener('progress', ev => {
        if (ev.lengthComputable) bar.value = (ev.loaded / ev.total) * 100;
      });
      xhr.onreadystatechange = () => {
        if (xhr.readyState === 4) {
          form.removeChild(p);
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(filename);
          } else {
            reject(new Error(`Upload failed (${xhr.status}): ${xhr.responseText}`));
          }
        }
      };
      xhr.open('PUT', signed_url);
      xhr.setRequestHeader('Content-Type', file.type);
      xhr.send(file);
    });
  }

  try {
    // Upload all images in sequence (or use Promise.all for parallel)
    for (let file of imageInput.files) {
      const name = await uploadFile(file, 'image');
      uploadedImageNames.push(name);
    }

    // If audio provided, upload it too
    if (audioInput.files.length) {
      uploadedAudioName = await uploadFile(audioInput.files[0], 'audio');
    }

    // 4) Call create_video with the filenames
    const res2 = await fetch('/create_video', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_filenames: uploadedImageNames,
        audio_filename: uploadedAudioName,
        filename: form.querySelector('[name="filename"]').value || 'video.mp4',
        aspect_ratio: aspectRatio,
        green_duration: greenDuration
      })
    });
    if (!res2.ok) throw new Error(`Error creating video: ${await res2.text()}`);
    const { download_url } = await res2.json();

    alert('✅ Vídeo criado com sucesso! Baixe em: ' + download_url);
  } catch (err) {
    console.error(err);
    alert('❌ Ocorreu um erro: ' + err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

