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
