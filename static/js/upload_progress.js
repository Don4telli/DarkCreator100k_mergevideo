
document.getElementById('videoForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form        = e.target;
  const submitBtn   = form.querySelector('button[type="submit"]');
  submitBtn.disabled = true;

  // Elementos de progresso
  
   const bar         = document.getElementById('progressBar');
   const text        = document.getElementById('progressText');
   const stats       = document.getElementById('uploadStats');
   const dlLink      = document.getElementById('downloadLink');

   progressContainer.style.display = 'block';

   dlLink.style.display = 'none';
   bar.value = 0; text.textContent = '⬆️ Preparando…'; stats.textContent = '';

  // Arquivos
  const imgFiles = Array.from(document.getElementById('imageFiles').files)
                        .sort((a,b) => a.name.localeCompare(b.name,undefined,{numeric:true}));
  const audFile  = document.getElementById('audioFile').files[0] || null;

  const totalImgs = imgFiles.length;
  const totalFiles = totalImgs + (audFile ? 1 : 0);

  let doneFiles = 0;                       // contador global seguro
  let lastUi    = 0;                       // throttle ui 100 ms
  const uploadedImageNames = [];
  let   uploadedAudioName  = null;

  // — helper: PUT via signed-URL —
  async function putSigned(file, type, index, total) {
    // 1. signed-URL
    const res = await fetch('/get_signed_url',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({filename:file.name,file_type:type})
    });
    if(!res.ok) throw new Error(await res.text());
    const { signed_url, filename } = await res.json();
    
    // 2. upload
    await fetch(signed_url,{method:'PUT',headers:{'Content-Type':file.type},body:file});

    // 3. atualizar barra (thread-safe)
    doneFiles++;
    const pct = Math.round(doneFiles/totalFiles*100);

    const now = performance.now();
      // Atualiza a UI se o throttle permitir OU se for o último arquivo
      if (now - lastUi > 100 || doneFiles === totalFiles) {
        bar.value = pct;
        if (type === 'image') {
          // Usamos doneFiles aqui para o contador ser sempre preciso
          stats.textContent = `Enviando imagem ${doneFiles > totalImgs ? totalImgs : doneFiles}/${totalImgs}`;
          text.textContent = `⬆️ (${pct}%)`;
        } else {
          text.textContent = `⬆️ Enviando áudio (${pct}%)`;
          stats.textContent = 'Áudio 1/1';
        }

        // Se for a atualização final, garante que o texto reflita isso
        if (doneFiles === totalFiles) {
          text.textContent = '⬆️ Upload Concluído (100%)';
          stats.textContent = `Enviados ${totalFiles} arquivos.`;
        }
        lastUi = now;
      }
    return filename;
  }

  // — Upload das imagens em paralelo (até 60) —
  const sem = new class {
    constructor(max){this.max=max;this.q=[];this.av=max;}
    async acquire(){ if(this.av>0){this.av--;return;} return new Promise(r=>this.q.push(r)); }
    release(){ this.av++; if(this.q.length){ this.av--; this.q.shift()(); } }
  }(60);

  const imgPromises = imgFiles.map((f,i)=> (async()=>{
    await sem.acquire();
    try{
      const name = await putSigned(f,'image', i+1,totalImgs);
      uploadedImageNames.push(name);
    }finally{ sem.release(); }
  })());

  // — Upload áudio (se houver) em paralelo —
  const audPromise = audFile
    ? putSigned(audFile,'audio',null,null).then(n=>{ uploadedAudioName=n; })
    : Promise.resolve();

  try{
    await Promise.all([...imgPromises, audPromise]);

    /* ----------------------------------------------------------------
       CRIAR VÍDEO
    ---------------------------------------------------------------- */
    const res = await fetch('/create_video',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        image_filenames: uploadedImageNames,
        audio_filename : uploadedAudioName,
        filename       : form.filename.value || 'video.mp4',
        aspect_ratio   : form.aspect_ratio.value,
        green_duration : parseFloat(form.green_duration.value)||5
      })
    });
    if(!res.ok) throw new Error(await res.text());
    const { session_id } = await res.json();

    /* ----------------------------------------------------------------
       ESCUTAR PROGRESSO
    ---------------------------------------------------------------- */
    listenProgress(session_id);

  }catch(err){
    console.error(err);
    text.textContent = '❌ '+err.message;
  }finally{
    submitBtn.disabled = false;
  }

  // ————————————————————————————————————————————————————————————————
  function listenProgress(id){
    const es = new EventSource(`/progress/${id}`);
    es.onmessage = ({data})=>{
      const d = JSON.parse(data);
      if(d.status==='processing'){
        bar.value = d.progress;
        text.textContent = `🎬 Renderizando… ${d.progress}%`;
      }else if(d.status==='uploading'){
        bar.value = d.progress;
        text.textContent = '⬆️ Enviando vídeo…';
      }else if(d.status==='completed' && d.download_url){
        bar.value = 100;
        text.textContent = '✅ Pronto!';
        dlLink.href = d.download_url;
        dlLink.style.display='inline-block';
        es.close();
      }else if(d.status==='error'){
        text.textContent='❌ '+d.message;
        es.close();
      }
    };
    es.onerror = ()=>{ text.textContent='❌ SSE perdido'; es.close(); };
  }
});

