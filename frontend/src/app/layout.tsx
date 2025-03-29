import type {Metadata} from "next";
import {Manrope} from "next/font/google";
import "./globals.scss";
import {Providers} from "app/providers";

const poppins = Manrope({
    weight: ["400", "500", "600", "700", "800"],
    subsets: ["latin"],
});

export const metadata: Metadata = {
    title: "AZV Motors - Премиальный каршеринг",
    description: "Сдавайте свой автомобиль в субаренду и получайте стабильный доход с AZV Motors",
}

export default function RootLayout({
                                       children,
                                   }: {
    children: React.ReactNode
}) {
    return (
        <html lang="ru">
        <body className={`${poppins.className} font-sans`}>{children}</body>
        </html>
    )
}