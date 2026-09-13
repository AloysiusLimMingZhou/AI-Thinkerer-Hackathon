import type { Metadata, Viewport } from "next";
import { Archivo, Courier_Prime } from "next/font/google";
import { TopBar } from "@/components/TopBar";
import "./globals.css";

const archivo = Archivo({
  subsets: ["latin"],
  axes: ["wdth"],
  variable: "--font-archivo",
  display: "swap",
});

const courier = Courier_Prime({
  subsets: ["latin"],
  weight: ["400", "700"],
  style: ["normal", "italic"],
  variable: "--font-courier",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Meetings – Meeting Agent", template: "%s – Meeting Agent" },
  description: "Meetings Aloy-bot attended for you: minutes, transcripts, and everything it said.",
};

export const viewport: Viewport = {
  themeColor: "#e6ebdf",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-GB" className={`${archivo.variable} ${courier.variable}`}>
      <body>
        <TopBar />
        {children}
      </body>
    </html>
  );
}
