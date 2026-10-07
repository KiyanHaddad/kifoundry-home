/** Origin-scoped proof supplements cookies, which browsers share across ports. */
const PROOF_KEY = 'kifoundry-home:session-proof';

export function readSessionProof() {
  try { return sessionStorage.getItem(PROOF_KEY) || ''; }
  catch { return ''; }
}

export function saveSessionProof(proof) {
  try { sessionStorage.setItem(PROOF_KEY, proof); }
  catch { /* Current-tab memory still works; reopen with the launcher after reload. */ }
}

/** Each transport operation has a finite wait, including reading its JSON body. */
export async function requestJSON(path, { body, csrf = '', headers = {}, timeoutMs = 15000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const options = {
    credentials: 'same-origin', signal: controller.signal,
    headers: { Accept: 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}), ...headers },
  };
  if (body !== undefined) {
    options.method = 'POST';
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  try {
    let response;
    try { response = await fetch(path, options); }
    catch {
      throw new Error(controller.signal.aborted ?
        'The request timed out. Your draft is kept. Reconnect to check saved progress before retrying.' :
        'The connection was lost. Your draft is still here.');
    }
    let result;
    try { result = await response.json(); }
    catch {
      throw new Error(controller.signal.aborted ?
        'The request timed out. Reconnect to check saved progress before retrying.' :
        'The home returned an unreadable response. Your draft is kept.');
    }
    if (!response.ok) {
      const error = new Error(typeof result?.error === 'string' ? result.error : 'That request could not be completed.');
      error.status = response.status;
      throw error;
    }
    return result;
  } finally { clearTimeout(timer); }
}
