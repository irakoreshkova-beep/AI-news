const latestUrl = "./data/latest.json";
const archiveIndexUrl = "./data/archive/index.json";

const installButton = document.querySelector("#installButton");
const refreshButton = document.querySelector("#refreshButton");
const dateSelect = document.querySelector("#dateSelect");
const generatedAtNode = document.querySelector("#generatedAt");
const itemCountNode = document.querySelector("#itemCount");
const sourceCountNode = document.querySelector("#sourceCount");
const sourceChipsNode = document.querySelector("#sourceChips");
const newsListNode = document.querySelector("#newsList");
const viewNoteNode = document.querySelector("#viewNote");
const cardTemplate = document.querySelector("#newsCardTemplate");

let installPromptEvent = null;
let archiveIndex = [];

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Request failed for ${url}: ${response.status}`);
  }
  return response.json();
}

function formatTimestamp(value) {
  const date = new Date(value);
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatArchiveDate(value) {
  const date = new Date(`${value}T12:00:00Z`);
  return new Intl.DateTimeFormat("ru-RU", {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(date);
}

function renderChips(sources) {
  sourceChipsNode.innerHTML = "";
  sources.forEach((source) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = source;
    sourceChipsNode.appendChild(chip);
  });
}

function renderItems(items) {
  newsListNode.innerHTML = "";

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent =
      "Сегодня в выбранном окне свежести новых материалов не нашлось. Проверьте архив или обновите позже.";
    newsListNode.appendChild(empty);
    return;
  }

  items.forEach((item) => {
    const fragment = cardTemplate.content.cloneNode(true);
    fragment.querySelector(".card-source").textContent = item.source;
    fragment.querySelector(".card-time").textContent = formatTimestamp(item.publishedAt);
    fragment.querySelector(".card-title").textContent = item.title;
    fragment.querySelector(".card-summary").textContent = item.summary;
    const link = fragment.querySelector(".card-link");
    link.href = item.link;
    newsListNode.appendChild(fragment);
  });
}

function updateSummary(payload, mode) {
  generatedAtNode.textContent = formatTimestamp(payload.generatedAt);
  itemCountNode.textContent = String(payload.items.length);
  sourceCountNode.textContent = String(payload.sources.length);
  renderChips(payload.sources);
  renderItems(payload.items);
  viewNoteNode.textContent =
    mode === "latest"
      ? "Показываю свежий выпуск, который GitHub Actions подготовил автоматически."
      : `Показываю архивный выпуск за ${payload.date}.`;
}

async function loadArchiveIndex() {
  const data = await fetchJson(archiveIndexUrl);
  archiveIndex = data.entries || [];

  dateSelect.innerHTML = "";
  const latestOption = document.createElement("option");
  latestOption.value = "latest";
  latestOption.textContent = "Свежий выпуск";
  dateSelect.appendChild(latestOption);

  archiveIndex.forEach((entry) => {
    const option = document.createElement("option");
    option.value = entry.file;
    option.textContent = `${formatArchiveDate(entry.date)} · ${entry.count}`;
    dateSelect.appendChild(option);
  });
}

async function loadLatest() {
  const payload = await fetchJson(latestUrl);
  updateSummary(payload, "latest");
  dateSelect.value = "latest";
}

async function loadArchiveFile(filePath) {
  const payload = await fetchJson(`./${filePath}`);
  updateSummary(payload, "archive");
}

async function refreshView() {
  refreshButton.disabled = true;
  refreshButton.textContent = "Обновляю...";

  try {
    await loadArchiveIndex();
    await loadLatest();
  } catch (error) {
    generatedAtNode.textContent = "Ошибка загрузки";
    newsListNode.innerHTML = `<div class="empty-state">${error.message}</div>`;
  } finally {
    refreshButton.disabled = false;
    refreshButton.textContent = "Обновить";
  }
}

dateSelect.addEventListener("change", async () => {
  const value = dateSelect.value;
  if (value === "latest") {
    await loadLatest();
    return;
  }

  try {
    await loadArchiveFile(value);
  } catch (error) {
    viewNoteNode.textContent = `Не удалось открыть архив: ${error.message}`;
  }
});

refreshButton.addEventListener("click", refreshView);

window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installPromptEvent = event;
  installButton.classList.remove("hidden");
});

installButton.addEventListener("click", async () => {
  if (!installPromptEvent) {
    return;
  }
  await installPromptEvent.prompt();
  installPromptEvent = null;
  installButton.classList.add("hidden");
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./sw.js");
}

refreshView();
