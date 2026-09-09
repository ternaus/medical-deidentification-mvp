import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Анонимизация документов",
  description: "Локальная обработка синтетических медицинских документов",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
