import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Bexio AI Workspace",
  description: "AI-Buchhaltungs-Workspace fuer Bexio - automatische Erfassung, Vorschlaege, Multi-Mandant.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="de" suppressHydrationWarning>
      <body className="min-h-screen">
        {children}
      </body>
    </html>
  );
}
