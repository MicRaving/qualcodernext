/**
 * Typed API client for the QualCoder v4 backend (FastAPI).
 *
 * The backend listens on localhost:8765 (dev default). All requests are
 * JSON; errors are normalized into `ApiError`.
 *
 * In the packaged (Tauri) app the backend may have fallen back to an
 * ephemeral port (two instances cannot share 8765) — the shell exposes the
 * actual port via the `backend_port` command and the base URL is resolved
 * lazily on first use.
 */

let resolvedBase: string | null = null;
let basePromise: Promise<string> | null = null;

const DEV_FALLBACK = import.meta.env.VITE_API_BASE ?? "http://localhost:8765/api/v1";

function resolveBase(): Promise<string> {
  if (!basePromise) {
    basePromise = (async () => {
      if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
        try {
          const core = await import("@tauri-apps/api/core");
          // The embedded backend takes ~10s to start; its port file appears
          // late, so retry the resolution instead of falling back early.
          for (let i = 0; i < 20; i++) {
            try {
              const port = await core.invoke<number>("backend_port");
              if (typeof port === "number" && port > 0) {
                return `http://127.0.0.1:${port}/api/v1`;
              }
            } catch {
              /* not in the Tauri shell — use the dev default */
            }
            await new Promise((r) => setTimeout(r, 1000));
          }
        } catch {
          /* fall through to the dev default */
        }
      }
      return DEV_FALLBACK;
    })();
  }
  return basePromise;
}

/** Kick off base-URL resolution at startup (sync callers then see the port). */
export function initApiBase(): Promise<string> {
  return resolveBase().then((base) => {
    resolvedBase = base;
    return base;
  });
}

