import type { Metadata } from "next";
import { Inter } from "next/font/google";

import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap"
});

export const metadata: Metadata = {
  title: "AskTube AI",
  description: "Search, understand, and chat with YouTube videos using AI."
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className={inter.variable} suppressHydrationWarning>
        <a
          href="#main-content"
          className="skip-link"
        >
          Skip to main content
        </a>
        {children}
      </body>
    </html>
  );
}
