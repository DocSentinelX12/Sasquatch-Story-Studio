// API client — thin fetch wrapper with honest error surfaces.
export class ApiError extends Error {
  constructor(status, detail, path) {
    const message = typeof detail === "string"
      ? detail
      : (detail && (detail.message || detail.error)) || `Request failed (${status})`;
    super(message);
    this.status = status;
    this.detail = detail;
    this.path = path;
  }
}

export async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch (networkError) {
    throw new ApiError(0, { message: "Cannot reach the studio server. Is it running?" }, path);
  }
  const text = await response.text();
  let payload = null;
  if (text) {
    try { payload = JSON.parse(text); } catch { payload = text; }
  }
  if (!response.ok) {
    throw new ApiError(response.status, payload && payload.detail !== undefined ? payload.detail : payload, path);
  }
  return payload;
}

export const getJSON = (path) => api(path);
export const postJSON = (path, body) =>
  api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
export const patchJSON = (path, body) =>
  api(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
