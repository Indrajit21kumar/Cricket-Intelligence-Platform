// Empty / loading / error states (Book 6 §3.2). Every data view has all three,
// so the UI is never a blank void or a silent failure. Errors are specific and
// non-punitive (§13).
import type { ReactNode } from "react";
import { Button } from "./primitives";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-8 text-sm text-slate-500" role="status" aria-live="polite">
      <span
        className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600"
        aria-hidden="true"
      />
      {label}
    </div>
  );
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-card border border-dashed border-slate-200 p-8 text-center">
      <div className="text-sm font-semibold text-slate-700">{title}</div>
      {body ? <div className="mt-1 text-sm text-slate-500">{body}</div> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="rounded-card bg-critical-bg p-4 text-sm text-critical-fg" role="alert">
      <div className="font-semibold">Something went wrong</div>
      <div className="mt-0.5">{message}</div>
      {onRetry ? (
        <div className="mt-3">
          <Button variant="secondary" onClick={onRetry}>
            Try again
          </Button>
        </div>
      ) : null}
    </div>
  );
}
