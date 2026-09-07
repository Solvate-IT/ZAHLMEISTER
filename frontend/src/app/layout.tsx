import type {Metadata, Viewport} from "next";
import "./globals.css";
import "./portal.css";
import {I18nProvider} from "@/lib/i18n";
import {NativeBridge} from "@/components/NativeBridge";

export const metadata: Metadata = {
  title: "Zahlmeister – Ihr Geldeintreiber",
  description: "Zahlungen einfach einsammeln und nachverfolgen.",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [{url: "/favicon.svg", type: "image/svg+xml"}],
    shortcut: "/favicon.svg",
  },
};
export const viewport: Viewport = {
  themeColor: "#06183F",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({children}: {children: React.ReactNode}) {
  return <html lang="de"><body><I18nProvider><NativeBridge/>{children}</I18nProvider></body></html>;
}
