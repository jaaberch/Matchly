"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { useSession } from "@/components/SessionProvider";
import { Button, Input } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { RequestOtpResult } from "@/lib/types";

type Step = "phone" | "code";

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginSkeleton />}>
      <LoginForm />
    </Suspense>
  );
}

function LoginSkeleton() {
  return (
    <div className="space-y-4 py-6" aria-busy="true">
      <div className="h-8 w-32 animate-pulse rounded bg-ink-800" />
      <div className="h-12 animate-pulse rounded-xl bg-ink-800" />
    </div>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, signIn } = useSession();

  // Where to go after signing in. Only same-site paths are accepted, so a
  // crafted link cannot bounce someone off to another origin.
  const nextParam = searchParams.get("next");
  const destination = nextParam && nextParam.startsWith("/") && !nextParam.startsWith("//")
    ? nextParam
    : "/";

  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<RequestOtpResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const codeRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (user) router.replace(destination);
  }, [user, router, destination]);

  useEffect(() => {
    if (step === "code") codeRef.current?.focus();
  }, [step]);

  async function sendCode(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.auth.requestOtp(phone);
      setChallenge(result);
      // The mock provider hands the code back so development needs no SMS vendor.
      if (result.dev_code) setCode(result.dev_code);
      setStep("code");
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setBusy(false);
    }
  }

  async function verifyCode(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      signIn(await api.auth.verifyOtp(phone, code, name));
      router.replace(destination);
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="animate-fade-in py-6">
      <h1 className="text-2xl font-bold tracking-tight">
        {step === "phone" ? "Sign in" : "Enter your code"}
      </h1>
      <p className="mt-2 text-sm text-ink-300">
        {step === "phone"
          ? "Your phone number is your Matchly account. We will text you a code."
          : `We sent a code to ${challenge?.phone ?? "your phone"}.`}
      </p>

      {step === "phone" ? (
        <form onSubmit={sendCode} className="mt-7 space-y-5" noValidate>
          <Input
            label="Phone number"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            autoFocus
            placeholder="0612345678"
            hint="Moroccan or international format both work."
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            error={error ?? undefined}
          />
          <Input
            label="Your name"
            hint="Shown to the other players in your match."
            autoComplete="name"
            placeholder="Youssef"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <Button type="submit" size="lg" fullWidth loading={busy} disabled={!phone.trim()}>
            Send code
          </Button>
        </form>
      ) : (
        <form onSubmit={verifyCode} className="mt-7 space-y-5" noValidate>
          <Input
            ref={codeRef}
            label="6-digit code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            placeholder="123456"
            className="text-center text-2xl tracking-[0.4em]"
            value={code}
            onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
            error={error ?? undefined}
          />
          {challenge?.dev_code && (
            <p className="rounded-xl bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
              Development mode: the code was filled in for you. No SMS was sent.
            </p>
          )}
          <Button type="submit" size="lg" fullWidth loading={busy} disabled={code.length < 4}>
            Continue
          </Button>
          <Button
            type="button"
            variant="ghost"
            fullWidth
            onClick={() => {
              setStep("phone");
              setCode("");
              setError(null);
            }}
          >
            Use a different number
          </Button>
        </form>
      )}
    </div>
  );
}

/** Turns the API's stable error codes into text a player understands. */
function messageFor(caught: unknown): string {
  if (!(caught instanceof ApiError)) return "Something went wrong. Please try again.";

  switch (caught.code) {
    case "INVALID_PHONE":
      return "That phone number does not look right.";
    case "INVALID_OTP": {
      const left = caught.details.attempts_remaining;
      return typeof left === "number" && left > 0
        ? `Wrong code. ${left} ${left === 1 ? "try" : "tries"} left.`
        : "Wrong code.";
    }
    case "OTP_EXPIRED":
      return "That code expired. Request a new one.";
    case "TOO_MANY_ATTEMPTS":
      return "Too many attempts. Request a new code.";
    case "RATE_LIMITED":
      return "Too many codes requested. Wait a few minutes and try again.";
    case "VALIDATION_ERROR":
      return "Please check what you entered.";
    default:
      return caught.message;
  }
}
