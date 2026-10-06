import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CAR Agri-Climate Portal",
  description:
    "El Niño vulnerability, rainfall and drought forecast maps for the Cordillera Administrative Region – DA-RFO-CAR AMIA Program.",
  icons: { icon: "/logos/da-car.png" },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0b6237" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preload" href="/fonts/Montserrat-Regular.woff2" as="font" type="font/woff2" crossOrigin="" />
        <link rel="preload" href="/fonts/Montserrat-SemiBold.woff2" as="font" type="font/woff2" crossOrigin="" />
      </head>
      <body>
        <a href="#main-content" className="skip">
          Skip to content
        </a>
        <div id="main-content">{children}</div>
      </body>
    </html>
  );
}
