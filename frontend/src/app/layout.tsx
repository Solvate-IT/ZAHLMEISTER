import type {Metadata, Viewport} from "next";
import "./globals.css";
import "./portal.css";
import "./ux.css";
import "./mobile-workspace.css";
import {I18nProvider} from "@/lib/i18n";
import {NativeBridge} from "@/components/NativeBridge";
import {ToastHost} from "@/components/ToastHost";

export const metadata: Metadata = {
  title: "Zahlmeister – Ihr Geldeintreiber",
  description: "Zahlungen einfach einsammeln und nachverfolgen.",
  manifest: "/manifest.webmanifest?v=4",
  icons: {
    icon: [{url: "/favicon.svg", type: "image/svg+xml"}],
    shortcut: "/favicon.svg",
    apple: [{url: "/icons/apple-touch-v4.png", sizes: "180x180", type: "image/png"}],
  },
};
export const viewport: Viewport = {
  themeColor: "#285481",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({children}: {children: React.ReactNode}) {
  return <html lang="de"><body><I18nProvider><NativeBridge/>{children}<ToastHost/></I18nProvider></body></html>;
}
