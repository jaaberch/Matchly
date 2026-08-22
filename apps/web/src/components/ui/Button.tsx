import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  fullWidth?: boolean;
}

const VARIANTS: Record<Variant, string> = {
  primary: "bg-pitch-500 text-ink-900 hover:bg-pitch-400 active:bg-pitch-600 font-semibold",
  secondary: "bg-ink-600 text-ink-100 hover:bg-ink-500 active:bg-ink-600",
  ghost: "bg-transparent text-ink-200 hover:bg-ink-700 active:bg-ink-600",
  danger: "bg-red-600/90 text-white hover:bg-red-600 active:bg-red-700",
};

// Minimum 44px tall: these are pressed with a thumb, often outdoors.
const SIZES: Record<Size, string> = {
  md: "h-11 px-4 text-sm",
  lg: "h-13 px-5 text-base",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading, fullWidth, className = "", children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={[
        "inline-flex items-center justify-center gap-2 rounded-xl transition-colors",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-pitch-400",
        "disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        SIZES[size],
        fullWidth ? "w-full" : "",
        className,
      ].join(" ")}
      {...rest}
    >
      {loading && (
        <span
          aria-hidden
          className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
        />
      )}
      {children}
    </button>
  );
});
