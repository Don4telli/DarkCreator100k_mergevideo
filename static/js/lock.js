/* --- config ---------------------------------------------------------------- */
const MASTER_CODE = "Aa123";           // senha mestra

// Firebase (opcional) – coloque suas chaves se for usar a Function
/*
import { initializeApp }   from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";
import { getFunctions, httpsCallable }
       from "https://www.gstatic.com/firebasejs/10.12.0/firebase-functions.js";

const firebaseConfig = { /* ... * / };
const app       = initializeApp(firebaseConfig);
const functions = getFunctions(app, "europe-west1");
const verify    = httpsCallable(functions, "verifyCode");
*/

/* --- helpers ----------------------------------------------------------------*/
const overlay = document.getElementById("lockOverlay");
const input   = document.getElementById("codeInput");
const btn     = document.getElementById("unlockBtn");

const deviceId = (() => {
  let id = localStorage.getItem("deviceId");
  if (!id) { id = crypto.randomUUID(); localStorage.setItem("deviceId", id); }
  return id;
})();

const cached = JSON.parse(localStorage.getItem("codeOk") || "null");
if (cached) showSite(cached.welcomeName);

btn.addEventListener("click", tryUnlock);
input.addEventListener("keyup", e => e.key === "Enter" && tryUnlock());

function tryUnlock() {
  const code = input.value.trim();
  if (!code) return;
  btn.disabled = true;

  /* ① senha mestra ----------------------------- */
  if (code === MASTER_CODE) {
    localStorage.setItem("codeOk", JSON.stringify({
      deviceId, code: "MASTER", welcomeName: "Admin"
    }));
    showSite("Admin");
    btn.disabled = false;
    return;
  }

  /* ② sem Firebase? apenas erro visual ---------- */
  shakeRed("Código inválido");
  btn.disabled = false;

  /* ② com Firebase? descomente e use:
  verify({ code, deviceId })
    .then(({ data }) => {
      localStorage.setItem("codeOk", JSON.stringify({ ...data, code, deviceId }));
      showSite(data.welcomeName);
    })
    .catch(err => shakeRed(err?.message || "Erro"))
    .finally(() => (btn.disabled = false));
  */
}

function showSite(name) {
  overlay.style.display = "none";
  console.log("Bem-vindo", name);
}

function shakeRed(msg) {
  input.classList.add("error", "shake");
  setTimeout(() => input.classList.remove("error", "shake"), 800);
  console.warn(msg);
}
