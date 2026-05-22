"use client";

import { ErrorState } from "@/components/ui/feedback-states";

export default function Error({
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="grid min-h-dvh place-items-center bg-[#05070d] px-5 text-white">
      <div className="w-full max-w-xl">
        <ErrorState
          title="The learning interface could not load"
          description="Something interrupted the cinematic workspace. Retry to rebuild the session."
          onRetry={reset}
          retryLabel="Reload workspace"
        />
      </div>
    </main>
  );
}
