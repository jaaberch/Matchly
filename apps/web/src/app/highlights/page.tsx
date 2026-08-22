"use client";

import { RequireAuth } from "@/components/RequireAuth";
import { Card, CardHeader, EmptyState } from "@/components/ui";

/** Personal highlight feed. Wired to `GET /users/me/highlights` in Phase 6. */
export default function HighlightsPage() {
  return (
    <RequireAuth>
      <div className="animate-fade-in space-y-5">
        <h1 className="text-2xl font-bold tracking-tight">Highlights</h1>
        <Card>
          <CardHeader title="All your moments" />
          <EmptyState
            title="Nothing here yet"
            description="Clips from your matches will show up here, ready to share."
          />
        </Card>
      </div>
    </RequireAuth>
  );
}
