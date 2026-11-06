import { Check, ClipboardCopy, MessageSquareText, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { type AskVia, deliverAsk } from "../ask";

const FEEDBACK: Record<Exclude<AskVia, "none">, string> = {
  sidecar: "Sent to the Command Center chat",
  agentapi: "Sent to the Command Center chat",
  clipboard: "Copied to clipboard — paste it into the Command Center chat",
};

/**
 * "Ask the Command Center about this Tile": opens a confirm dialog showing the
 * exact prompt, and only sends it on the confirm click. Never shows an error:
 * if every path fails, the dialog stays open with the prompt selected to copy.
 */
export function AskButton({ tileId, prompt }: { tileId: string; prompt: string }) {
  const [shown, setShown] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [via, setVia] = useState<AskVia | null>(null);
  const promptRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    if (via === null || via === "none") return;
    const timer = window.setTimeout(() => setVia(null), 6000);
    return () => window.clearTimeout(timer);
  }, [via]);

  async function confirm() {
    if (shown === null) return;
    setSending(true);
    const result = await deliverAsk(tileId, shown);
    setSending(false);
    setVia(result);
    console.info(`Evidence Board Ask for Tile ${tileId} delivered via: ${result}`);
    if (result === "none") {
      selectPrompt(promptRef.current);
    } else {
      setShown(null);
    }
  }

  return (
    <div className="mt-4 flex flex-wrap items-center gap-3">
      <button
        type="button"
        onClick={() => {
          setVia(null);
          setShown(prompt); // freeze the prompt the presenter is about to confirm
        }}
        className="inline-flex items-center gap-2 rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-base font-medium text-zinc-800 transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
      >
        <MessageSquareText className="size-4" aria-hidden />
        Ask the Command Center about this Tile
      </button>
      {via && via !== "none" ? (
        <span
          role="status"
          data-ask-via={via}
          className="inline-flex items-center gap-1.5 text-base text-emerald-700 dark:text-emerald-400"
        >
          {via === "clipboard" ? (
            <ClipboardCopy className="size-4" aria-hidden />
          ) : (
            <Check className="size-4" aria-hidden />
          )}
          {FEEDBACK[via]}
        </span>
      ) : null}

      {/* Portalled: the Tile's unlock animation transform would trap a fixed overlay. */}
      {shown !== null ? createPortal(
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={`ask-${tileId}-title`}
            className="w-full max-w-2xl rounded-xl border border-zinc-200 bg-white p-5 shadow-xl dark:border-zinc-800 dark:bg-zinc-950"
          >
            <div className="flex items-start justify-between gap-4">
              <h4 id={`ask-${tileId}-title`} className="text-xl font-semibold">
                Send this prompt to the Command Center?
              </h4>
              <button
                type="button"
                aria-label="Cancel"
                onClick={() => setShown(null)}
                className="rounded p-1 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                <X className="size-5" aria-hidden />
              </button>
            </div>
            <pre
              ref={promptRef}
              className="mt-4 max-h-[50vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-zinc-100 p-4 font-mono text-sm text-zinc-800 dark:bg-zinc-900 dark:text-zinc-200"
            >
              {shown}
            </pre>
            {via === "none" ? (
              <p role="status" data-ask-via="none" className="mt-3 text-base text-zinc-700 dark:text-zinc-300">
                Select and copy the prompt above, then paste it into the Command Center chat.
              </p>
            ) : null}
            <div className="mt-5 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setShown(null)}
                className="rounded-lg border border-zinc-300 px-4 py-2 text-base font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={sending}
                onClick={() => void confirm()}
                className="rounded-lg bg-blue-600 px-4 py-2 text-base font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
              >
                {sending ? "Sending…" : "Send to Command Center"}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      ) : null}
    </div>
  );
}

function selectPrompt(node: HTMLElement | null) {
  if (!node) return;
  const range = document.createRange();
  range.selectNodeContents(node);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}
