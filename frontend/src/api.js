export const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api";

async function request(path, options = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    },
    ...options
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || "Request failed");
  }
  return response.json();
}

export function fetchDocuments() {
  return request("/documents");
}

export function askPolicy(payload) {
  return request("/ask", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function comparePolicies(payload) {
  return request("/compare", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function diffPolicies(payload) {
  return request("/changes", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function buildIndexes(payload) {
  return request("/index/build", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function fetchIndexSettings() {
  return request("/index/settings");
}

export function updateIndexSettings(payload) {
  return request("/index/settings", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function fetchGraphStatus() {
  return request("/graph/status");
}

export function fetchHistory() {
  return request("/history");
}

export function fetchHistoryDetail(historyId) {
  return request(`/history/${historyId}`);
}

export function clearHistory() {
  return request("/history", {
    method: "DELETE"
  });
}

export function fetchEvidenceSummary(payload) {
  return request("/evidence/summary", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function documentPdfUrl(docId, page = 1) {
  return `${API_URL}/documents/${docId}/pdf#page=${page}`;
}

export async function uploadDocument(file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(`${API_URL}/documents/upload`, {
    method: "POST",
    body: formData
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || "Upload failed");
  }
  return response.json();
}
