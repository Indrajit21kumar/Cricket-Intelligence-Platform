// Core layout + input primitives (Book 6 §3.2). One definition, reused across
// screens. Calm, uncluttered, restrained elevation (D7).
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-card bg-white p-5 shadow-card ring-1 ring-slate-200/70 ${className}`}
    >
      {children}
    </section>
  );
}

export function SectionTitle({
  children,
  hint,
}: {
  children: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">{children}</h2>
      {hint ? <span className="text-xs text-slate-400">{hint}</span> : null}
    </div>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
};

export function Button({ variant = "primary", className = "", ...rest }: ButtonProps) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50";
  const variants: Record<string, string> = {
    primary: "bg-brand-600 text-white hover:bg-brand-700",
    secondary: "bg-white text-brand-700 ring-1 ring-brand-200 hover:bg-brand-50",
    ghost: "text-slate-600 hover:bg-slate-100",
  };
  return <button className={`${base} ${variants[variant]} ${className}`} {...rest} />;
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-xs text-slate-400">{hint}</span> : null}
    </label>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
      {...props}
    />
  );
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
      {...props}
    />
  );
}

export function Pill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "attention" | "critical" | "brand";
}) {
  const tones: Record<string, string> = {
    neutral: "bg-slate-100 text-slate-600 ring-slate-200",
    success: "bg-success-bg text-success-fg ring-success-ring/40",
    attention: "bg-attention-bg text-attention-fg ring-attention-ring/40",
    critical: "bg-critical-bg text-critical-fg ring-critical-ring/40",
    brand: "bg-brand-50 text-brand-700 ring-brand-200",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${tones[tone]}`}
    >
      {children}
    </span>
  );
}
