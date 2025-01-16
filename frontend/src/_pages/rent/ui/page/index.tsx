"use client";

import {useEffect, useState} from "react";

export const Rent = () => {
    const [timeLeft, setTimeLeft] = useState({
        days: 0,
        hours: 0,
        minutes: 0,
        seconds: 0,
    });

    useEffect(() => {
        const launchDate = new Date("2024-03-01T00:00:00").getTime();

        const timer = setInterval(() => {
            const now = new Date().getTime();
            const difference = launchDate - now;

            const days = Math.floor(difference / (1000 * 60 * 60 * 24));
            const hours = Math.floor((difference % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
            const minutes = Math.floor((difference % (1000 * 60 * 60)) / (1000 * 60));
            const seconds = Math.floor((difference % (1000 * 60)) / 1000);

            setTimeLeft({days, hours, minutes, seconds});

            if (difference < 0) {
                clearInterval(timer);
                setTimeLeft({days: 0, hours: 0, minutes: 0, seconds: 0});
            }
        }, 1000);

        return () => clearInterval(timer);
    }, []);

    return (
        <main className="min-h-screen flex items-center justify-center px-4">
            <div className="text-center space-y-8">
                <h1 className="text-4xl md:text-5xl font-bold">Скоро запустимся...</h1>
                <p className="text-xl md:text-2xl text-gray-600">Эта страница находится в разработке</p>

                <p className="text-lg text-gray-600 max-w-2xl mx-auto text-pretty">
                    Мы усердно работаем над тем, чтобы предоставить вам уникальный опыт аренды автомобилей.
                    <br/>
                    Совсем скоро вы сможете выбирать из широкого ассортимента автомобилей для любых целей и поездок.
                </p>
            </div>
        </main>
    );
};
