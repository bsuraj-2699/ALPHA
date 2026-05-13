import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
      <span className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
        404
      </span>
      <h1 className="font-display text-4xl">Page not found</h1>
      <p className="max-w-md text-sm text-muted-foreground">
        The page you&apos;re looking for doesn&apos;t exist, or has been moved.
      </p>
      <Button asChild variant="outline" size="sm">
        <Link href="/">Back to dashboard</Link>
      </Button>
    </div>
  );
}
