import { normalizeExtractedStyles } from "./lib/normalize.mjs";
import { generateDesignMarkdown } from "./lib/generate-design-md.mjs";
import { generateSkillMarkdown } from "./lib/generate-skill-md.mjs";
import { validateMarkdownOutput } from "./lib/validate.mjs";

const EXTRACTION_MESSAGE = "TYPEUI_EXTRACT_STYLES";

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.set({
    outputMode: "design"
  });
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || !message.type) {
    return;
  }

  if (message.type === "RUN_EXTRACTION") {
    handleExtraction(message)
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((error) => sendResponse({ ok: false, error: stringifyError(error) }));
    return true;
  }

  if (message.type === "DOWNLOAD_MARKDOWN") {
    handleDownload(message)
      .then((downloadId) => sendResponse({ ok: true, downloadId }))
      .catch((error) => sendResponse({ ok: false, error: stringifyError(error) }));
    return true;
  }
});

async function handleExtraction(message) {
  const mode = message.mode === "skill" ? "skill" : "design";
  const tab = await getActiveTab();
  await injectExtractor(tab.id);
  const payload = await requestExtractionPayload(tab.id);
  const normalized = normalizeExtractedStyles(payload);

  const context = {
    normalized
  };

  const markdown =
    mode === "skill"
      ? generateSkillMarkdown(context)
      : generateDesignMarkdown(context);

  const validation = validateMarkdownOutput(mode, markdown);
  const filename = mode === "skill" ? "SKILL.md" : "DESIGN.md";

  if (message.persistOutputMode !== false) {
    await chrome.storage.local.set({
      outputMode: mode
    });
  }

  return {
    mode,
    filename,
    markdown,
    normalized,
    validation
  };
}

async function handleDownload(message) {
  if (!message.markdown) {
    throw new Error("Cannot download empty markdown.");
  }

  const filename = normalizeMarkdownFilename(message.filename, message.mode);
  const url = `data:text/markdown;charset=utf-8,${encodeURIComponent(message.markdown)}`;
  return chrome.downloads.download({
    url,
    filename,
    saveAs: true,
    conflictAction: "uniquify"
  });
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({
    active: true,
    currentWindow: true
  });
  if (!tab || !tab.id) {
    throw new Error("No active tab available.");
  }
  if (String(tab.url || "").startsWith("chrome://")) {
    throw new Error("Extraction is not available on chrome:// pages.");
  }
  return tab;
}

async function injectExtractor(tabId) {
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["content-script.js"]
  });
}

function requestExtractionPayload(tabId) {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, { type: EXTRACTION_MESSAGE }, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (!response || !response.ok) {
        reject(new Error(response?.error || "No extraction response from tab."));
        return;
      }
      resolve(response.payload);
    });
  });
}

function stringifyError(error) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error || "Unknown error");
}

function normalizeMarkdownFilename(inputName, mode) {
  const normalizedMode = mode === "skill" ? "skill" : "design";
  const fallback = normalizedMode === "skill" ? "SKILL.md" : "DESIGN.md";
  const raw = String(inputName || "").trim();

  if (!raw) {
    return fallback;
  }

  const name = raw.replace(/[\\/]/g, "").trim();
  if (!name) {
    return fallback;
  }

  if (normalizedMode === "skill") {
    if (/^skill(\.md)?$/i.test(name)) {
      return "SKILL.md";
    }
    return name.toLowerCase().endsWith(".md") ? name : `${name}.md`;
  }

  if (/^design(\.md)?$/i.test(name)) {
    return "DESIGN.md";
  }
  return name.toLowerCase().endsWith(".md") ? name : `${name}.md`;
}
