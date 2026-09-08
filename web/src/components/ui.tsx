import type { ReactNode, ButtonHTMLAttributes } from "react";

export function Button({
  variant = "primary", className = "", ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  const base = "inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50 disabled:cursor-default transition-colors";
  const styles = {
    primary: "bg-accent text-white border border-accent hover:opacity-90",
    ghost: "bg-panel text-ink border border-line hover:border-accent",
    danger: "bg-panel text-danger border border-line hover:border-danger",
  }[variant];
  return <button className={`${base} ${styles} ${className}`} {...props} />;
}

export function Card({ children, className = "", onClick }: { children: ReactNode; className?: string; onClick?: () => void }) {
  return <div onClick={onClick} className={`rounded-xl border border-line bg-panel p-4 shadow-sm ${className}`}>{children}</div>;
}

export function Badge({ children, tone = "accent" }: { children: ReactNode; tone?: "accent" | "muted" }) {
  const s = tone === "accent" ? "bg-accentSoft text-accent" : "border border-line text-muted";
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${s}`}>{children}</span>;
}

export function Spinner() {
  return <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-muted border-t-transparent" />;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-12 text-center text-muted">{children}</div>;
}
