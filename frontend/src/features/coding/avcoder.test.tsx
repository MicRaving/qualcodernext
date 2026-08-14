// @vitest-environment jsdom
/**
 * AvCoder transcript lifecycle after the delete-transcript regression:
 *
 * 1. A media source with a linked (non-empty) transcript renders the
 *    read-only transcript panel.
 * 2. Deleting the transcript clears av_text_id on the LIVE store source
 *    (the CodingWorkspace prop keeps the stale id — the view must NOT
 *    fall back to it), so transcriptId becomes null, the transcript text
 *    disappears and the empty manual transcription editor returns.
 * 3. The header "Transcribe" button stays functional (its eligibility is
 *    the media type, not the transcript) and the TranscribeDialog submits
 *    the transcribe job through api.transcribeStart.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "@/lib/i18n";
import { ToastProvider } from "@/lib/toast";
import { useProjectStore } from "@/stores/project";
import type { Source } from "@/lib/api";
import { AvCoder } from "@/features/coding/AvCoder";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// jsdom does not implement scrollIntoView (the transcript auto-scroll
// effect calls it once a subtitle becomes active).
Element.prototype.scrollIntoView ??= () => {};

const apiMock = vi.hoisted(() => {
  const fns: Record<string, ReturnType<typeof vi.fn>> = {};
  const api = new Proxy({} as Record<string, (...args: unknown[]) => unknown>, {
    get: (_target, prop: string) => {
      fns[prop] ??= vi.fn();
      return fns[prop];
    },
  });
  return { api, fns };
});

vi.mock("@/lib/api", () => ({
  api: apiMock.api,
  sourceFileUrl: (id: number) => `/media/${id}`,
  ApiError: class ApiError extends Error {
    status: number;
    detail: unknown;
    constructor(status: number, message: string, detail?: unknown) {
      super(message);
      this.status = status;
      this.detail = detail;
    }
  },
  fetchWithTimeout: async () => {
    throw new Error("unexpected fetchWithTimeout call");
  },
  initApiBase: async () => "http://mock",
}));

const MEDIA_ID = 1;
const COMPANION_ID = 7;

function mediaSource(avTextId: number | null, hasTranscript: boolean): Source {
  return {
    id: MEDIA_ID,
    name: "talk.mp3",
    fulltext: null,
    mediapath: "/audio/talk.mp3",
    memo: "",
    owner: "default",
    date: "2026-01-01",
    av_text_id: avTextId,
    risid: null,
    media_type: "audio",
    has_transcript: hasTranscript,
  };
}

function companionSource(): Source {
  return {
    id: COMPANION_ID,
    name: "talk.mp3.txt",
    fulltext: "[00:00] Hello world",
    mediapath: null,
    memo: "",
    owner: "default",
    date: "2026-01-01",
    av_text_id: null,
    risid: null,
    media_type: "text",
    has_transcript: false,
  };
}

let currentSources: Source[];

function setupApiMocks() {
  // Ensure every stub exists BEFORE the component touches the api proxy
  // (the proxy's get lazily creates fns, so assertions on fns.* need the
  // entries pre-seeded).
  const fns = apiMock.fns;
  (fns.bookmarks ??= vi.fn()).mockResolvedValue({
    av_bookmark_file_id: null,
    av_bookmark_msec: null,
  });
  (fns.avCodings ??= vi.fn()).mockResolvedValue([]);
  (fns.codesFlat ??= vi.fn()).mockResolvedValue([]);
  (fns.getSource ??= vi.fn()).mockResolvedValue(companionSource());
  (fns.sources ??= vi.fn()).mockImplementation(async () => currentSources);
  (fns.projectSummary ??= vi.fn()).mockResolvedValue({ summary: null });
  (fns.codeTree ??= vi.fn()).mockResolvedValue([]);
  (fns.cases ??= vi.fn()).mockResolvedValue([]);
  (fns.journals ??= vi.fn()).mockResolvedValue([]);
  (fns.deleteTranscript ??= vi.fn()).mockImplementation(async () => {
    // The backend deletes the companion and clears the media source's
    // av_text_id link — the next sources() list reflects that.
    currentSources = [mediaSource(null, false)];
  });
  (fns.transcribeStatus ??= vi.fn()).mockResolvedValue({
    engines: { whisper: true },
    models_cached: ["tiny"],
    model_dir: "/models",
    models: ["tiny", "large-v3-turbo"],
    settings: {
      engine: "whisper",
      model: "large-v3-turbo",
      language: null,
      translate: false,
      beam_size: 5,
      temperature: 0,
      vad: true,
      device: "auto",
      segment_coding: false,
    },
  });
  (fns.transcribeStart ??= vi.fn()).mockResolvedValue({ job_id: "job-1" });
}

function seedStore() {
  useProjectStore.setState({
    projectOpen: true,
    projectName: "test",
    projectPath: "",
    sources: currentSources,
    codeTree: [],
    cases: [],
    journals: [],
    tasks: [],
    summary: null,
  });
}

function findButton(container: HTMLElement, text: string): HTMLButtonElement | null {
  return (
    Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === text,
    ) ?? null
  );
}

function findTranscribeEditor(container: HTMLElement): HTMLTextAreaElement | null {
  return container.querySelector('textarea[aria-label="Transcribe"]');
}

async function flushUi() {
  await act(async () => {});
  await act(async () => {});
}

function renderAvCoder(container: HTMLElement): Root {
  const root = createRoot(container);
  act(() => {
    root.render(
      <I18nProvider>
        <ToastProvider>
          <AvCoder source={currentSources[0]} />
        </ToastProvider>
      </I18nProvider>,
    );
  });
  return root;
}

async function deleteTranscript(container: HTMLElement) {
  const deleteBtn = container.querySelector('button[title="Delete the transcript and its text codings"]');
  expect(deleteBtn).not.toBeNull();
  await act(async () => {
    (deleteBtn as HTMLButtonElement).click();
    // The handler awaits api.deleteTranscript + refreshProject; wait for the
    // store to carry the post-delete source so the re-render lands inside act.
    await vi.waitFor(() => {
      expect(useProjectStore.getState().sources[0].av_text_id).toBeNull();
    });
  });
  await flushUi();
}

describe("AvCoder transcript delete + re-transcription", () => {
  beforeEach(() => {
    currentSources = [mediaSource(COMPANION_ID, true)];
    setupApiMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    seedStore();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("renders the read-only transcript of a linked companion", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = renderAvCoder(container);
    await flushUi();

    // The non-empty transcript is rendered as text…
    await vi.waitFor(() => {
      expect(container.textContent).toContain("Hello world");
    });
    // …the view is read-only (no transcription textarea)…
    expect(findTranscribeEditor(container)).toBeNull();
    // …and the delete-transcript button is present.
    expect(container.querySelector('button[title="Delete the transcript and its text codings"]')).not.toBeNull();
    // The header Transcribe button is media-type-gated and present.
    expect(findButton(container, "Transcribe")).not.toBeNull();

    act(() => root.unmount());
    container.remove();
  });

  it("returns to the empty manual editor after deleting the transcript", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = renderAvCoder(container);
    await flushUi();
    await vi.waitFor(() => {
      expect(container.textContent).toContain("Hello world");
    });

    // The delete handler resets the view: the stale CodingWorkspace prop
    // still carries av_text_id, but the LIVE store source (refreshed by
    // refreshProject) is the source of truth — transcriptId must become
    // null, the transcript text must disappear and the empty manual
    // editor must return.
    await deleteTranscript(container);

    expect(apiMock.fns.deleteTranscript).toHaveBeenCalledWith(MEDIA_ID);
    // The store now holds the post-delete source.
    expect(useProjectStore.getState().sources[0].av_text_id).toBeNull();

    await vi.waitFor(() => {
      expect(container.textContent).not.toContain("Hello world");
    });
    // Empty manual transcription editor is back.
    const editor = findTranscribeEditor(container);
    expect(editor).not.toBeNull();
    expect(editor?.value).toBe("");
    // Transcript-only chrome is gone.
    expect(container.querySelector('button[title="Delete the transcript and its text codings"]')).toBeNull();
    expect(findButton(container, "Autocode")).toBeNull();
    // The header Transcribe button survives the delete (media-type gate).
    expect(findButton(container, "Transcribe")).not.toBeNull();

    act(() => root.unmount());
    container.remove();
  });

  it("submits an automatic transcription job after the transcript was deleted", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = renderAvCoder(container);
    await flushUi();
    await vi.waitFor(() => {
      expect(container.textContent).toContain("Hello world");
    });

    await deleteTranscript(container);
    await vi.waitFor(() => {
      expect(findTranscribeEditor(container)).not.toBeNull();
    });

    // Open the automatic transcription dialog via the header button.
    const transcribeBtn = findButton(container, "Transcribe");
    expect(transcribeBtn).not.toBeNull();
    await act(async () => {
      (transcribeBtn as HTMLButtonElement).click();
    });
    await flushUi();

    const dialog = container.querySelector('[role="dialog"][aria-label="Transcribe audio/video"]');
    expect(dialog).not.toBeNull();

    const startBtn = Array.from(dialog!.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === "Start transcription",
    );
    expect(startBtn).not.toBeNull();
    await act(async () => {
      (startBtn as HTMLButtonElement).click();
      // The submit handler awaits api.transcribeStart and enqueues the job
      // before closing the dialog — wait for it inside act.
      await vi.waitFor(() => {
        expect(apiMock.fns.transcribeStart).toHaveBeenCalled();
      });
    });
    await flushUi();

    // The job POST fires through the api call path with the media source.
    expect(apiMock.fns.transcribeStart).toHaveBeenCalledTimes(1);
    expect(apiMock.fns.transcribeStart).toHaveBeenCalledWith(
      expect.objectContaining({ source_id: MEDIA_ID }),
    );
    // The job enters the task queue and the dialog closes.
    expect(useProjectStore.getState().tasks).toHaveLength(1);
    expect(useProjectStore.getState().tasks[0]).toMatchObject({
      kind: "transcribe",
      sourceId: MEDIA_ID,
      id: "job-1",
      state: "running",
    });
    await vi.waitFor(() => {
      expect(container.querySelector('[role="dialog"]')).toBeNull();
    });

    act(() => root.unmount());
    container.remove();
  });
});
