export type Job = {
  id: string;
  status: string;
  stage: string;
  progress: number;
  original_video_name: string;
  video_size_bytes: number;
  video_sha256: string;
  lyrics_source: "text" | "file" | null;
  vocal_mode?: "on" | "off" | "both";
  /** An instrumental (off-vocal) version was rendered as well. */
  off_vocal_available?: boolean;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

