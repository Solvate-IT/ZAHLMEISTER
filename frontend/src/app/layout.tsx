import type {Metadata, Viewport} from "next";
import "./globals.css";
import {I18nProvider} from "@/lib/i18n";
import {NativeBridge} from "@/components/NativeBridge";

export const metadata: Metadata = {
  title: "Zahlmeister",
  description: "Zahlungen einfach einsammeln und nachverfolgen.",
  manifest: "/manifest.webmanifest",
  icons: {icon: "/favicon.png", apple: "/icons/apple-touch-icon.png"},
};
export const viewport: Viewport = {themeColor: "#0B63D8", width: "device-width", initialScale: 1, viewportFit: "cover"};

export default function RootLayout({children}: {children: React.ReactNode}) {
  return <html lang="de"><body><I18nProvider><NativeBridge/>{children}</I18nProvider></body></html>;
}
