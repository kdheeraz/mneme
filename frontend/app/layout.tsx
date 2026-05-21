import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Mneme — Memory for LLM Agents",
  description: "Memory-as-a-Service for multi-agent LLM systems.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
