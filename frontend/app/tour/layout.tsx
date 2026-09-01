import type { Metadata } from "next";
import type { ReactNode } from "react";

// The page itself is a client component (it drives WebGL), and a client
// component cannot export metadata — hence this layout, whose only job is the
// title and description for this route.
export const metadata: Metadata = {
  title: "The Transcript Timeline · AskTube AI",
  description:
    "A scroll-driven walk along a video transcript: how a question becomes an answer that cites the second it came from.",
};

export default function TourLayout({ children }: { children: ReactNode }) {
  return children;
}
