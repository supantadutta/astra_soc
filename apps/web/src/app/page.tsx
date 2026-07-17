"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getToken() ? "/dashboard" : "/login");
  }, [router]);
  return (
    <div className="flex items-center justify-center min-h-screen text-cyan">
      <div className="animate-pulseGlow text-2xl font-bold tracking-widest">ASTRASOC</div>
    </div>
  );
}
