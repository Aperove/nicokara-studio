import { HEADER_HEIGHT, PAGE_WIDTH } from "@/lib/layout";
import type { Metadata } from "next";
import { headers } from "next/headers";
import Link from "next/link";

import { THEME_BOOT_SCRIPT, ThemeToggle } from "@/components/theme-toggle";
import { HOME_COPY } from "@/lib/ui-copy";

import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host");
  const protocol = requestHeaders.get("x-forwarded-proto") ?? "https";
  const metadataBase = new URL(host ? `${protocol}://${host}` : "https://localhost");
  const title = "ニコカラ自动生成器";
  const description = HOME_COPY.metadataDescription;

  return {
    metadataBase,
    title,
    description,
    openGraph: {
      title,
      description,
      type: "website",
      images: [{ url: "/og.png", width: 1731, height: 907, alt: title }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: ["/og.png"],
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body className="min-h-screen">
        <header className="sticky top-0 z-30 border-b bg-background/80 backdrop-blur-md">
          <div
            className={`${PAGE_WIDTH} ${HEADER_HEIGHT} flex items-center justify-between`}
          >
            <Link href="/" className="focus-ring rounded-sm">
              <span className="text-base font-bold tracking-[0.06em]">
                ニコカラ
              </span>
              <span className="ml-2 rounded-full border px-2 py-0.5 text-[0.65rem] font-medium tracking-wider text-muted-foreground">
                LOCAL
              </span>
            </Link>
            <ThemeToggle />
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
