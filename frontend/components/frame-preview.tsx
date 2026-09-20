"use client";

import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { formatSeconds } from "@/lib/timeline";
import { STYLE_COPY } from "@/lib/ui-copy";
import { previewFrame } from "@/services/api";
import type { SubtitleStyle } from "@/types/style";

const DEBOUNCE_MS = 450;

type Frame = { url: string; timeMs: number };

/**
 * One frame of the video with the subtitles on it, drawn by the renderer
 * that makes the final video: the only preview that shows the real font
 * size and position, including any automatic shrinking.
 */
export function FramePreview({
  jobId,
  style,
  timeMs,
  className = "",
}: {
  jobId: string;
  style: SubtitleStyle;
  /** null shows the longest line, the one that decides the font size */
  timeMs: number | null;
  className?: string;
}) {
  const [frame, setFrame] = useState<Frame | null>(null);
  const [failed, setFailed] = useState(false);
  const [pending, setPending] = useState(0);
  const styleKey = JSON.stringify(style);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setPending((count) => count + 1);
      previewFrame(jobId, JSON.parse(styleKey) as SubtitleStyle, timeMs, controller.signal)
        .then((next) => {
          if (!active) {
            URL.revokeObjectURL(next.url);
            return;
          }
          setFailed(false);
          setFrame((previous) => {
            if (previous) URL.revokeObjectURL(previous.url);
            return next;
          });
        })
        .catch(() => {
          if (active) setFailed(true);
        })
        .finally(() => setPending((count) => count - 1));
    }, DEBOUNCE_MS);
    return () => {
      active = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [jobId, styleKey, timeMs]);

  return (
    <figure className={`relative overflow-hidden rounded-xl bg-black ${className}`}>
      {frame ? (
        // a blob URL of an image made for this view; next/image has nothing to add
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={frame.url}
          alt={STYLE_COPY.framePreviewAlt}
          className="size-full object-contain"
        />
      ) : (
        <div className="aspect-video w-full" />
      )}
      {(pending > 0 || (!frame && !failed)) && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/35 text-white">
          <LoaderCircle className="size-6 animate-spin" />
        </div>
      )}
      <figcaption className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-3 bg-gradient-to-t from-black/75 to-transparent px-3 pb-2 pt-6 text-xs text-white">
        <span>
          {failed ? STYLE_COPY.framePreviewFailed : STYLE_COPY.framePreviewCaption}
        </span>
        {frame && <span className="font-mono">{formatSeconds(frame.timeMs)}</span>}
      </figcaption>
    </figure>
  );
}
