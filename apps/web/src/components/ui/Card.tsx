import type { HTMLAttributes, ReactNode } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

export function Card({ className = "", children, ...rest }: CardProps) {
  return (
    <div
      className={`rounded-2xl border border-ink-600/70 bg-ink-800 ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardHeader({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="flex items-center justify-between px-4 pt-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-300">{title}</h2>
      {action}
    </div>
  );
}

export function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="px-4 py-8 text-center">
      <p className="text-sm font-medium text-ink-200">{title}</p>
      <p className="mt-1 text-sm text-ink-400">{description}</p>
    </div>
  );
}
