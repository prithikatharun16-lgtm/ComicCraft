const form = document.querySelector("#comic-form");
const createButton = document.querySelector("#create-button");
const exportButton = document.querySelector("#export-button");
const panelsGrid = document.querySelector("#panels-grid");
const toast = document.querySelector("#toast");

let currentComic = null;
let toastTimer = null;

function showToast(message, isError = false) {
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("visible"), 3600);
}

function updateGenerationBadge(comic) {
  const story = comic.generation?.story || "Your story";
  const art = comic.generation?.art || "Illustrations";
  const storyName = story.startsWith("Gemini") ? story : "Demo story";
  const artName = art.startsWith("Hugging Face") ? "AI art" : "sample art";
  document.querySelector("#generation-badge").textContent = `${storyName} · ${artName}`;
}

function makePanel(panel) {
  const article = document.createElement("article");
  article.className = "comic-panel";

  const image = document.createElement("img");
  image.className = "panel-art";
  image.src = panel.image_url;
  image.alt = `${panel.title}: ${panel.narration}`;
  image.loading = "lazy";
  image.decoding = "async";

  const copy = document.createElement("div");
  copy.className = "panel-copy";
  const titleLine = document.createElement("div");
  titleLine.className = "panel-title-line";
  const number = document.createElement("span");
  number.className = "panel-number";
  number.textContent = String(panel.number).padStart(2, "0");
  const title = document.createElement("h4");
  title.textContent = panel.title;
  titleLine.append(number, title);

  const narration = document.createElement("p");
  narration.textContent = panel.narration;
  copy.append(titleLine, narration);
  if (panel.dialogue) {
    const dialogue = document.createElement("p");
    dialogue.className = "panel-dialogue";
    dialogue.textContent = `“${panel.dialogue}”`;
    copy.append(dialogue);
  }
  article.append(image, copy);
  return article;
}

function renderComic(comic, isSample = false) {
  currentComic = comic;
  document.querySelector("#comic-title").textContent = comic.title;
  document.querySelector("#comic-tagline").textContent = comic.tagline;
  panelsGrid.replaceChildren(...comic.panels.map(makePanel));
  panelsGrid.dataset.count = String(comic.panels.length);
  document.querySelector("#panel-total").innerHTML = `${comic.panels.length} PANELS <b>·</b> 1 LITTLE ADVENTURE`;
  document.querySelector("#preview-note-text").textContent = isSample
    ? "Tweak the details on the left, then make this story yours."
    : `${comic.generation?.story || "Story ready"} · ${comic.generation?.art || "Illustrations ready"}`;
  document.querySelector("#start-over").hidden = isSample;
  exportButton.disabled = false;
  document.querySelector("#comic-sheet").setAttribute("aria-busy", "false");
  updateGenerationBadge(comic);
}

function setCreating(isCreating) {
  createButton.disabled = isCreating;
  createButton.classList.toggle("is-loading", isCreating);
  createButton.querySelector(".button-label").textContent = isCreating ? "Making your comic…" : "Create my comic";
  createButton.querySelector(".button-icon").innerHTML = isCreating ? '<span class="button-spinner"></span>' : "↗";
  form.setAttribute("aria-busy", String(isCreating));
  document.querySelector("#comic-sheet").setAttribute("aria-busy", String(isCreating));
  if (isCreating) {
    exportButton.disabled = true;
    document.querySelector("#generation-badge").textContent = "Finding the story…";
  }
}

async function loadSample() {
  try {
    const response = await fetch("/api/sample");
    if (!response.ok) throw new Error("Sample story is unavailable.");
    renderComic(await response.json(), true);
  } catch {
    panelsGrid.replaceChildren();
    const message = document.createElement("div");
    message.className = "panel-skeleton";
    message.textContent = "Your story is ready when you are.";
    panelsGrid.append(message);
    exportButton.disabled = true;
  }
}

async function updateServiceStatus() {
  const dot = document.querySelector("#service-dot");
  const label = document.querySelector("#service-label");
  try {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error("Unavailable");
    const health = await response.json();
    if (health.gemini_configured && health.images_configured) {
      label.textContent = "AI studio is ready";
    } else if (health.gemini_configured || health.images_configured) {
      label.textContent = "Studio ready · some demo features";
    } else {
      label.textContent = "Demo studio is ready";
    }
  } catch {
    dot?.parentElement.classList.add("offline");
    label.textContent = "Studio is starting up";
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!form.reportValidity()) return;

  const payload = Object.fromEntries(new FormData(form).entries());
  payload.panel_count = Number(payload.panel_count);
  setCreating(true);
  const progress = ["Finding the story…", "Painting your panels…", "Adding the final touches…"];
  let progressIndex = 0;
  const progressTimer = window.setInterval(() => {
    progressIndex = Math.min(progressIndex + 1, progress.length - 1);
    document.querySelector("#generation-badge").textContent = progress[progressIndex];
  }, 4200);

  try {
    const response = await fetch("/api/comics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "We couldn't create that comic just now.");
    renderComic(result);
    showToast("Your new comic is ready. Have a look around!");
    document.querySelector("#preview-heading").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    document.querySelector("#generation-badge").textContent = "A little preview";
    showToast(error.message || "Something went wrong. Please try again.", true);
  } finally {
    window.clearInterval(progressTimer);
    setCreating(false);
    if (currentComic) exportButton.disabled = false;
  }
});

document.querySelectorAll(".idea-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.querySelector("#prompt").value = chip.dataset.idea;
    document.querySelector("#character_name").value = chip.dataset.name;
    document.querySelector("#setting").value = chip.dataset.setting;
    document.querySelector("#tone").value = chip.dataset.tone;
    document.querySelector("#prompt").focus();
    showToast("A fresh idea is in the studio. Make it your own!");
  });
});

document.querySelector("#start-over").addEventListener("click", () => {
  document.querySelector("#prompt").value = "A brave fox explores an enchanted forest and discovers a tiny star that has fallen from the sky.";
  document.querySelector("#character_name").value = "Pip";
  document.querySelector("#setting").value = "Enchanted forest";
  document.querySelector("#tone").value = "adventurous";
  document.querySelector("#art_style").value = "storybook";
  document.querySelector("#panel_count").value = "4";
  loadSample();
});

exportButton.addEventListener("click", async () => {
  if (!currentComic) return;
  exportButton.disabled = true;
  const oldLabel = exportButton.innerHTML;
  exportButton.innerHTML = '<span aria-hidden="true">…</span> Preparing PDF';
  try {
    const response = await fetch(`/api/comics/${encodeURIComponent(currentComic.id)}/pdf`);
    if (!response.ok) {
      const result = await response.json();
      throw new Error(result.detail || "We couldn't prepare your PDF.");
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const disposition = response.headers.get("Content-Disposition") || "";
    const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || "comiccraft-comic.pdf";
    const download = document.createElement("a");
    download.href = objectUrl;
    download.download = filename;
    document.body.append(download);
    download.click();
    download.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1200);
    window.setTimeout(() => { window.location.href = `/export/${encodeURIComponent(currentComic.id)}/success`; }, 450);
  } catch (error) {
    showToast(error.message || "PDF export failed. Please try again.", true);
    exportButton.disabled = false;
    exportButton.innerHTML = oldLabel;
  }
});

loadSample();
updateServiceStatus();
