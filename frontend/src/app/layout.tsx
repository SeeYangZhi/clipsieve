import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AppHeader } from "@/components/AppHeader";
import { Toaster } from "@/components/ui/sonner";
import { en } from "@/lib/i18n/en";
import "./globals.css";

const geistSans = Geist({
  subsets: ["latin"],
  variable: "--font-geist-sans",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
});

// Metadata renders on the server before the client locale is known; use the en dictionary.
export const metadata: Metadata = {
  description: en["app.tagline"],
  title: en["app.title"],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      lang="en"
    >
      <body className="min-h-screen bg-background text-foreground">
        <AppHeader />
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
        <Toaster />
      </body>
    </html>
  );
}
