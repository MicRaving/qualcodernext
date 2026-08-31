/**
 * SelectionToolbar — floating coding toolbar for a text selection: pick a
 * code (the primary button always opens the code-selection flyout, which
 * can also create new codes), segment links (copy / paste) and "send to
 * QTT". Owns ALL popover state (QTT sheet picker, code picker) and every
 * mutation it triggers, so any coder surface can reuse it — the text coder
 * and the CSV table view both mount it next to their selection.
 *
 * Memos are NOT edited here: clicking an already-coded segment opens its
 * memo editor instead (see the coders' memo gutter / bubble).
 *
 * Contract with the host:
 * - `anchor` / `selection` — where to show the popup and what it operates
 *   on (selection is in document-text coordinates). The component stays
 *   mounted when `anchor` is null so the code-picker modal survives outside
 *   clicks — the host only hides the popup via `onHide`.
 * - `refreshCodings` must return the FRESH coding list (it also updates the
 *   host state) so `onCoded` can highlight the just-created segment.
 * - `onChanged` reloads annotations/codes/links after non-coding mutations.
 */
import { errorMessage } from "@/lib/utils";
import { useEffect, useRef, useState } from "react";
import { useAsyncEffect } from "@/lib/useAsync";
import { Check, Code, Link as LinkIcon, LoaderCircle, ScrollText } from "lucide-react";
import { Button, Menu, MenuItem } from "@/components/ui/orchestrator";
import { api, type CodeTreeItem, type Coding } from "@/lib/api";
import { CodePicker, type PickedCode } from "@/features/coding/CodePicker";
import { listQttSheets, sendSegmentToQtt, type QttSheet } from "@/lib/qttApi";
import {
  copyLinkPayload,
  createLink,
  readLinkPayload,
  type LinkSpanTarget,
} from "@/features/coding/links";
import { useWorkspaceStore } from "@/stores/workspace";
import { useI18n } from "@/lib/i18n";
import { cls } from "@/components/ui/tokens";

export interface SelectionToolbarProps {
  /** Popup position; null hides the popup (the component stays mounted so
   *  the code-picker modal survives outside clicks). */
  anchor: { left: number; top: number } | null;
  /** Current selection in document-text coordinates (null = none). */
  selection: { pos0: number; pos1: number; text: string } | null;
  /** The file being coded. */
  fid: number;
  /** Flat code list — picker, names, in-vivo categories. */
  codes: CodeTreeItem[];
  /** Reload the codings (returns the fresh list — updates host state too). */
  refreshCodings: () => Promise<Coding[]>;
  /** Called after a coding was created with the fresh codings, so the host
   *  can highlight the new segment (e.g. auto-show details). */
  onCoded?: (created: Coding, next: Coding[]) => void;
  /** Reload annotations/codes/links after non-coding mutations. */
  onChanged: () => void;
  /** Hide the popup only — the selection stays (outside click). */
  onHide: () => void;
  /** Clear the host selection (after a completed action). */
  onClose: () => void;
  /** Surface an error to the host. */
  onError: (msg: string) => void;
}

