// lock.js  (exemplo resumido)

import { initializeApp }   from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";
import { getFunctions, httpsCallable }
       from "https://www.gstatic.com/firebasejs/10.12.0/firebase-functions.js";

// 1) Config Firebase — se preferir, coloque num outro módulo e faça import { firebaseConfig } …
const firebaseConfig = {
  apiKey: "…",
  authDomain: "…",
  projectId: "…",
  appId: "…"
};

const app       = initializeApp(firebaseConfig);
const functions = getFunctions(app, "europe-west1");
const verify    = httpsCallable(functions, "verifyCode");

// 2) DOM refs
const overlay = document.getElementById("lockOverlay");
const input   = document.getElementById("codeInput");
const btn     = document.getElementById("unlockBtn");

// 3) deviceId + cache
const deviceId = (() => {
  let id = localStorage.getItem("deviceId");
  if (!id) { id = crypto.randomUUID(); localStorage.setItem("deviceId", id); }
  return id;
})();

// 4) se já desbloqueado, pula overlay
const cached = JSON.parse(localStorage.getItem("codeOk") || "null");
if (cached) showSite(cached.welcomeName);

// 5) listeners
btn.addEventListener("click", tryUnlock);
input.addEventListener("keyup", e => e.key === "Enter" && tryUnlock());

const MASTER_CODE = "Aa123";    // 👈  senha mestra

function tryUnlock() {
  const code = input.value.trim();
  if (!code) return;
  btn.disabled = true;

  /* ①  se for a senha mestra, desbloqueia sem Firebase */
  if (code === MASTER_CODE) {
    localStorage.setItem("codeOk", JSON.stringify({
      deviceId,
      code: "MASTER",
      welcomeName: "Admin"
    }));
    showSite("Admin");
    btn.disabled = false;
    return;                     // sai da função
  }

  /* ②  caso contrário, chama a Cloud Function */
  verify({ code, deviceId })
    .then(({ data }) => {
      localStorage.setItem("codeOk", JSON.stringify({ ...data, code, deviceId }));
      showSite(data.welcomeName);
    })
    .catch(err => {
      input.classList.add("error");
      setTimeout(() => input.classList.remove("error"), 1200);
      alert(err.message);
    })
    .finally(() => (btn.disabled = false));
}

function showSite(name) {
  overlay.style.display = "none";
  // Exemplo: mostrar “Bem-vindo” em algum canto fixo
  document.body.insertAdjacentHTML("afterbegin",
    `<div id="welcome" style="position:fixed;top:10px;right:10px;">Bem‑vindo ${name}!</div>`
  );
}
