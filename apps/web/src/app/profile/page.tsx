"use client";

import { useState } from "react";

import { RequireAuth } from "@/components/RequireAuth";
import { useSession } from "@/components/SessionProvider";
import { Button, Card, Input } from "@/components/ui";
import { api } from "@/lib/api";
import { formatPhone } from "@/lib/format";

export default function ProfilePage() {
  return (
    <RequireAuth>
      <ProfileContent />
    </RequireAuth>
  );
}

function ProfileContent() {
  const { user, setUser, signOut } = useSession();
  const [name, setName] = useState(user?.name ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      setUser(await api.users.updateMe({ name }));
      setSaved(true);
    } catch {
      setError("Could not save your name. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="animate-fade-in space-y-5">
      <h1 className="text-2xl font-bold tracking-tight">Profile</h1>

      <Card className="p-4">
        <form onSubmit={save} className="space-y-4">
          <Input
            label="Name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            error={error ?? undefined}
          />
          <div>
            <p className="field-label">Phone</p>
            <p className="mt-1 text-base text-ink-100">
              {user ? formatPhone(user.phone) : ""}
            </p>
            <p className="mt-1 text-sm text-ink-400">
              Your phone number is your account and cannot be changed here.
            </p>
          </div>
          <Button type="submit" loading={saving} disabled={!name.trim() || name === user?.name}>
            Save
          </Button>
          {saved && <p className="text-sm text-pitch-400">Saved.</p>}
        </form>
      </Card>

      <Card className="p-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-300">
          Privacy
        </h2>
        <p className="mt-2 text-sm text-ink-300">
          Matchly records matches to generate highlights. Players are identified by the
          jersey number they register at check-in — never by facial recognition. You can
          delete your account at any time.
        </p>
      </Card>

      <Button variant="secondary" fullWidth onClick={() => void signOut()}>
        Sign out
      </Button>
    </div>
  );
}