export function SelectionToolbar({
  anchor,
  selection,
  fid,
  codes,
  refreshCodings,
  onCoded,
  onChanged,
  onHide,
  onClose,
  onError,
}: SelectionToolbarProps) {
  const { t } = useI18n();

  const [pickerOpen, setPickerOpen] = useState(false);

  /* Segment links: whether a qcnext-link payload is on the clipboard (the
     "Paste link here" button) + a transient "copied" feedback. */
  const [clipboardLink, setClipboardLink] = useState<LinkSpanTarget | null>(null);
  const [linkCopied, setLinkCopied] = useState(false);
  const linkCopiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  /* "Send to QTT": pick a worksheet in a small inline menu and store the
     selected span as a segment item (transient "sent" feedback). */
  const [qttOpen, setQttOpen] = useState(false);
  const [qttSheets, setQttSheets] = useState<QttSheet[]>([]);
  const [qttLoading, setQttLoading] = useState(false);
  const [qttSending, setQttSending] = useState<number | null>(null);
  const [qttSent, setQttSent] = useState(false);
  const qttSentTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const popupRef = useRef<HTMLDivElement | null>(null);

  useEffect(
    () => () => {
      if (linkCopiedTimer.current) clearTimeout(linkCopiedTimer.current);
      if (qttSentTimer.current) clearTimeout(qttSentTimer.current);
    },
    [],
  );

  /* A NEW selection always opens the helper bar fresh — no popover state
     (QTT worksheet menu) may leak from the previous selection. */
  useEffect(() => {
    setQttOpen(false);
    setQttSent(false);
  }, [selection?.pos0, selection?.pos1]);

  /* ------------------------------------------------------------------ ops */

  /** Code the pending selection with the given code id. Resolves when the
   *  coding exists and the host state is fresh (or the error was reported). */
  async function codeSelection(cid: number): Promise<void> {
    const sel = selection;
    if (!sel) return;
    try {
      const created = await api.createTextCoding({
        cid,
        fid,
        seltext: sel.text,
        pos0: sel.pos0,
        pos1: sel.pos1,
      });
      const next = await refreshCodings();
      onCoded?.(created, next);
      onChanged();
      onClose();
    } catch (e) {
      // Keep the selection so the user can retry without re-selecting.
      onError(errorMessage(e, t("coder.createError")));
    }
  }

  /** Code the pending selection with SEVERAL codes (multi-pick): create all
   *  codings sequentially (so failures are attributable) and refresh the
   *  host exactly once. */
  async function codeSelectionMany(cids: number[]): Promise<void> {
    const sel = selection;
    if (!sel || cids.length === 0) return;
    const created: Coding[] = [];
    let failed = 0;
    for (const cid of cids) {
      try {
        created.push(
          await api.createTextCoding({
            cid,
            fid,
            seltext: sel.text,
            pos0: sel.pos0,
            pos1: sel.pos1,
          }),
        );
      } catch (e) {
        failed += 1;
        onError(errorMessage(e, t("coder.createError")));
      }
    }
    if (created.length > 0) {
      const next = await refreshCodings();
      onCoded?.(created[created.length - 1], next);
      onChanged();
    }
    if (failed === 0) onClose();
  }

  function copySegmentLink() {
    const sel = selection;
    if (!sel) return;
    void (async () => {
      try {
        await copyLinkPayload(fid, sel.pos0, sel.pos1);
        setClipboardLink({ fid, pos0: sel.pos0, pos1: sel.pos1 });
        setLinkCopied(true);
        if (linkCopiedTimer.current) clearTimeout(linkCopiedTimer.current);
        linkCopiedTimer.current = setTimeout(() => setLinkCopied(false), 1500);
      } catch (e) {
        onError(errorMessage(e, t("coder.linkCopyError")));
      }
    })();
  }

  /** Create one link from the current selection to the copied segment. */
  function pasteSegmentLink() {
    const sel = selection;
    const target = clipboardLink;
    if (!sel || !target) return;
    void (async () => {
      try {
        await createLink({
          from_fid: fid,
          from_pos0: sel.pos0,
          from_pos1: sel.pos1,
          to_fid: target.fid,
          to_pos0: target.pos0,
          to_pos1: target.pos1,
        });
        onChanged();
        onClose();
      } catch (e) {
        // Keep the selection so the user can retry without re-selecting.
        onError(errorMessage(e, t("coder.linkCreateError")));
      }
    })();
  }

  /** Open the worksheet picker for the current selection. */
  function openQttPicker() {
    setQttOpen(true);
    setQttLoading(true);
    void listQttSheets()
      .then((sheets) => setQttSheets(sheets))
      .catch((e) => {
        onError(errorMessage(e, t("qtt.sendError")));
        setQttOpen(false);
      })
      .finally(() => setQttLoading(false));
  }

  /** Store the selected span as a segment item on the given worksheet. The
   *  selection stays put so the "sent" feedback remains visible. */
  function sendSelectionToSheet(sheet: QttSheet) {
    const sel = selection;
    if (!sel || qttSending != null) return;
    setQttSending(sheet.id);
    void (async () => {
      try {
        await sendSegmentToQtt(sheet.id, {
          fid,
          pos0: sel.pos0,
          pos1: sel.pos1,
        });
        setQttOpen(false);
        setQttSent(true);
        if (qttSentTimer.current) clearTimeout(qttSentTimer.current);
        qttSentTimer.current = setTimeout(() => setQttSent(false), 1500);
        // An open QTT workspace refreshes its sheets/items.
        const { qttUi, setQttUi } = useWorkspaceStore.getState();
        setQttUi({ tick: qttUi.tick + 1 });
      } catch (e) {
        onError(errorMessage(e, t("qtt.sendError")));
      } finally {
        setQttSending(null);
      }
    })();
  }

  /* ------------------------------------------------------------ listeners */

  // Clicking a code in the left sidebar assigns it to the selected part.
  useEffect(() => {
    const onAssign = (e: Event) => {
      const cid = (e as CustomEvent<{ cid: number }>).detail?.cid;
      if (typeof cid !== "number") return;
      setPickerOpen(false);
      void codeSelection(cid);
    };
    window.addEventListener("qc:assign-code", onAssign);
    return () => window.removeEventListener("qc:assign-code", onAssign);
  });

  // Track whether a qcnext-link payload is on the clipboard so the toolbar
  // can offer "Paste link here".
  useAsyncEffect(async (signal) => {
    const target = await readLinkPayload();
    signal.throwIfAborted();
    setClipboardLink(target);
  }, [selection]);

  // Escape closes the inner popovers FIRST — capture phase + stop
  // immediate propagation, so the host's own Escape handler (which clears
  // the whole selection) never fires while a popover is open. Without a
  // popover open, the host closes the popup and selection itself.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (qttOpen) {
        setQttOpen(false);
        e.stopImmediatePropagation();
        return;
      }
      if (pickerOpen) {
        setPickerOpen(false);
        e.stopImmediatePropagation();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [qttOpen, pickerOpen]);

  // Clicking outside the popup hides it (the code picker is a modal and
  // survives — matches the popup/selection split the host expects).
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const target = e.target instanceof Node ? e.target : null;
      if (!target) return;
      if (!popupRef.current?.contains(target)) onHide();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onHide]);

  /* -------------------------------------------------------------- rendering */

  const popupVisible = anchor != null && selection != null;

  return (
    <>
      {popupVisible && (
        <div
          ref={popupRef}
          className="fixed z-40 qc-enter"
          style={{ left: anchor.left, top: anchor.top }}
        >
          {qttOpen ? (
            <Menu role="menu" className="w-64" aria-label={t("qtt.sendTitle")}>
              <div className="border-b border-border px-2 py-1 text-[11px] font-medium uppercase tracking-wide text-text-secondary">
                {t("qtt.sendTitle")}
              </div>
              {qttLoading ? (
                <div className="flex items-center gap-1.5 px-2 py-2 text-xs text-text-secondary">
                  <LoaderCircle size={12} className="animate-spin" aria-hidden />
                  {t("qtt.loading")}
                </div>
              ) : qttSheets.length === 0 ? (
                <div className="px-2 py-2 text-xs text-text-secondary">{t("qtt.sendEmpty")}</div>
              ) : (
                qttSheets.map((sheet) => (
                  <MenuItem
                    key={sheet.id}
                    role="menuitem"
                    disabled={qttSending != null}
                    onClick={() => sendSelectionToSheet(sheet)}
                    className={qttSending === sheet.id ? "opacity-60" : ""}
                  >
                    {qttSending === sheet.id ? (
                      <LoaderCircle size={12} className="animate-spin" aria-hidden />
                    ) : (
                      <ScrollText size={12} aria-hidden />
                    )}
                    <span className="min-w-0 flex-1 truncate">{sheet.name}</span>
                    <span className="shrink-0 rounded-sm bg-surface-higher px-1 py-px text-[10px] font-medium uppercase text-text-secondary">
                      {sheet.kind === "mixed" ? t("qtt.kindMixed") : t("qtt.kindQual")}
                    </span>
                  </MenuItem>
                ))
              )}
            </Menu>
          ) : (
            <div
              className={`flex items-center gap-1 p-1 ${cls.popup}`}
              role="toolbar"
              aria-label={t("coder.selectionActions")}
            >
              <Button
                variant="primary"
                icon={<Code size={12} aria-hidden />}
                className="max-w-56"
                onClick={() => setPickerOpen(true)}
                title={t("coder.pickCode")}
              >
                <span className="truncate">{t("coder.codeAction")}</span>
              </Button>
              <Button
                variant="secondary"
                icon={<LinkIcon size={12} aria-hidden />}
                onClick={copySegmentLink}
                title={t("coder.linkCopied")}
              >
                {linkCopied ? t("coder.copyLinkDone") : t("coder.copyLink")}
              </Button>
              {clipboardLink && (
                <Button
                  variant="secondary"
                  icon={<LinkIcon size={12} aria-hidden />}
                  onClick={pasteSegmentLink}
                  title={t("coder.linkCopied")}
                >
                  {t("coder.pasteLinkHere")}
                </Button>
              )}
              <Button
                variant="secondary"
                icon={
                  qttSent ? <Check size={12} aria-hidden /> : <ScrollText size={12} aria-hidden />
                }
                onClick={openQttPicker}
                title={t("qtt.sendTitle")}
              >
                {qttSent ? t("qtt.sendDone") : t("qtt.send")}
              </Button>
            </div>
          )}
        </div>
      )}

      <CodePicker
        open={pickerOpen}
        codes={codes}
        onClose={() => setPickerOpen(false)}
        onPick={(picked: PickedCode[]) => {
          setPickerOpen(false);
          void codeSelectionMany(picked.map((p) => p.cid));
        }}
      />
    </>
  );
}
