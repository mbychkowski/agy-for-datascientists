/**
 * Delivering a Tile's Ask prompt to the Command Center chat (#97).
 *
 * Paths, tried in order, each falling through silently on any failure:
 * 1. `window.sidecar.agent.sendMessage`: the sidecar preload bridge, when the
 *    host injects it (undocumented, so feature-detected).
 * 2. `POST api/ask`: the board backend runs `agentapi send-message` into the
 *    conversation (sidecar mode only; the standalone backend answers 503).
 * 3. The clipboard, so the presenter can paste the prompt into the chat.
 *
 * A path that times out may still deliver late, so a timeout skips straight to
 * the clipboard rather than risk the prompt landing in the chat twice.
 */

declare global {
  interface Window {
    sidecar?: { agent?: { sendMessage?: (message: string, conversationId?: string) => Promise<unknown> } };
  }
}

export type AskVia = "sidecar" | "agentapi" | "clipboard" | "none";

// The bridge's own timeout; the backend gives agentapi 15 s, so wait a little longer.
const SIDECAR_TIMEOUT_MS = 10_000;
const BACKEND_TIMEOUT_MS = 20_000;

class TimedOut extends Error {}

export async function deliverAsk(tileId: string, prompt: string): Promise<AskVia> {
  const params = new URLSearchParams(window.location.search);
  const conversationId = params.get("conversationId") ?? undefined;
  const send = window.sidecar?.agent?.sendMessage;
  let timedOut = false;
  if (typeof send === "function") {
    try {
      await withTimeout(send.call(window.sidecar?.agent, prompt, conversationId), SIDECAR_TIMEOUT_MS);
      return "sidecar";
    } catch (error) {
      timedOut = error instanceof TimedOut; // else fall through to the backend
    }
  }
  if (!timedOut) {
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      const token = params.get("token");
      if (token) headers["X-Sidecar-Token"] = token;
      const response = await withTimeout(
        fetch("api/ask", {
          method: "POST",
          headers,
          body: JSON.stringify({ tile: tileId, prompt, ...(conversationId ? { conversationId } : {}) }),
        }),
        BACKEND_TIMEOUT_MS,
      );
      if (response.ok) return "agentapi";
    } catch {
      // fall through to the clipboard
    }
  }
  return (await copyToClipboard(prompt)) ? "clipboard" : "none";
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // e.g. an iframe without clipboard permission: try the legacy copy
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    area.remove();
  }
}

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new TimedOut()), ms);
    promise.then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        window.clearTimeout(timer);
        reject(error);
      },
    );
  });
}
