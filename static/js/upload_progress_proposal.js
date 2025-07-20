/* ------------------------------------------------------------------
   Upload + barra única + download
   ------------------------------------------------------------------ */
const form            = document.getElementById("videoForm");
const submitBtn       = form.querySelector('button[type="submit"]');
const imageInput      = document.getElementById("imageFiles");
const audioInput      = document.getElementById("audioFile");
const progressWrap    = document.getElementById("progressContainer");
const bar             = document.getElementById("progressBar");
const text            = document.getElementById("progressText");
const stats           = document.getElementById("uploadStats");
const downloadLink    = document.getElementById("downloadLink"); // ⬇️ novo

form.addEventListener("submit", async e => {
  e.preventDefault();
  submitBtn.disabled = true;
  downloadLink.style.display = "none";
  bar.value = 0;
  progressWrap.style.display = "block";

  /* helpers -------------------------------------------------------- */
  const aspectRatio   = form.aspect_ratio.value;
  const greenDuration = parseFloat(form.green_duration.value) || 5;
  const filenameOut   = form.filename.value || "my_video.mp4";

  const totalFiles = imageInput.files.length + (audioInput.files.length ? 1 : 0);
  let   doneFiles  = 0;

  async function upload(file, kind){
    /* ① pede URL assinada */
    const res1 = await fetch("/get_signed_url", {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body:JSON.stringify({ filename:file.name, kind })
    });
    if(!res1.ok) throw new Error("Falha get_signed_url");
    const { signed_url, object_name } = await res1.json();

    /* ② faz PUT  com barra única */
    await fetch(signed_url, { method:"PUT", headers:{ "Content-Type":file.type }, body:file });
    doneFiles++;
    const pct = Math.round((doneFiles / totalFiles) * 100);
    bar.value = pct;
    text.textContent = `Uploading (${pct} %)`;
    return object_name;
  }

  try {
    /* ------ IMAGENS ------ */
    const imgNames = [];
    for (const img of imageInput.files){
      imgNames.push(await upload(img, "image"));
    }

    /* ------ ÁUDIO opcional ------ */
    let audioName = null;
    if (audioInput.files.length){
      audioName = await upload(audioInput.files[0], "audio");
    }

    /* ------ CRIAR VÍDEO ------ */
    text.textContent = "Processando vídeo…";
    stats.textContent = "";
    const res2 = await fetch("/create_video", {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body:JSON.stringify({
        images: imgNames,
        audio:  audioName,
        aspect_ratio: aspectRatio,
        green_duration: greenDuration,
        filename: filenameOut
      })
    });
    if(!res2.ok) throw new Error(await res2.text());
    const { download_url } = await res2.json();

    /* ------ pronto ------ */
    bar.value = 100;
    text.textContent = "✔️ Vídeo pronto!";
    downloadLink.href = download_url;
    downloadLink.style.display = "inline-block";
  } catch(err){
    console.error(err);
    alert("Erro: " + err.message);
    text.textContent = "❌ erro – veja console";
  } finally {
    submitBtn.disabled = false;
  }
});
