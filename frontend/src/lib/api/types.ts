/**
 * All exported interfaces, type aliases, and the GRAPH_MODELS constant
 * for the QualCoder v4 API client.
 *
 * Pure type definitions — no runtime logic (except the const assertion).
 */

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
  /** Another live instance is already open as the current coder (open only).
   *  Non-empty triggers a blocking warning before sync is allowed to corrupt
   *  the project. */
  duplicate_coder?: string;
  /** Shared-folder detection: true when the collaboration sync cycle should
   *  be switched on for this project (respects the per-project override). */
  sync_auto_enabled?: boolean;
  sync_auto_reason?: string;
}

export interface AppSettings {
  /** Packaged app: auto-open the most recent project on start (default on). */
  auto_open_project: boolean;
  /** GitHub token for the bug report (submitted issues / attachments).
   *  The backend settings model only knows auto_open_project — the GitHub
   *  fields travel in the same payload and are mirrored to localStorage
   *  (the backend drops unknown keys, so they would not survive a reload
   *  otherwise). */
  github_token?: string;
  /** Target repository as "owner/repo" for the bug report. */
  github_repo?: string;
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
  /** True when av_text_id points at a companion whose fulltext is non-empty. */
  has_transcript: boolean;
}

export interface CodeTreeItem {
  kind: "category" | "code";
  id: number;
  name: string;
  color: string | null;
  parent_id: number | null;
  memo: string;
  subcode?: boolean;
  /** Sibling order within the parent group (backend sorts by it). */
  position?: number;
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

export interface Category {
  catid: number;
  name: string;
  memo: string;
  owner: string;
  date: string;
  supercatid: number | null;
}

export interface CodeExample {
  ctid: number;
  fid: number;
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
  value_labels?: Record<string, string>;
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
  suggested: { cid: number; name: string; reason: string }[];
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
  /** Live reachability of the provider (only when probed). */
  reachable?: boolean | null;
  probe_error?: string;
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
  summary?: string;
  undoable?: boolean;
  undo_reason?: string | null;
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

export interface TranscribeStatus {
  engines: { whisper: boolean };
  models_cached: string[];
  model_dir: string;
  models: string[];
  settings: TranscribeSettings;
}


export interface TranscribeJob {
  id: string;
  state: string;
  progress: number;
  message: string;
  segments: unknown[];
  error: string | null;
  transcript_source_id?: number | null;
  /** Partial "[mm:ss] text" transcript while the job is still running. */
  live_text?: string | null;
  result?: unknown[];
  paused?: boolean;
}

/** A background AI-autocode job (one per source file). */
export interface AutocodeJob {
  id: string;
  state: string;
  progress: number;
  message: string;
  source_id: number;
  paused?: boolean;
  error?: string | null;
  result?: { count: number; suggested: { cid: number; name: string; reason: string }[] } | null;
}

// --- R integration (Rscript bridge) ------------------------------------

/** R installation status as probed by the backend bridge. */
export interface RStatus {
  available: boolean;
  path: string | null;
  version: string | null;
  error: string | null;
}

/** A background R-script job (runs through the same queue as the others). */
export interface RJob {
  id: string;
  state: string;
  progress: number;
  message: string;
  stdout: string;
  stderr: string;
  exit_code: number | null;
  error: string | null;
  /** Artifact file names produced by the job (subset of GET /r/artifacts). */
  artifacts?: string[];
}

/** An artifact file in the R exchange directory. */
export interface RArtifact {
  name: string;
  kind: "png" | "csv" | "other";
  size: number;
  modified: string;
}

/** A saved R script (per project, like stored SQL queries). */
export interface RScript {
  name: string;
  script: string;
  updated: string;
}

/** Response of POST /r/prepare-report: a template stub + prepared files. */
export interface RPrepareResult {
  stub: string;
  files: string[];
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

// --- Collaboration sync (Option B) ------------------------------------

export interface SyncConflict {
  seq: number;
  entity: string;
  pk: string;
  action: string;
  reason: string;
}

/** Live coder presence — an instance actively working on the open project
 *  (broadcast via per-instance presence files inside the project folder). */
export interface PresenceEntry {
  coder: string;
  os_user: string;
  pid: number;
  /** Last heartbeat (epoch seconds); "live" when recent. */
  ts: number;
  /** The source currently being worked on (null = not in a file). */
  file_id: number | null;
  file_name: string;
}

export interface PresenceResponse {
  ok: boolean;
  presence: PresenceEntry[];
}

export interface SyncCollaborator {
  user: string;
  last_sync: number; // sidecar mtime (epoch seconds)
  pending_import: number;
  /** Number of that rater's changes still blocked by conflicts. */
  pending_conflicts: number;
  /** Structured conflict summaries for that rater (empty when none). */
  conflicts?: SyncConflict[];
}

export interface SyncStatus {
  ok: boolean;
  reason?: string;
  enabled?: boolean;
  user?: string;
  pending_export: number;
  pending_import: number;
  /** Total pending conflicts across collaborators (drives the warning UI). */
  pending_conflicts: number;
  collaborators: SyncCollaborator[];
  last_sync: number; // epoch seconds of the last successful cycle (0 = never)
  last_error: string;
  last_error_at: number;
}

export interface UpdatesSettings {
  check_interval: "daily" | "weekly" | "never";
  auto_update: boolean;
}

export interface MaintenanceSettings {
  compact_on_close: boolean;
  last_compact: string;
}

export interface CompactResult {
  ok: boolean;
  before_bytes: number;
  after_bytes: number;
  freed_bytes: number;
  indexes_dropped: number;
  indexes_recreated: number;
}

export interface SyncResult {
  ok: boolean;
  reason?: string;
  exported?: number;
  imported?: Record<string, { applied: number; conflicts: SyncConflict[] }>;
}
