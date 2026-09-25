/**
 * The user's OpenAI key lives in sessionStorage only: it is scoped to this browser tab and disappears when the tab
 * closes. It is never put in a URL, cookie or localStorage, and is sent solely as the X-OpenAI-Key header.
 */
const KEY = "financial-assistant.openai-key";
const NOTICE = "financial-assistant.landing-notice";

export function getApiKey(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function saveApiKey(key: string): void {
  try {
    sessionStorage.setItem(KEY, key);
  } catch {
    /* storage blocked: the key then only lives for this page load, via the caller */
  }
}

export function clearApiKey(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* nothing to clear */
  }
}

/** A one-shot message for the landing page (e.g. "your key was rejected"). Reading it removes it. */
export function setLandingNotice(message: string): void {
  try {
    sessionStorage.setItem(NOTICE, message);
  } catch {
    /* best effort */
  }
}

export function takeLandingNotice(): string | null {
  try {
    const message = sessionStorage.getItem(NOTICE);
    if (message) sessionStorage.removeItem(NOTICE);
    return message;
  } catch {
    return null;
  }
}
