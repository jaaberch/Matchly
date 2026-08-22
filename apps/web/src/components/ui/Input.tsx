import { forwardRef, useId } from "react";
import type { InputHTMLAttributes } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
  error?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, className = "", id, ...rest },
  ref,
) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const describedBy = error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined;

  return (
    <div className="space-y-1.5">
      {label && (
        <label htmlFor={inputId} className="field-label">
          {label}
        </label>
      )}
      <input
        ref={ref}
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={[
          // text-base (16px) stops iOS Safari zooming in on focus.
          "h-12 w-full rounded-xl border bg-ink-800 px-4 text-base text-ink-100",
          "placeholder:text-ink-400 transition-colors",
          "focus:outline-none focus:ring-2 focus:ring-pitch-400/60",
          error ? "border-red-500/70" : "border-ink-600 focus:border-pitch-500",
          className,
        ].join(" ")}
        {...rest}
      />
      {error ? (
        <p id={`${inputId}-error`} role="alert" className="text-sm text-red-400">
          {error}
        </p>
      ) : hint ? (
        <p id={`${inputId}-hint`} className="text-sm text-ink-300">
          {hint}
        </p>
      ) : null}
    </div>
  );
});