/** Synchronous base URL for URL helpers (img/video/audio sources). */
function apiBaseSync(): string {
  return resolvedBase ?? DEV_FALLBACK;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const base = await resolveBase();
  resolvedBase = base;
  const res = await fetch(`${base}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* non-JSON error body */
    }
    const suffix = typeof detail === "string" && detail ? `: ${detail}` : "";
    throw new ApiError(res.status, `API error ${res.status} on ${path}${suffix}`, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** URL to the raw source file bytes (used as img/video/pdf src). */
export function sourceFileUrl(sourceId: number): string {
  return `${apiBaseSync()}/sources/${sourceId}/file`;
}

/** URL to a generated thumbnail (PNG) for image/PDF sources. */
export function thumbnailUrl(sourceId: number, maxSize = 300): string {
  return `${apiBaseSync()}/sources/${sourceId}/thumbnail?max_size=${maxSize}`;
}

export interface HealthStatus {
  status: string;
  version?: string;
}

export interface ProjectSummary {
  databaseversion: string;
  project_date: string;
  project_memo: string;
  about: string;
  bookmark_file_id: number | null;
  bookmark_pos: number | null;
  files_count: number;
  cases_count: number;
  code_categories_count: number;
  codes_count: number;
  attributes_count: number;
  journals_count: number;
  bookmark_filename: string | null;
}

export interface OpenProjectResult {
  ok: boolean;
  project_path: string;
  project_name: string;
  migrations_applied: string[];
  error: string;
  lock_user: string;
}

export interface Source {
  id: number;
  name: string;
  fulltext: string | null;
  mediapath: string | null;
  memo: string;
  owner: string;
  date: string;
  av_text_id: number | null;
  risid: number | null;
  media_type: "text" | "pdf" | "image" | "audio" | "video";
}

export interface CodeTreeItem {
  kind: "category" | "code";
  id: number;
  name: string;
  color: string | null;
  parent_id: number | null;
  memo: string;
  subcode?: boolean;
}

export interface Code {
  cid: number;
  name: string;
  memo: string;
  catid: number | null;
  owner: string;
  date: string;
  color: string | null;
  supercid?: number | null;
}

export interface CodeExample {
  ctid: number;
  file_name: string;
  seltext: string;
  pos0: number;
  pos1: number;
}

export interface CodeDetails {
  code: Code;
  category_path: string[];
  coding_count: number;
  file_count: number;
  recent_examples: CodeExample[];
}

export interface SourceDetails {
  source: Source;
  text_codings: number;
  image_codings: number;
  av_codings: number;
  codes_used: { cid: number; name: string; color: string | null; count: number }[];
  cases: { caseid: number; name: string }[];
  attributes: { name: string; value: string; attr_type: string }[];
}

export interface Case {
  caseid: number;
  name: string;
  memo: string;
  owner: string;
  date: string;
}

export interface CaseFileLink {
  id: number;
  name: string;
  mediapath: string | null;
  memo: string;
  date: string;
}

export interface AttributeType {
  name: string;
  date: string;
  owner: string;
  memo: string;
  case_or_file: string;
  value_type: string;
}

export interface AttributeValue {
  attrid: number;
  name: string;
  attr_type: string;
  value: string;
  id: number;
  date: string;
  owner: string;
}

export interface Journal {
  jid: number;
  name: string;
  jentry: string;
  date: string;
  owner: string;
}

// --- Reports -----------------------------------------------------------

export interface CodeFrequencyRow {
  cid: number;
  name: string;
  color: string | null;
  category: string;
  count: number;
}

export interface CodesBySegmentRow {
  ctid: number;
  file_name: string;
  code_name: string;
  category: string;
  seltext: string;
  owner: string;
  date: string;
}

export interface ComparisonTable {
  files: { fid: number; name: string }[];
  codes: { cid: number; name: string; color: string | null }[];
  counts: number[][];
}

export interface CooccurrenceTable {
  codes: { cid: number; name: string; color: string | null }[];
  counts: number[][];
}

export interface ExactMatchRow {
  seltext: string;
  count: number;
  files: string[];
}

export interface FileSummaryRow {
  fid: number;
  name: string;
  media_type: string;
  codes_count: number;
  segments_count: number;
  cases: string[];
  words: number;
}

export interface CoderComparisonRow {
  owner: string;
  codings_count: number;
  files_count: number;
}

export interface AttributeReportRow {
  name: string;
  value: string;
  attr_type: string;
  entity_kind: string;
  entity_name: string;
}

export interface InterraterResult {
  coder_a: string;
  coder_b: string;
  n_units: number;
  n_categories: number;
  n_pairs: number;
  both: number;
  only_a: number;
  only_b: number;
  neither: number;
  kappa: number | null;
  krippendorff: number | null;
  gwet_ac1: number | null;
}

export interface Coding {
  ctid: number;
  cid: number;
  fid: number;
  seltext: string;
  pos0: number;
  pos1: number;
  owner: string;
  date: string;
  memo: string;
  avid: number | null;
  important: number;
}

export interface ImageCoding {
  imid: number;
  id: number;
  x1: number;
  y1: number;
  width: number;
  height: number;
  cid: number;
  memo: string;
  date: string;
  owner: string;
  important: number;
  pdf_page: number | null;
}

export interface AVCoding {
  avid: number;
  id: number;
  pos0: number;
  pos1: number;
  cid: number;
  memo: string;
  date: string;
  owner: string;
  important: number;
}

export interface Annotation {
  anid: number;
  fid: number;
  pos0: number;
  pos1: number;
  memo: string;
  owner: string;
  date: string;
}

export interface CaseTextSpan {
  id: number;
  caseid: number;
  fid: number;
  pos0: number;
  pos1: number;
  owner: string;
  date: string;
  memo: string;
}

/** One shifted segment returned by the shift-positions endpoint. */
export interface ShiftedSegment {
  newpos0: number;
  newpos1: number;
}

export interface ShiftPositionsResponse {
  codings: (ShiftedSegment & { ctid?: number })[];
  annotations: (ShiftedSegment & { anid?: number })[];
  case_text: (ShiftedSegment & { id?: number })[];
  deletions: { code_text: number[]; annotation: number[]; case_text: number[] };
}

export interface CommitEditResponse {
  updated: { code_text: number; annotation: number; case_text: number };
  deleted: { code_text: number[]; annotation: number[]; case_text: number[] };
}

export interface AutocodeResponse {
  created: Coding[];
  count: number;
}

export interface UndoCodingsResponse {
  restored: number;
}

// --- AI assistant -----------------------------------------------------

export interface AiStatus {
  enabled: boolean;
  configured: boolean;
  reason: string;
  provider: string;
  base_url: string;
  model: string;
  mcp_permissions?: string;
}

export interface AiChatReply {
  reply: string;
  model: string;
}

export interface AiSearchResult {
  source_id: number;
  file_name: string;
  text: string;
  score: number;
}

export interface AiPromptInfo {
  id: string;
  mode: string;
  name: string;
  description: string;
}

export interface AiIndexStatus {
  indexed: boolean;
  model: string;
  chunks: number;
}

export interface Pseudonym {
  original: string;
  pseudonym: string;
}

export interface SpeakerTurn {
  name: string;
  fid: number;
  filename: string;
  seltext: string;
  seltext_response: string;
  pos0: number;
  pos1: number;
}

export interface SpeakerInfo {
  name: string;
  count: number;
  files: string[];
  example: string;
}

export interface ReferenceEntry {
  risid: number;
  title: string;
  authors: string[];
  year: string;
  type: string;
  fields: Record<string, string[]>;
  sources: { id: number; name: string }[];
}

export interface BadLink {
  id: number;
  name: string;
  kind: string;
  path: string;
  exists: boolean;
  mediapath: string;
}

export interface FileFilter {
  filterid: number;
  name: string;
  filter: string;
  owner: string;
}

export interface Bookmarks {
  bookmark_file_id: number | null;
  bookmark_pos: number | null;
  av_bookmark_file_id: number | null;
  av_bookmark_msec: number | null;
  av_bookmark_textpos: number | null;
}

export interface CodeSegmentRow {
  kind: "text" | "image" | "av";
  id: number;
  file_name: string;
  seltext?: string;
  pos0?: number;
  pos1?: number;
  x1?: number;
  y1?: number;
  width?: number;
  height?: number;
  pdf_page?: number | null;
  owner: string;
  memo: string;
}

export interface CodeSummary {
  cid: number;
  name: string;
  memo: string;
  color: string;
  categories: string[];
  counts: { text: number; image: number; av: number };
  total: number;
  files: string[];
  file_count: number;
}

export interface CoderFileComparison {
  coder_a: string;
  coder_b: string;
  files: {
    file_name: string;
    coder_a_count: number;
    coder_b_count: number;
    segments_a: { cid: number; code_name: string; seltext: string; pos0: number; pos1: number }[];
    segments_b: { cid: number; code_name: string; seltext: string; pos0: number; pos1: number }[];
  }[];
  total_a: number;
  total_b: number;
}

export interface CodeRelation {
  code_a: string;
  code_b: string;
  count: number;
}

export interface WordFrequencyRow {
  word: string;
  count: number;
}

export interface ChartSeries {
  cid: number;
  name: string;
  color: string;
  count?: number;
  cumulative?: number;
}

export interface ChartMatrix {
  kind: string;
  files?: { fid: number; name: string }[];
  cases?: { caseid: number; name: string }[];
  labels?: { fid?: number; caseid?: number; name: string }[];
  codes: ChartSeries[];
  counts?: number[][];
  series?: { cid: number; count: number }[][];
  rows?: { cid: number; name: string; color: string; value: number }[];
}

// --- Interchange (REFI-QDA etc.) --------------------------------------

export interface InterchangeResult {
  ok: boolean;
  message?: string;
  codes?: number;
  categories?: number;
  sources?: number;
  codings?: number;
  cases?: number;
  references?: number;
  attributes?: number;
}

// --- SQL console -------------------------------------------------------

export interface SqlResult {
  columns: string[];
  rows: unknown[][];
  truncated?: boolean;
}

export interface SavedQuery {
  title: string;
  description: string;
  grouper: string;
  ssql: string;
}

// --- Audit / history ---------------------------------------------------

export interface AuditRow {
  id: number;
  ts: string;
  user: string;
  action: string;
  entity: string;
  entity_id: number | null;
  source_id: number | null;
  detail: Record<string, unknown>;
}

export interface AuditResponse {
  rows: AuditRow[];
  total: number;
}

export interface AuditStatsRow {
  action: string;
  count: number;
}

// --- Transcription -----------------------------------------------------

export interface TranscribeStatus {
  engines: { whisper: boolean; noscribe: boolean };
  models_cached: string[];
  model_dir: string;
  models: string[];
  settings: TranscribeSettings;
}

export interface TranscribeSettings {
  engine: string;
  model: string;
  language: string | null;
  translate: boolean;
  beam_size: number;
  temperature: number;
  vad: boolean;
  device: string;
  segment_coding: boolean;
}

export interface TranscribeJob {
  id: string;
  state: "running" | "done" | "error";
  progress: number;
  message: string;
  segments: number;
  error: string | null;
  transcript_source_id?: number | null;
  result?: { start: number; end: number; text: string }[] | null;
}

export interface CoderInfo {
  name: string;
  coding_count: number;
}

export interface CodersResponse {
  current: string;
  coders: CoderInfo[];
}

// --- Graphs (code-map editor) -----------------------------------------

export interface GraphSummary {
  grid: number;
  name: string;
  description: string;
  date: string;
  scene_width: number;
  scene_height: number;
}

export interface CdctItem {
  gtextid: number;
  grid: number;
  x: number;
  y: number;
  supercatid: number | null;
  catid: number | null;
  cid: number | null;
  font_size: number;
  bold: number;
  isvisible: number;
  displaytext: string;
}

export interface CaseItem {
  gcaseid: number;
  grid: number;
  x: number;
  y: number;
  caseid: number;
  font_size: number;
  bold: number;
  color: string | null;
  displaytext: string;
}

export interface FileItem {
  gfileid: number;
  grid: number;
  x: number;
  y: number;
  fid: number;
  font_size: number;
  bold: number;
  color: string | null;
  displaytext: string;
}

export interface FreeItem {
  gfreeid: number;
  grid: number;
  freetextid: number;
  x: number;
  y: number;
  free_text: string;
  color: string | null;
  font_size: number;
  bold: number;
}

export interface MemoItem {
  gmemoid: number;
  grid: number;
  memo_source_type: string;
  memo_source_id: number;
  x: number;
  y: number;
  color: string | null;
  font_size: number;
}

export interface CdctLine {
  glineid: number;
  grid: number;
  fromcatid: number | null;
  fromcid: number | null;
  tocatid: number | null;
  tocid: number | null;
  color: string | null;
  linewidth: number;
  linetype: string | null;
  isvisible: number;
  label: string | null;
  arrow_mode: string | null;
}

export interface FreeLine {
  gflineid: number;
  grid: number;
  fromfreetextid: number | null;
  fromcatid: number | null;
  fromcid: number | null;
  fromcaseid: number | null;
  fromfileid: number | null;
  fromimid: number | null;
  fromavid: number | null;
  tofreetextid: number | null;
  tocatid: number | null;
  tocid: number | null;
  tocaseid: number | null;
  tofileid: number | null;
  toimid: number | null;
  toavid: number | null;
  color: string | null;
  linewidth: number;
  linetype: string | null;
  label: string | null;
  arrow_mode: string | null;
}

export interface GraphData {
  graph: GraphSummary;
  cdct_items: CdctItem[];
  case_items: CaseItem[];
  file_items: FileItem[];
  free_items: FreeItem[];
  memo_items: MemoItem[];
  cdct_lines: CdctLine[];
  free_lines: FreeLine[];
  categories: { catid: number; name: string; supercatid: number | null }[];
  codes: { cid: number; name: string; color: string | null; catid: number | null; supercid: number | null; memo: string | null }[];
  cases: { caseid: number; name: string }[];
  sources: { id: number; name: string }[];
}

export interface ColorScheme {
  colors: string[];
  ranges: { name: string; min: number; max: number }[];
}

export const GRAPH_MODELS = [
  "category-hierarchy",
  "file-hierarchy",
  "file-comparison",
  "case-hierarchy",
  "case-comparison",
  "cooccurrence-network",
] as const;

export const api = {
  health: () => request<HealthStatus>("/health"),

  recentProjects: () => request<{ recent: string[] }>("/projects"),
  createProject: (project_path: string, codername?: string) =>
    request<OpenProjectResult>("/projects", {
      method: "POST",
      body: JSON.stringify({ project_path, codername }),
    }),
  openProject: (project_path: string, codername?: string) =>
    request<OpenProjectResult>("/projects/open", {
      method: "POST",
      body: JSON.stringify({ project_path, codername }),
    }),
  closeProject: () => request<OpenProjectResult>("/projects/close", { method: "POST" }),
  projectSummary: () => request<{ summary: ProjectSummary }>("/projects/current/summary"),
  projectOpeners: () => request<{ openers: { user: string; pid: number; ts: number }[] }>("/projects/openers"),

  // --- Coders ------------------------------------------------------------

  coders: () => request<CodersResponse>("/coders"),
  createCoder: (name: string) =>
    request<CodersResponse>("/coders", { method: "POST", body: JSON.stringify({ name }) }),
  switchCoder: (name: string) =>
    request<CodersResponse>("/coders/current", {
      method: "PUT",
      body: JSON.stringify({ name }),
    }),
  deleteCoder: (name: string, reassign_to?: string) =>
    request<CodersResponse>(`/coders/${encodeURIComponent(name)}`, {
      method: "DELETE",
      body: JSON.stringify({ reassign_to }),
    }),
  coderVisibility: () => request<{ visibility: Record<string, number> }>("/coders/visibility"),
  setCoderVisibility: (name: string, visible: boolean) =>
    request<{ ok: boolean }>(`/coders/${encodeURIComponent(name)}/visibility`, {
      method: "PUT",
      body: JSON.stringify({ visible }),
    }),

  sources: () => request<Source[]>("/sources"),
  getSource: (id: number) => request<Source>(`/sources/${id}`),
  importSource: (file: File, owner?: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("owner", owner ?? "");
    return fetch(`${apiBaseSync()}/sources/import`, { method: "POST", body: form }).then(
      handleJson<Source>,
    );
  },
  deleteSource: (id: number) => request<void>(`/sources/${id}`, { method: "DELETE" }),
  patchSource: (id: number, body: { name?: string; memo?: string; owner?: string }) =>
    request<Source>(`/sources/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  codeTree: () => request<CodeTreeItem[]>("/codes"),
  codesFlat: () => request<CodeTreeItem[]>("/codes"),
  createCode: (name: string, opts: { catid?: number | null; color?: string; owner?: string; supercid?: number | null } = {}) =>
    request<{ cid: number }>("/codes", {
      method: "POST",
      body: JSON.stringify({ name, owner: opts.owner, catid: opts.catid ?? null, color: opts.color, supercid: opts.supercid ?? null }),
    }),
  createCategory: (name: string, opts: { supercatid?: number | null; owner?: string; memo?: string } = {}) =>
    request<{ catid: number }>("/codes/categories", {
      method: "POST",
      body: JSON.stringify({
        name,
        owner: opts.owner,
        supercatid: opts.supercatid ?? null,
        memo: opts.memo,
      }),
    }),
  codeDetails: (cid: number) => request<CodeDetails>(`/codes/${cid}/details`),
  patchCode: (cid: number, body: { name?: string; memo?: string; color?: string; catid?: number | null; supercid?: number | null }) =>
    request<Code>(`/codes/${cid}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteCode: (cid: number) => request<void>(`/codes/${cid}`, { method: "DELETE" }),
  deleteCategory: (catid: number) => request<void>(`/codes/categories/${catid}`, { method: "DELETE" }),
  mergeCode: (cid: number, targetCid: number) =>
    request<Code>(`/codes/${cid}/merge`, {
      method: "POST",
      body: JSON.stringify({ target_cid: targetCid }),
    }),
  mergeCategory: (catid: number, targetCatid: number) =>
    request<void>(`/codes/categories/${catid}/merge`, {
      method: "POST",
      body: JSON.stringify({ target_catid: targetCatid }),
    }),

  sourceDetails: (id: number) => request<SourceDetails>(`/sources/${id}/details`),

  cases: () => request<Case[]>("/cases"),

  sourceCoding: (fid: number) => request<Coding[]>(`/codings/text/${fid}`),
  createTextCoding: (body: {
    cid: number;
    fid: number;
    seltext: string;
    pos0: number;
    pos1: number;
    owner?: string;
  }) =>
    request<Coding>("/codings/text", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteTextCoding: (ctid: number) => request<void>(`/codings/text/${ctid}`, { method: "DELETE" }),
  undoCodings: (items: object[]) =>
    request<UndoCodingsResponse>("/codings/undo", {
      method: "POST",
      body: JSON.stringify(items),
    }),

  imageCodings: (sourceId: number) => request<ImageCoding[]>(`/codings/image/${sourceId}`),
  createImageCoding: (body: {
    id: number;
    x1: number;
    y1: number;
    width: number;
    height: number;
    cid: number;
    owner?: string;
    memo?: string;
    important?: number;
    pdf_page?: number | null;
  }) =>
    request<ImageCoding>("/codings/image", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteImageCoding: (imid: number) =>
    request<void>(`/codings/image/${imid}`, { method: "DELETE" }),
  patchImageCoding: (
    imid: number,
    body: { x1?: number; y1?: number; width?: number; height?: number; memo?: string; cid?: number },
  ) =>
    request<ImageCoding>(`/codings/image/${imid}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  avCodings: (sourceId: number) => request<AVCoding[]>(`/codings/av/${sourceId}`),
  createAvCoding: (body: {
    id: number;
    pos0: number;
    pos1: number;
    cid: number;
    owner?: string;
    memo?: string;
    important?: number;
  }) =>
    request<AVCoding>("/codings/av", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteAvCoding: (avid: number) => request<void>(`/codings/av/${avid}`, { method: "DELETE" }),

  fileAnnotations: (fid: number) => request<Annotation[]>(`/annotations/${fid}`),  createAnnotation: (body: { fid: number; pos0: number; pos1: number; memo: string; owner?: string }) =>
    request<Annotation>("/annotations", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteAnnotation: (anid: number) => request<void>(`/annotations/${anid}`, { method: "DELETE" }),
  updateAnnotation: (anid: number, memo: string) =>
    request<Annotation>(`/annotations/${anid}`, {
      method: "PATCH",
      body: JSON.stringify({ memo }),
    }),

  shiftPositions: (body: {
    prev_text: string;
    new_text: string;
    codings: { ctid: number; pos0: number; pos1: number }[];
    annotations: { anid: number; pos0: number; pos1: number }[];
    case_text: { id: number; pos0: number; pos1: number }[];
  }) =>
    request<ShiftPositionsResponse>("/codings/shift-positions", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  commitEdit: (body: { fid: number; new_text: string }) =>
    request<CommitEditResponse>("/codings/commit-edit", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  autocode: (body: {
    fid: number | null;
    cid: number;
    find_texts: string[];
    mode: string;
    use_regex: boolean;
    owner?: string;
  }) =>
    request<AutocodeResponse>("/codings/autocode", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // --- Bookmarks ---------------------------------------------------------

  bookmarks: () => request<Bookmarks>("/bookmarks"),
  setBookmark: (file_id: number | null, pos: number | null) =>
    request<Bookmarks>("/bookmarks", {
      method: "PUT",
      body: JSON.stringify({ file_id, pos }),
    }),
  setAvBookmark: (file_id: number | null, msec: number | null, textpos: number | null) =>
    request<Bookmarks>("/bookmarks/av", {
      method: "PUT",
      body: JSON.stringify({ file_id, msec, textpos }),
    }),

  // --- Pseudonyms ----------------------------------------------------------

  pseudonyms: () => request<{ pseudonyms: Pseudonym[] }>("/pseudonyms"),
  addPseudonym: (original: string, pseudonym = "") =>
    request<{ pseudonym: Pseudonym }>("/pseudonyms", {
      method: "POST",
      body: JSON.stringify({ original, pseudonym }),
    }),
  deletePseudonym: (original: string) =>
    request<{ ok: boolean }>(`/pseudonyms/${encodeURIComponent(original)}`, { method: "DELETE" }),

  // --- Speakers ------------------------------------------------------------

  speakersDetect: (body: { fid?: number | null; identifiers: string[]; custom_regex?: string }) =>
    request<{ turns: SpeakerTurn[]; speakers: SpeakerInfo[] }>("/speakers/detect", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  speakersMark: (body: { fid?: number | null; identifiers: string[]; custom_regex?: string; selected?: string[] }) =>
    request<{ ok: boolean; turns_marked: number; codes_created: number }>("/speakers/mark", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // --- References -----------------------------------------------------------

  references: () => request<{ references: ReferenceEntry[] }>("/references"),
  deleteReference: (risid: number) => request<void>(`/references/${risid}`, { method: "DELETE" }),

  // --- Bad links + file replacement ----------------------------------------

  badLinks: () => request<{ links: BadLink[] }>("/sources/bad-links"),
  fixLink: (sourceId: number, mediapath: string) =>
    request<{ ok: boolean }>(`/sources/${sourceId}/mediapath`, {
      method: "PATCH",
      body: JSON.stringify({ mediapath }),
    }),
  bulkRenamePath: (old: string, newPath: string) =>
    request<{ ok: boolean; updated: number }>("/sources/bulk-rename-path", {
      method: "POST",
      body: JSON.stringify({ old, new: newPath }),
    }),
  replaceSource: (sourceId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${apiBaseSync()}/sources/${sourceId}/replace`, {
      method: "POST",
      body: form,
    }).then(handleJson<{ ok: boolean; message: string }>);
  },

  // --- Saved file filters ----------------------------------------------------

  fileFilters: () => request<{ filters: FileFilter[] }>("/sources/filters"),
  createFileFilter: (name: string, filter: string, owner?: string) =>
    request<{ ok: boolean; filterid: number }>("/sources/filters", {
      method: "POST",
      body: JSON.stringify({ name, filter, owner }),
    }),
  deleteFileFilter: (filterid: number) =>
    request<void>(`/sources/filters/${filterid}`, { method: "DELETE" }),

  // --- Cases -----------------------------------------------------------

  createCase: (name: string, owner?: string, memo = "") =>
    request<Case>("/cases", {
      method: "POST",
      body: JSON.stringify({ name, owner, memo }),
    }),
  updateCase: (caseid: number, body: { name?: string; memo?: string }) =>
    request<Case>(`/cases/${caseid}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteCase: (caseid: number) => request<void>(`/cases/${caseid}`, { method: "DELETE" }),
  caseFiles: (caseid: number) => request<CaseFileLink[]>(`/cases/${caseid}/files`),
  linkFileToCase: (caseid: number, fid: number, owner?: string) =>
    request<unknown>(`/cases/${caseid}/files`, {
      method: "POST",
      body: JSON.stringify({ fid, owner }),
    }),
  unlinkFileFromCase: (caseid: number, fid: number) =>
    request<void>(`/cases/${caseid}/files/${fid}`, { method: "DELETE" }),

  // --- Attributes ------------------------------------------------------

  attributeTypes: () => request<AttributeType[]>("/attributes/types"),
  createAttributeType: (
    name: string,
    case_or_file: string,
    value_type: string,
    owner?: string,
  ) =>
    request<AttributeType>("/attributes/types", {
      method: "POST",
      body: JSON.stringify({ name, case_or_file, value_type, owner }),
    }),
  deleteAttributeType: (name: string) =>
    request<void>(`/attributes/types/${name}`, { method: "DELETE" }),
  attributeValues: () => request<AttributeValue[]>("/attributes/values"),
  setAttributeValue: (
    name: string,
    attr_type: string,
    entityId: number,
    value: string,
    owner?: string,
  ) =>
    request<AttributeValue>(`/attributes/values/${name}?attr_type=${attr_type}&entity_id=${entityId}`, {
      method: "PUT",
      body: JSON.stringify({ value, owner }),
    }),

  // --- Journals --------------------------------------------------------

  journals: () => request<Journal[]>("/journals"),
  createJournal: (name: string, jentry: string, owner?: string) =>
    request<Journal>("/journals", {
      method: "POST",
      body: JSON.stringify({ name, jentry, owner }),
    }),
  updateJournal: (jid: number, body: { name?: string; jentry?: string }) =>
    request<Journal>(`/journals/${jid}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteJournal: (jid: number) => request<void>(`/journals/${jid}`, { method: "DELETE" }),

  // --- Notes workspace ----------------------------------------------------

  annotationsAll: () =>
    request<
      (Annotation & { file_name: string })[]
    >("/annotations"),
  memos: () => request<{ memos: { kind: string; id: number; name: string; memo: string; date: string; owner: string }[] }>("/memos"),

  // --- Reports ---------------------------------------------------------

  reports: {
    codeFrequencies: () => request<{ rows: CodeFrequencyRow[] }>("/reports/code-frequencies"),
    codesBySegments: () => request<{ rows: CodesBySegmentRow[] }>("/reports/codes-by-segments"),
    comparisonTable: () => request<ComparisonTable>("/reports/comparison-table"),
    cooccurrence: () => request<CooccurrenceTable>("/reports/co-occurrence"),
    exactMatches: () => request<{ rows: ExactMatchRow[] }>("/reports/exact-matches"),
    fileSummary: () => request<{ rows: FileSummaryRow[] }>("/reports/file-summary"),
    coderComparison: () => request<{ rows: CoderComparisonRow[] }>("/reports/coder-comparison"),
    attributes: () => request<{ rows: AttributeReportRow[] }>("/reports/attributes"),
    interrater: (coderA: string, coderB: string) =>
      request<InterraterResult>("/reports/interrater", {
        method: "POST",
        body: JSON.stringify({ coder_a: coderA, coder_b: coderB }),
      }),
    codeSegments: (cid: number) =>
      request<{ rows: CodeSegmentRow[] }>(`/reports/code-segments/${cid}`),
    codeSummary: (cid: number) => request<CodeSummary>(`/reports/code-summary/${cid}`),
    coderFileComparison: (coderA: string, coderB: string) =>
      request<CoderFileComparison>("/reports/coder-file-comparison", {
        method: "POST",
        body: JSON.stringify({ coder_a: coderA, coder_b: coderB }),
      }),
    codeRelations: (owner?: string) =>
      request<{ owner: string; relations: CodeRelation[] }>(
        `/reports/code-relations${owner ? `?owner=${encodeURIComponent(owner)}` : ""}`,
      ),
    wordFrequencies: (sourceId: number | null, limit = 100, stopwords = true) =>
      request<{ rows: WordFrequencyRow[] }>(
        `/reports/word-frequencies?limit=${limit}&stopwords=${stopwords}${sourceId ? `&source_id=${sourceId}` : ""}`,
      ),
    charts: (kind: string) => request<ChartMatrix>(`/reports/charts?kind=${kind}`),
    codebook: (memos = false) => request<{ text: string }>(`/reports/codebook?memos=${memos}`),
  },

  // --- Interchange (REFI-QDA and friends) ------------------------------

  interchange: {
    exportRefiUrl: () => `${apiBaseSync()}/interchange/export/refi`,
  },
  importRefi: (file: File, codername?: string) =>
    importMultipart<InterchangeResult>("/interchange/import/refi", file, codername),
  importRqda: (file: File, codername?: string) =>
    importMultipart<InterchangeResult>("/interchange/import/rqda", file, codername),
  importTaguette: (file: File, codername?: string) =>
    importMultipart<InterchangeResult>("/interchange/import/taguette", file, codername),
  importRis: (file: File, codername?: string) =>
    importMultipart<InterchangeResult>("/interchange/import/ris", file, codername),
  importSurvey: (file: File, codername?: string, qualitativeHeaders?: string[]) =>
    importMultipart<InterchangeResult>(
      "/interchange/import/survey",
      file,
      codername,
      qualitativeHeaders ? { qualitative_headers: qualitativeHeaders.join(",") } : undefined,
    ),
  importCodebook: (file: File, codername?: string) =>
    importMultipart<InterchangeResult>("/interchange/import/codebook", file, codername),
  importMerge: (file: File, codername?: string) =>
    importMultipart<InterchangeResult>("/interchange/import/merge", file, codername),
  importZotero: (codername?: string) => {
    const form = new FormData();
    if (codername) form.append("codername", codername);
    return fetch(`${apiBaseSync()}/interchange/import/zotero`, {
      method: "POST",
      body: form,
    }).then(handleJson<InterchangeResult>);
  },

  // --- AI assistant ---------------------------------------------------

  aiStatus: () => request<AiStatus>("/ai/status"),
  aiSaveSettings: (body: {
    enabled: boolean;
    provider: string;
    api_base: string;
    model: string;
    api_key: string;
    mcp_permissions?: string;
  }) =>
    request<unknown>("/ai/settings", { method: "PUT", body: JSON.stringify(body) }),
  aiChat: (message: string, context = "", mode = "general", promptId?: string) =>
    request<AiChatReply>("/ai/chat", {
      method: "POST",
      body: JSON.stringify({ message, context, mode, prompt_id: promptId }),
    }),
  aiSearch: (query: string, limit = 10) =>
    request<{ results: AiSearchResult[]; indexed?: boolean }>("/ai/search", {
      method: "POST",
      body: JSON.stringify({ query, limit }),
    }),
  aiPrompts: () => request<{ prompts: AiPromptInfo[] }>("/ai/prompts"),
  aiIndexStatus: () => request<AiIndexStatus>("/ai/index"),
  aiIndexBuild: () => request<AiIndexStatus>("/ai/index", { method: "POST", body: "{}" }),
  aiIndexDelete: () => request<void>("/ai/index", { method: "DELETE" }),
  aiMcp: (body: unknown) =>
    request<unknown>("/ai/mcp", { method: "POST", body: JSON.stringify(body) }),

  // --- SQL console -----------------------------------------------------

  sqlRun: (sql: string) =>
    request<SqlResult>("/sql/run", { method: "POST", body: JSON.stringify({ sql }) }),
  savedQueries: () => request<{ rows: SavedQuery[] }>("/sql/saved"),
  saveQuery: (q: { title: string; description?: string; grouper?: string; ssql: string }) =>
    request<unknown>("/sql/saved", { method: "POST", body: JSON.stringify(q) }),
  deleteQuery: (title: string) =>
    request<void>(`/sql/saved/${encodeURIComponent(title)}`, { method: "DELETE" }),

  // --- Audit / history ---------------------------------------------------

  audit: (params: { limit?: number; offset?: number; action?: string; user?: string } = {}) =>
    request<AuditResponse>(
      `/audit?${new URLSearchParams(
        Object.fromEntries(
          Object.entries(params).filter(([, v]) => v !== undefined && v !== ""),
        ) as Record<string, string>,
      ).toString()}`,
    ),
  auditStats: () => request<AuditStatsRow[]>("/audit/stats"),
  auditUndo: (id: number) =>
    request<{ ok: boolean; message: string }>("/audit/undo", {
      method: "POST",
      body: JSON.stringify({ id }),
    }),
  auditRedo: (id: number) =>
    request<{ ok: boolean; message: string }>("/audit/redo", {
      method: "POST",
      body: JSON.stringify({ id }),
    }),

  // --- Transcription ------------------------------------------------------

  transcribeStatus: () => request<TranscribeStatus>("/transcribe/status"),
  transcribeSaveSettings: (body: Partial<TranscribeSettings>) =>
    request<TranscribeSettings>("/transcribe/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  transcribeStart: (body: {
    source_id: number;
    engine?: string;
    model?: string;
    language?: string | null;
    translate?: boolean;
    beam_size?: number;
    temperature?: number;
    vad?: boolean;
    device?: string;
    timestamps?: boolean;
    segment_coding?: boolean;
    segment_cid?: number | null;
  }) => request<{ job_id: string }>("/transcribe", { method: "POST", body: JSON.stringify(body) }),
  transcribeJob: (jobId: string) => request<TranscribeJob>(`/transcribe/jobs/${jobId}`),

  // --- Graphs (code-map editor) ----------------------------------------

  graphs: () => request<{ graphs: GraphSummary[] }>("/graphs"),
  patchPath: (path: string, body: Record<string, unknown>) =>
    request<unknown>(path, { method: "PATCH", body: JSON.stringify(body) }),
  createGraph: (name: string, description = "") =>
    request<GraphSummary>("/graphs", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),
  updateGraph: (
    grid: number,
    body: { name?: string; description?: string; scene_width?: number; scene_height?: number },
  ) => request<GraphSummary>(`/graphs/${grid}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteGraph: (grid: number) => request<void>(`/graphs/${grid}`, { method: "DELETE" }),
  graphData: (grid: number) => request<GraphData>(`/graphs/${grid}`),

  graphAddCdctItem: (grid: number, body: { kind: string; ref_id: number; x: number; y: number }) =>
    request<CdctItem>(`/graphs/${grid}/items/cdct`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  graphPatchCdctItem: (grid: number, gtextid: number, body: Record<string, unknown>) =>
    request<CdctItem>(`/graphs/${grid}/items/cdct/${gtextid}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  graphDeleteCdctItem: (grid: number, gtextid: number) =>
    request<void>(`/graphs/${grid}/items/cdct/${gtextid}`, { method: "DELETE" }),

  graphAddCaseItem: (grid: number, body: { caseid: number; x: number; y: number }) =>
    request<CaseItem>(`/graphs/${grid}/items/case`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  graphPatchCaseItem: (grid: number, gcaseid: number, body: Record<string, unknown>) =>
    request<CaseItem>(`/graphs/${grid}/items/case/${gcaseid}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  graphDeleteCaseItem: (grid: number, gcaseid: number) =>
    request<void>(`/graphs/${grid}/items/case/${gcaseid}`, { method: "DELETE" }),

  graphAddFileItem: (grid: number, body: { fid: number; x: number; y: number }) =>
    request<FileItem>(`/graphs/${grid}/items/file`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  graphPatchFileItem: (grid: number, gfileid: number, body: Record<string, unknown>) =>
    request<FileItem>(`/graphs/${grid}/items/file/${gfileid}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  graphDeleteFileItem: (grid: number, gfileid: number) =>
    request<void>(`/graphs/${grid}/items/file/${gfileid}`, { method: "DELETE" }),

  graphAddFreeItem: (grid: number, body: { x: number; y: number; free_text: string }) =>
    request<FreeItem>(`/graphs/${grid}/items/free`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  graphPatchFreeItem: (grid: number, gfreeid: number, body: Record<string, unknown>) =>
    request<FreeItem>(`/graphs/${grid}/items/free/${gfreeid}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  graphDeleteFreeItem: (grid: number, gfreeid: number) =>
    request<void>(`/graphs/${grid}/items/free/${gfreeid}`, { method: "DELETE" }),

  graphAddMemoItem: (
    grid: number,
    body: { memo_source_type: string; memo_source_id: number; x: number; y: number },
  ) =>
    request<MemoItem>(`/graphs/${grid}/items/memo`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  graphDeleteMemoItem: (grid: number, gmemoid: number) =>
    request<void>(`/graphs/${grid}/items/memo/${gmemoid}`, { method: "DELETE" }),

  graphAddCdctLine: (
    grid: number,
    body: { from_node: number; to_node: number; label?: string; arrow_mode?: string },
  ) =>
    request<CdctLine>(`/graphs/${grid}/lines/cdct`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  graphPatchCdctLine: (grid: number, glineid: number, body: Record<string, unknown>) =>
    request<CdctLine>(`/graphs/${grid}/lines/cdct/${glineid}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  graphDeleteCdctLine: (grid: number, glineid: number) =>
    request<void>(`/graphs/${grid}/lines/cdct/${glineid}`, { method: "DELETE" }),

  graphAddEntityLine: (
    grid: number,
    body: { from_kind: string; from_id: number; to_kind: string; to_id: number; label?: string },
  ) =>
    request<FreeLine>(`/graphs/${grid}/lines/entity`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  graphPatchEntityLine: (grid: number, gflineid: number, body: Record<string, unknown>) =>
    request<FreeLine>(`/graphs/${grid}/lines/entity/${gflineid}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  graphDeleteEntityLine: (grid: number, gflineid: number) =>
    request<void>(`/graphs/${grid}/lines/entity/${gflineid}`, { method: "DELETE" }),

  graphGenerateModel: (
    model: string,
    name: string,
    fileIds?: number[],
    caseIds?: number[],
  ) =>
    request<{ grid: number; model: string }>("/graphs/models", {
      method: "POST",
      body: JSON.stringify({ model, name, file_ids: fileIds, case_ids: caseIds }),
    }),

  // --- Reference attachments -------------------------------------------

  attachReferenceFile: (risid: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${apiBaseSync()}/references/${risid}/attach`, {
      method: "POST",
      body: form,
    }).then(handleJson<{ ok: boolean; source_id: number; name: string; risid: number }>);
  },
  detachReferenceFile: (risid: number, sourceId: number) =>
    request<void>(`/references/${risid}/attach/${sourceId}`, { method: "DELETE" }),

  // --- Code color scheme --------------------------------------------------

  colorScheme: () => request<ColorScheme>("/color-scheme"),
  saveColorScheme: (colors: string[], ranges: { name: string; min: number; max: number }[] = []) =>
    request<ColorScheme>("/color-scheme", {
      method: "PUT",
      body: JSON.stringify({ colors, ranges }),
    }),
  resetColorScheme: () => request<ColorScheme>("/color-scheme", { method: "DELETE" }),
};

async function handleJson<T>(res: Response): Promise<T> {
  if (!res.ok) throw new ApiError(res.status, `API error ${res.status}`);
  return (await res.json()) as T;
}

async function importMultipart<T>(
  path: string,
  file: File,
  codername?: string,
  extra?: Record<string, string>,
): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  if (codername) form.append("codername", codername);
  for (const [key, value] of Object.entries(extra ?? {})) {
    form.append(key, value);
  }
  return fetch(`${apiBaseSync()}${path}`, { method: "POST", body: form }).then(handleJson<T>);
}
