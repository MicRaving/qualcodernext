/**
 * Media helpers matching backend semantics (core/enums.py).
 */

export function isPdf(filename: string): boolean {
  return filename.toLowerCase().endsWith(".pdf");
}

/** True when a source should open in the PDF coder. */
export function usesPdfCoder(source: { name: string; media_type: string }): boolean {
  return source.media_type === "text" && isPdf(source.name);
}

/** True when a file name is an HTML document (a captured webpage snapshot). */
export function isHtml(filename: string): boolean {
  return filename.toLowerCase().endsWith(".html") || filename.toLowerCase().endsWith(".htm");
}

/** True when a source should open in the HTML coder (webpage + plain text). */
export function usesHtmlCoder(source: { name: string; media_type: string }): boolean {
  return source.media_type === "text" && isHtml(source.name);
}

/**
 * True when a source can be transcribed (single source of truth for the
 * batch transcribe button AND the AV coder's transcribe button, so the two
 * can never disagree).
 *
 * Note: this checks the media type ONLY. Imported audio/video files always
 * have a linked transcript companion (av_text_id is never null), so that
 * field must not be used for eligibility — re-transcription overwrites the
 * companion's text.
 */
export function canTranscribeSource(source: { media_type: string }): boolean {
  return source.media_type === "audio" || source.media_type === "video";
}

/**
 * True when the source already has a REAL transcript: a companion is linked
 * (av_text_id) AND that companion carries non-empty text. Imported AV files
 * get an empty companion immediately, so empty companions stay eligible for
 * (re-)transcription. Used together with canTranscribeSource to decide
 * batch-transcribe eligibility.
 */
export function hasRealTranscript(source: {
  av_text_id: number | null;
  has_transcript?: boolean;
}): boolean {
  return source.av_text_id != null && source.has_transcript === true;
}
