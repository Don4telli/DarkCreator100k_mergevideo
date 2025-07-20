
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
  
  // Progress elements
  const progressWrap = document.getElementById('progressContainer');
  const bar = document.getElementById('progressBar');
  const text = document.getElementById('progressText');
  const downloadLink = document.getElementById('downloadLink');
  
  // Initialize progress
  if (downloadLink) downloadLink.style.display = 'none';
  if (bar) bar.value = 0;
  if (progressWrap) progressWrap.style.display = 'block';

  const uploadedImageNames = [];
  let uploadedAudioName = null;
  
  const totalFiles = imageInput.files.length + (audioInput.files.length ? 1 : 0);
  let doneFiles = 0;

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

    // 2) upload via PUT with fetch
    await fetch(signed_url, {
      method: 'PUT',
      headers: { 'Content-Type': file.type },
      body: file
    });
    
    // Update global progress
    doneFiles++;
    const pct = Math.round((doneFiles / totalFiles) * 100);
    if (bar) bar.value = pct;
    if (text) text.textContent = `Uploading (${pct}%)`;
    
    return filename;
  }

  try {
    // Upload all images in parallel (max 60 concurrent)
    const files = Array.from(imageInput.files)
                      .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
    
    const maxConcurrent = 60;
    
    class Semaphore {
      constructor(count){ this.count=count; this.waiting=[]; }
      async acquire(){
        if(this.count>0){ this.count--; return; }
        return new Promise(res => this.waiting.push(res));
      }
      release(){
        this.count++;
        if(this.waiting.length){
          const res=this.waiting.shift();
          this.count--; res();
        }
      }
    }
    const sem = new Semaphore(maxConcurrent);
    
    const uploadPromises = files.map(async (file) => {
      await sem.acquire();
      try {
        return await uploadFile(file, 'image');
      } finally { 
        sem.release(); 
      }
    });
    
    const uploadResults = await Promise.all(uploadPromises);
    uploadedImageNames.push(...uploadResults);

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

    // Show success and download link
    if (bar) bar.value = 100;
    if (text) text.textContent = '✔️ Vídeo pronto!';
    if (downloadLink) {
      downloadLink.href = download_url;
      downloadLink.style.display = 'inline-block';
    } else {
      alert('✅ Vídeo criado com sucesso! Baixe em: ' + download_url);
    }
  } catch (err) {
    console.error(err);
    if (text) text.textContent = '❌ erro – veja console';
    alert('❌ Ocorreu um erro: ' + err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

