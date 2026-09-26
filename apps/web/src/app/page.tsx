"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    // The shell redirects to /login when there is no session.
    router.replace("/dashboard");
  }, [router]);
  return (
    <div className="flex items-center justify-center min-h-screen text-cyan">
      <div className="animate-pulseGlow text-2xl font-bold tracking-widest">ASTRASOC</div>
    </div>
  );
}
