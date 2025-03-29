"use client"

import {useState, useEffect, useRef} from "react"
import Link from "next/link"
import Image from "next/image"
import {ArrowRight, Menu, X, ChevronDown} from "lucide-react"

export default function Home() {
    const [isMenuOpen, setIsMenuOpen] = useState(false)
    const [isScrolled, setIsScrolled] = useState(false)
    const [activeSection, setActiveSection] = useState("hero")
    const [cursorPosition, setCursorPosition] = useState({x: 0, y: 0})
    const [cursorHidden, setCursorHidden] = useState(true)
    const heroRef = useRef<HTMLDivElement>(null)
    const benefitsRef = useRef<HTMLDivElement>(null)
    const processRef = useRef<HTMLDivElement>(null)
    const securityRef = useRef<HTMLDivElement>(null)
    const appRef = useRef<HTMLDivElement>(null)

    // Parallax effect for hero section
    const [offsetY, setOffsetY] = useState(0)

    useEffect(() => {
        const handleScroll = () => {
            if (window.scrollY > 10) {
                setIsScrolled(true)
            } else {
                setIsScrolled(false)
            }

            setOffsetY(window.pageYOffset)

            // Determine active section
            const scrollPosition = window.scrollY + 300

            if (heroRef.current && scrollPosition < heroRef.current.offsetTop + heroRef.current.offsetHeight) {
                setActiveSection("hero")
            } else if (
                benefitsRef.current &&
                scrollPosition < benefitsRef.current.offsetTop + benefitsRef.current.offsetHeight
            ) {
                setActiveSection("benefits")
            } else if (
                processRef.current &&
                scrollPosition < processRef.current.offsetTop + processRef.current.offsetHeight
            ) {
                setActiveSection("process")
            } else if (
                securityRef.current &&
                scrollPosition < securityRef.current.offsetTop + securityRef.current.offsetHeight
            ) {
                setActiveSection("security")
            } else if (appRef.current) {
                setActiveSection("app")
            }
        }

        window.addEventListener("scroll", handleScroll)
        return () => window.removeEventListener("scroll", handleScroll)
    }, [])

    // Custom cursor effect
    useEffect(() => {
        // Проверка, является ли устройство мобильным
        const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent)

        if (!isMobile) {
            const handleMouseMove = (e: MouseEvent) => {
                setCursorPosition({x: e.clientX, y: e.clientY})
                setCursorHidden(false)
            }

            const handleMouseLeave = () => {
                setCursorHidden(true)
            }

            window.addEventListener("mousemove", handleMouseMove)
            document.body.addEventListener("mouseleave", handleMouseLeave)

            return () => {
                window.removeEventListener("mousemove", handleMouseMove)
                document.body.removeEventListener("mouseleave", handleMouseLeave)
            }
        } else {
            // Скрываем курсор на мобильных устройствах
            setCursorHidden(true)
        }
    }, [])

    const toggleMenu = () => {
        setIsMenuOpen(!isMenuOpen)
    }

    const whatsappLink =
        "https://wa.me/+77076319221?text=Здравствуйте! Хочу стать партнером Azv Motors."

    return (
        <div className="min-h-screen bg-white text-black">
            {/* Custom cursor */}
            <div
                className={`fixed w-6 h-6 rounded-full border border-black mix-blend-difference pointer-events-none z-50 transition-opacity duration-300 ${cursorHidden ? "opacity-0" : "opacity-100"}`}
                style={{
                    left: `${cursorPosition.x}px`,
                    top: `${cursorPosition.y}px`,
                    transform: "translate(-50%, -50%)",
                }}
            />

            {/* Навигация */}
            <header
                className={`fixed w-full z-40 transition-all duration-500 ${isScrolled ? "bg-white/90 backdrop-blur-md py-4" : "bg-transparent py-6"}`}
            >
                <div className="container mx-auto px-6 md:px-12 lg:px-16">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center">
                            <Image src="/Group.png" alt="AZV Motors" width={28} height={28} className="mr-3"/>
                            <span className="text-lg font-light tracking-widest">AZV MOTORS</span>
                        </div>

                        <div className="hidden md:flex items-center space-x-8 lg:space-x-12">
                            <Link
                                href="#benefits"
                                className={`text-sm font-light tracking-wider hover:text-gray-500 transition-colors ${activeSection === "benefits" ? "text-black" : "text-gray-400"}`}
                            >
                                ПРЕИМУЩЕСТВА
                            </Link>
                            <Link
                                href="#process"
                                className={`text-sm font-light tracking-wider hover:text-gray-500 transition-colors ${activeSection === "process" ? "text-black" : "text-gray-400"}`}
                            >
                                ПРОЦЕСС
                            </Link>
                            <Link
                                href="#security"
                                className={`text-sm font-light tracking-wider hover:text-gray-500 transition-colors ${activeSection === "security" ? "text-black" : "text-gray-400"}`}
                            >
                                БЕЗОПАСНОСТЬ
                            </Link>
                            <Link
                                href={whatsappLink}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-sm font-light tracking-wider hover:text-gray-500 transition-colors"
                            >
                                СВЯЗАТЬСЯ
                            </Link>
                            <Link
                                href="/login"
                                className="ml-4 px-6 py-2 border border-black text-sm font-light tracking-wider hover:bg-black hover:text-white transition-all duration-300"
                            >
                                ВОЙТИ
                            </Link>
                        </div>

                        <div className="flex items-center md:hidden">
                            <Link
                                href="/login"
                                className="mr-4 px-4 py-1.5 border border-black text-xs font-light tracking-wider hover:bg-black hover:text-white transition-all duration-300"
                            >
                                ВОЙТИ
                            </Link>
                            <button className="focus:outline-none" onClick={toggleMenu}>
                                {isMenuOpen ? <X className="h-5 w-5"/> : <Menu className="h-5 w-5"/>}
                            </button>
                        </div>
                    </div>
                </div>

                {/* Мобильное меню */}
                {isMenuOpen && (
                    <div className="md:hidden fixed inset-0 bg-white z-50 flex flex-col justify-center items-center">
                        <button className="absolute top-6 right-6 focus:outline-none" onClick={toggleMenu}>
                            <X className="h-5 w-5"/>
                        </button>

                        <div className="space-y-8 text-center">
                            <Link
                                href="#benefits"
                                className="block text-2xl font-extralight tracking-wider hover:text-gray-500 transition-colors"
                                onClick={() => setIsMenuOpen(false)}
                            >
                                ПРЕИМУЩЕСТВА
                            </Link>
                            <Link
                                href="#process"
                                className="block text-2xl font-extralight tracking-wider hover:text-gray-500 transition-colors"
                                onClick={() => setIsMenuOpen(false)}
                            >
                                ПРОЦЕСС
                            </Link>
                            <Link
                                href="#security"
                                className="block text-2xl font-extralight tracking-wider hover:text-gray-500 transition-colors"
                                onClick={() => setIsMenuOpen(false)}
                            >
                                БЕЗОПАСНОСТЬ
                            </Link>
                            <Link
                                href={whatsappLink}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="block text-2xl font-extralight tracking-wider hover:text-gray-500 transition-colors"
                                onClick={() => setIsMenuOpen(false)}
                            >
                                СВЯЗАТЬСЯ
                            </Link>
                        </div>
                    </div>
                )}
            </header>

            {/* Боковая навигация */}
            <div className="fixed right-8 top-1/2 transform -translate-y-1/2 z-30 hidden lg:block">
                <div className="flex flex-col items-center space-y-8">
                    <Link
                        href="#hero"
                        className={`w-2 h-2 rounded-full transition-all duration-300 ${activeSection === "hero" ? "bg-black h-8" : "bg-gray-300 hover:bg-gray-400"}`}
                    >
                        <span className="sr-only">Главная</span>
                    </Link>
                    <Link
                        href="#benefits"
                        className={`w-2 h-2 rounded-full transition-all duration-300 ${activeSection === "benefits" ? "bg-black h-8" : "bg-gray-300 hover:bg-gray-400"}`}
                    >
                        <span className="sr-only">Преимущества</span>
                    </Link>
                    <Link
                        href="#process"
                        className={`w-2 h-2 rounded-full transition-all duration-300 ${activeSection === "process" ? "bg-black h-8" : "bg-gray-300 hover:bg-gray-400"}`}
                    >
                        <span className="sr-only">Процесс</span>
                    </Link>
                    <Link
                        href="#security"
                        className={`w-2 h-2 rounded-full transition-all duration-300 ${activeSection === "security" ? "bg-black h-8" : "bg-gray-300 hover:bg-gray-400"}`}
                    >
                        <span className="sr-only">Безопасность</span>
                    </Link>
                    <Link
                        href="#app"
                        className={`w-2 h-2 rounded-full transition-all duration-300 ${activeSection === "app" ? "bg-black h-8" : "bg-gray-300 hover:bg-gray-400"}`}
                    >
                        <span className="sr-only">Приложение</span>
                    </Link>
                </div>
            </div>

            {/* Главный экран */}
            <section id="hero" ref={heroRef} className="relative h-screen flex items-center overflow-hidden">
                {/* Фоновое изображение с параллакс-эффектом */}
                <div
                    className="absolute inset-0 z-0 opacity-20"
                    style={{
                        transform: `translateY(${offsetY * 0.5}px)`,
                        backgroundImage: 'url("/placeholder.svg?height=1800&width=2400")',
                        backgroundSize: "cover",
                        backgroundPosition: "center",
                    }}
                />

                <div className="container mx-auto px-6 md:px-12 lg:px-16 relative z-10">
                    <div className="max-w-3xl">
                        <h1 className="text-4xl sm:text-5xl md:text-6xl lg:text-7xl xl:text-8xl font-extralight leading-tight tracking-tight mb-8 sm:mb-12">
                            Монетизируйте простаивающий автомобиль
                        </h1>
                        <p className="text-base sm:text-lg md:text-xl font-light text-gray-600 mb-10 sm:mb-16 tracking-wide max-w-2xl">
                            Сдавайте автомобиль в аренду и получайте стабильный доход, пока мы заботимся о безопасности
                            и комфорте
                        </p>
                        <div className="flex items-center">
                            <Link
                                href={whatsappLink}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="group inline-flex items-center text-sm font-light tracking-widest hover:text-gray-500 transition-colors"
                            >
                                НАЧАТЬ СОТРУДНИЧЕСТВО
                                <span
                                    className="ml-3 w-10 h-10 sm:w-12 sm:h-12 rounded-full border border-black flex items-center justify-center group-hover:bg-black group-hover:text-white transition-all duration-300">
                  <ArrowRight className="h-4 w-4 sm:h-5 sm:w-5"/>
                </span>
                            </Link>
                        </div>
                    </div>
                </div>

                {/* Скролл-индикатор */}
                <div
                    className="absolute bottom-8 sm:bottom-12 left-1/2 transform -translate-x-1/2 flex flex-col items-center">
                    <span className="text-xs font-light tracking-widest mb-4">СКРОЛЛ</span>
                    <ChevronDown className="h-5 w-5 animate-bounce"/>
                </div>
            </section>

            {/* Преимущества */}
            <section id="benefits" ref={benefitsRef} className="py-20 sm:py-24 md:py-32 relative">
                {/* Декоративный элемент */}
                <div className="absolute top-0 right-0 w-1/3 h-1/2 bg-gray-50 -z-10"></div>

                <div className="container mx-auto px-6 md:px-12 lg:px-16">
                    <div className="grid md:grid-cols-2 gap-16 md:gap-24">
                        <div>
                            <h2 className="text-2xl sm:text-3xl md:text-4xl lg:text-5xl font-extralight mb-8 sm:mb-12 tracking-tight">
                                Преимущества для владельцев авто премиум класса
                            </h2>
                            <p className="text-base sm:text-lg font-light text-gray-600 tracking-wide mb-8 sm:mb-12">
                                Мы создали идеальную платформу для владельцев автомобилей премиум-класса, которые хотят
                                получать
                                гарантированный пассивный доход без рисков и хлопот
                            </p>

                            <div className="relative mt-16 sm:mt-24 hidden sm:block">
                                <div className="relative overflow-hidden rounded-lg">
                                    <Image
                                        src="/fwafwa.jpeg"
                                        alt="Премиальный автомобиль"
                                        width={600}
                                        height={800}
                                        className="object-cover w-full h-[400px] md:h-[500px] lg:h-[600px] transform hover:scale-105 transition-transform duration-700"
                                    />
                                </div>
                                <div className="absolute -bottom-8 -right-8 bg-white p-4 sm:p-6 shadow-xl max-w-xs">
                                    <p className="text-xs sm:text-sm font-light">
                                        Превратите ваш простаивающий автомобиль в источник стабильного дохода без лишних
                                        хлопот и забот.
                                    </p>
                                </div>
                            </div>
                        </div>

                        <div className="space-y-10 sm:space-y-16 md:mt-24">
                            <div className="group">
                                <div className="flex items-start">
                  <span
                      className="text-3xl sm:text-4xl md:text-5xl font-extralight text-gray-200 mr-4 sm:mr-6 group-hover:text-black transition-colors duration-300">
                    01
                  </span>
                                    <div>
                                        <h3 className="text-lg sm:text-xl font-light mb-2 sm:mb-4 tracking-wide">Высокий
                                            доход</h3>
                                        <p className="text-gray-600 font-light tracking-wide">
                                            Прозрачные условия и регулярные выплаты гарантируют стабильный ежемесячный
                                            заработок.
                                        </p>
                                    </div>
                                </div>
                            </div>

                            <div className="group">
                                <div className="flex items-start">
                  <span
                      className="text-3xl sm:text-4xl md:text-5xl font-extralight text-gray-200 mr-4 sm:mr-6 group-hover:text-black transition-colors duration-300">
                    02
                  </span>
                                    <div>
                                        <h3 className="text-lg sm:text-xl font-light mb-2 sm:mb-4 tracking-wide">Полная
                                            страховка</h3>
                                        <p className="text-gray-600 font-light tracking-wide">
                                            Ваш автомобиль застрахован на 100%. Мы покрываем любые повреждения, которые
                                            могут возникнуть во
                                            время аренды.
                                        </p>
                                    </div>
                                </div>
                            </div>

                            <div className="group">
                                <div className="flex items-start">
                  <span
                      className="text-3xl sm:text-4xl md:text-5xl font-extralight text-gray-200 mr-4 sm:mr-6 group-hover:text-black transition-colors duration-300">
                    03
                  </span>
                                    <div>
                                        <h3 className="text-lg sm:text-xl font-light mb-2 sm:mb-4 tracking-wide">Проверенные
                                            клиенты</h3>
                                        <p className="text-gray-600 font-light tracking-wide">
                                            Мы тщательно проверяем каждого клиента. Верификация документов и проверка по
                                            всем базам данных
                                            гарантирует безопасность.
                                        </p>
                                    </div>
                                </div>
                            </div>

                            <div className="group">
                                <div className="flex items-start">
                  <span
                      className="text-3xl sm:text-4xl md:text-5xl font-extralight text-gray-200 mr-4 sm:mr-6 group-hover:text-black transition-colors duration-300">
                    04
                  </span>
                                    <div>
                                        <h3 className="text-lg sm:text-xl font-light mb-2 sm:mb-4 tracking-wide">Поддержка
                                            24/7</h3>
                                        <p className="text-gray-600 font-light tracking-wide">
                                            Наша команда поддержки доступна круглосуточно. Мы решаем любые вопросы в
                                            любое время дня и ночи.
                                        </p>
                                    </div>
                                </div>
                            </div>

                            {/* Мобильная версия изображения */}
                            <div className="relative mt-8 sm:hidden">
                                <div className="relative overflow-hidden rounded-lg">
                                    <Image
                                        src="/fwafwa.jpeg"
                                        alt="Премиальный автомобиль"
                                        width={600}
                                        height={800}
                                        className="object-cover w-full h-[300px] transform hover:scale-105 transition-transform duration-700"
                                    />
                                </div>
                                <div className="absolute -bottom-4 -right-4 bg-white p-4 shadow-xl max-w-[200px]">
                                    <p className="text-xs font-light">
                                        Превратите ваш простаивающий автомобиль в источник стабильного дохода.
                                    </p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            {/* Как это работает */}
            <section id="process" ref={processRef} className="py-20 sm:py-24 md:py-32 relative">
                <div className="absolute top-0 left-0 w-1/2 h-full bg-gray-50 -z-10"></div>

                <div className="container mx-auto px-6 md:px-12 lg:px-16 relative">
                    <div className="max-w-3xl mb-16 sm:mb-24">
                        <h2 className="text-2xl sm:text-3xl md:text-4xl lg:text-5xl font-extralight mb-8 sm:mb-12 tracking-tight">
                            Процесс
                        </h2>
                        <p className="text-base sm:text-lg font-light text-gray-600 tracking-wide">
                            Четыре простых шага для начала получения дохода от вашего автомобиля
                        </p>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8">
                        <div className="relative group">
                            <div
                                className="absolute -inset-4 bg-gray-50 rounded-lg opacity-0 group-hover:opacity-100 transition-opacity duration-300 -z-10"></div>
                            <div className="mb-6 sm:mb-8 overflow-hidden">
                                <div
                                    className="w-16 h-16 sm:w-20 sm:h-20 border border-black rounded-full flex items-center justify-center mb-4 sm:mb-6 group-hover:bg-black group-hover:text-white transition-all duration-300">
                                    <span className="text-lg sm:text-xl font-light">01</span>
                                </div>
                            </div>
                            <h3 className="text-lg sm:text-xl font-light mb-2 sm:mb-4 tracking-wide">Регистрация
                                автомобиля</h3>
                            <p className="text-gray-600 font-light tracking-wide">
                                Оставьте информацию о своей машине нам на WhatsApp — мы свяжемся с вами и договоримся об
                                установке оборудования.
                            </p>
                        </div>

                        <div className="relative group">
                            <div
                                className="absolute -inset-4 bg-gray-50 rounded-lg opacity-0 group-hover:opacity-100 transition-opacity duration-300 -z-10"></div>
                            <div className="mb-6 sm:mb-8 overflow-hidden">
                                <div
                                    className="w-16 h-16 sm:w-20 sm:h-20 border border-black rounded-full flex items-center justify-center mb-4 sm:mb-6 group-hover:bg-black group-hover:text-white transition-all duration-300">
                                    <span className="text-lg sm:text-xl font-light">02</span>
                                </div>
                            </div>
                            <h3 className="text-lg sm:text-xl font-light mb-2 sm:mb-4 tracking-wide">Получение
                                бронирований</h3>
                            <p className="text-gray-600 font-light tracking-wide">
                                После проверки личности, водители могут бронировать ваш автомобиль, когда он доступен.
                            </p>
                        </div>

                        <div className="relative group">
                            <div
                                className="absolute -inset-4 bg-gray-50 rounded-lg opacity-0 group-hover:opacity-100 transition-opacity duration-300 -z-10"></div>
                            <div className="mb-6 sm:mb-8 overflow-hidden">
                                <div
                                    className="w-16 h-16 sm:w-20 sm:h-20 border border-black rounded-full flex items-center justify-center mb-4 sm:mb-6 group-hover:bg-black group-hover:text-white transition-all duration-300">
                                    <span className="text-lg sm:text-xl font-light">03</span>
                                </div>
                            </div>
                            <h3 className="text-lg sm:text-xl font-light mb-2 sm:mb-4 tracking-wide">Аренда без
                                хлопот</h3>
                            <p className="text-gray-600 font-light tracking-wide">
                                Водители могут найти, разблокировать и заблокировать ваш автомобиль с помощью своего
                                телефона после
                                осмотра.
                            </p>
                        </div>

                        <div className="relative group">
                            <div
                                className="absolute -inset-4 bg-gray-50 rounded-lg opacity-0 group-hover:opacity-100 transition-opacity duration-300 -z-10"></div>
                            <div className="mb-6 sm:mb-8 overflow-hidden">
                                <div
                                    className="w-16 h-16 sm:w-20 sm:h-20 border border-black rounded-full flex items-center justify-center mb-4 sm:mb-6 group-hover:bg-black group-hover:text-white transition-all duration-300">
                                    <span className="text-lg sm:text-xl font-light">04</span>
                                </div>
                            </div>
                            <h3 className="text-lg sm:text-xl font-light mb-2 sm:mb-4 tracking-wide">Получение
                                оплаты</h3>
                            <p className="text-gray-600 font-light tracking-wide">
                                Вы получаете гарантированный банковский перевод в начале каждого месяца, включая
                                компенсацию за топливо.
                            </p>
                        </div>
                    </div>

                    <div className="mt-16 sm:mt-24 text-center">
                        <Link
                            href={whatsappLink}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="group inline-flex items-center text-sm font-light tracking-widest hover:text-gray-500 transition-colors"
                        >
                            НАЧАТЬ СОТРУДНИЧЕСТВО
                            <span
                                className="ml-3 w-10 h-10 sm:w-12 sm:h-12 rounded-full border border-black flex items-center justify-center group-hover:bg-black group-hover:text-white transition-all duration-300">
                <ArrowRight className="h-4 w-4 sm:h-5 sm:w-5"/>
              </span>
                        </Link>
                    </div>
                </div>
            </section>

            {/* Безопасность */}
            <section id="security" ref={securityRef} className="py-20 sm:py-24 md:py-32 relative">
                <div className="container mx-auto px-6 md:px-12 lg:px-16">
                    <div className="grid md:grid-cols-2 gap-12 md:gap-16 items-center">
                        <div className="order-2 md:order-1">
                            <h2 className="text-2xl sm:text-3xl md:text-4xl lg:text-5xl font-extralight mb-8 sm:mb-12 tracking-tight">
                                Безопасность
                            </h2>
                            <p className="text-base sm:text-lg font-light text-gray-600 tracking-wide mb-10 sm:mb-16">
                                Мы разработали многоуровневую систему безопасности, чтобы гарантировать сохранность
                                вашего автомобиля
                            </p>

                            <div className="space-y-8 sm:space-y-12">
                                <div className="group">
                                    <div className="flex items-start">
                    <span
                        className="text-3xl sm:text-4xl md:text-5xl font-extralight text-gray-200 mr-4 sm:mr-6 group-hover:text-black transition-colors duration-300">
                      01
                    </span>
                                        <div>
                                            <h3 className="text-lg sm:text-xl font-light mb-2 sm:mb-4 tracking-wide">
                                                Тщательная проверка клиентов
                                            </h3>
                                            <p className="text-gray-600 font-light tracking-wide">
                                                Каждый клиент проходит строгую верификацию личности и проверку
                                                документов по всем базам данных.
                                            </p>
                                        </div>
                                    </div>
                                </div>

                                <div className="group">
                                    <div className="flex items-start">
                    <span
                        className="text-3xl sm:text-4xl md:text-5xl font-extralight text-gray-200 mr-4 sm:mr-6 group-hover:text-black transition-colors duration-300">
                      02
                    </span>
                                        <div>
                                            <h3 className="text-lg sm:text-xl font-light mb-2 sm:mb-4 tracking-wide">Детальный
                                                осмотр</h3>
                                            <p className="text-gray-600 font-light tracking-wide">
                                                Водители выполняют тщательный осмотр с 8 фотографиями при получении и
                                                возврате автомобиля.
                                            </p>
                                        </div>
                                    </div>
                                </div>

                                <div className="group">
                                    <div className="flex items-start">
                    <span
                        className="text-3xl sm:text-4xl md:text-5xl font-extralight text-gray-200 mr-4 sm:mr-6 group-hover:text-black transition-colors duration-300">
                      03
                    </span>
                                        <div>
                                            <h3 className="text-lg sm:text-xl font-light mb-2 sm:mb-4 tracking-wide">Система
                                                телеметрии</h3>
                                            <p className="text-gray-600 font-light tracking-wide">
                                                Наш датчик телеметрии отслеживает стиль вождения, выявляет агрессивную
                                                езду и при необходимости
                                                позволяет дистанционно блокировать автомобиль.
                                            </p>
                                        </div>
                                    </div>
                                </div>
                                <div className="group">
                                    <div className="flex items-start">
                    <span
                        className="text-3xl sm:text-4xl md:text-5xl font-extralight text-gray-200 mr-4 sm:mr-6 group-hover:text-black transition-colors duration-300">
                      04
                    </span>
                                        <div>
                                            <h3 className="text-lg sm:text-xl font-light mb-2 sm:mb-4 tracking-wide">
                                                Ограничение зоны использования
                                            </h3>
                                            <p className="text-gray-600 font-light tracking-wide">
                                                Автомобиль может использоваться только в пределах города, что
                                                минимизирует риски и обеспечивает
                                                дополнительную безопасность.
                                            </p>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div className="order-1 md:order-2 relative">
                            <div
                                className="absolute top-1/2 -right-6 sm:-right-12 transform -translate-y-1/2 w-16 h-16 sm:w-24 sm:h-24 bg-black rounded-full z-0"></div>
                            <div
                                className="absolute bottom-1/4 -left-6 sm:-left-12 transform -translate-y-1/2 w-32 h-32 sm:w-48 sm:h-48 bg-gray-50 rounded-full z-0"></div>
                        </div>
                    </div>
                </div>
            </section>

            {/* Скоро в App Store и Google Play */}
            <section id="app" ref={appRef} className="py-20 sm:py-24 md:py-32 bg-gray-50">
                <div className="container mx-auto px-6 md:px-12 lg:px-16">
                    <div className="grid md:grid-cols-2 gap-12 md:gap-16 items-center">
                        <div>
                            <h2 className="text-2xl sm:text-3xl md:text-4xl lg:text-5xl font-extralight mb-8 sm:mb-12 tracking-tight">
                                Мобильное приложение
                            </h2>
                            <p className="text-base sm:text-lg font-light text-gray-600 tracking-wide mb-10 sm:mb-16">
                                Скоро в App Store и Google Play. Управляйте своим автомобилем и доходом через удобное
                                мобильное
                                приложение
                            </p>

                            <div className="flex flex-col sm:flex-row gap-4 sm:gap-8">
                                <div
                                    className="border border-black px-6 sm:px-8 py-4 sm:py-6 inline-flex items-center group hover:bg-black hover:text-white transition-all duration-300">
                                    <div>
                                        <div
                                            className="text-xs font-light tracking-widest mb-1 group-hover:text-gray-300 transition-colors">
                                            СКОРО В
                                        </div>
                                        <div className="text-sm font-light tracking-widest">APP STORE</div>
                                    </div>
                                </div>

                                <div
                                    className="border border-black px-6 sm:px-8 py-4 sm:py-6 inline-flex items-center group hover:bg-black hover:text-white transition-all duration-300">
                                    <div>
                                        <div
                                            className="text-xs font-light tracking-widest mb-1 group-hover:text-gray-300 transition-colors">
                                            СКОРО В
                                        </div>
                                        <div className="text-sm font-light tracking-widest">GOOGLE PLAY</div>
                                    </div>
                                </div>
                            </div>

                            <div className="mt-10 sm:mt-16">
                                <p className="text-sm font-light text-gray-600 tracking-wide mb-6 sm:mb-8">
                                    Узнайте первыми о запуске приложения и получите специальные условия
                                </p>
                                <Link
                                    href={whatsappLink}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center px-6 py-4 bg-black text-white text-sm font-light tracking-widest hover:bg-gray-900 transition-colors"
                                >
                                    СВЯЗАТЬСЯ С МЕНЕДЖЕРОМ
                                    <ArrowRight className="ml-3 h-4 w-4"/>
                                </Link>
                            </div>
                        </div>

                        <div className="relative mt-12 md:mt-0">
                            <div
                                className="absolute top-1/3 -left-6 sm:-left-12 transform -translate-y-1/2 w-16 h-16 sm:w-24 sm:h-24 bg-black rounded-full z-0"></div>
                            <div
                                className="absolute bottom-1/4 -right-6 sm:-right-12 transform -translate-y-1/2 w-32 h-32 sm:w-48 sm:h-48 bg-white rounded-full z-0"></div>
                        </div>
                    </div>
                </div>
            </section>

            {/* CTA */}
            <section className="py-20 sm:py-24 md:py-32 relative overflow-hidden">
                <div className="absolute inset-0 z-0 opacity-5">
                    <div
                        className="absolute inset-0 bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-gray-700 via-gray-900 to-black"></div>
                </div>

                <div className="container mx-auto px-6 md:px-12 lg:px-16 relative z-10">
                    <div className="max-w-4xl mx-auto text-center">
                        <h2 className="text-2xl sm:text-3xl md:text-4xl lg:text-5xl xl:text-6xl font-extralight mb-8 sm:mb-12 tracking-tight">
                            Ваш автомобиль может приносить вам доход ежемесячно
                        </h2>
                        <p className="text-base sm:text-lg md:text-xl font-light text-gray-600 mb-10 sm:mb-16 tracking-wide">
                            Свяжитесь с нами прямо сейчас, чтобы узнать точную сумму, которую может приносить ваш
                            автомобиль.
                            Гарантированные выплаты в начале каждого месяца и полная страховка от всех рисков.
                        </p>
                        <Link
                            href={whatsappLink}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="group inline-flex items-center text-sm font-light tracking-widest hover:text-gray-500 transition-colors"
                        >
                            НАЧАТЬ СОТРУДНИЧЕСТВО
                            <span
                                className="ml-3 w-10 h-10 sm:w-12 sm:h-12 rounded-full border border-black flex items-center justify-center group-hover:bg-black group-hover:text-white transition-all duration-300">
                <ArrowRight className="h-4 w-4 sm:h-5 sm:w-5"/>
              </span>
                        </Link>
                    </div>
                </div>
            </section>

            {/* Футер */}
            <footer className="py-16 border-t border-gray-100">
                <div className="container mx-auto px-6 md:px-12 lg:px-16">
                    <div className="flex flex-col md:flex-row justify-between items-start">
                        <div className="mb-8 md:mb-0">
                            <div className="flex items-center mb-6">
                                <Image src="/Group.png" alt="AZV Motors" width={24} height={24} className="mr-3"/>
                                <span className="text-sm font-light tracking-widest">AZV MOTORS</span>
                            </div>
                            <p className="text-xs font-light text-gray-500 tracking-wide max-w-xs">
                                Сервис P2P каршеринга для владельцев премиальных автомобилей
                            </p>
                        </div>

                        <div className="grid grid-cols-2 md:grid-cols-3 gap-x-16 gap-y-8">
                            <div>
                                <h3 className="text-xs font-light tracking-widest mb-4">НАВИГАЦИЯ</h3>
                                <div className="space-y-3">
                                    <Link
                                        href="#benefits"
                                        className="block text-xs font-light text-gray-500 tracking-wide hover:text-gray-800 transition-colors"
                                    >
                                        Преимущества
                                    </Link>
                                    <Link
                                        href="#process"
                                        className="block text-xs font-light text-gray-500 tracking-wide hover:text-gray-800 transition-colors"
                                    >
                                        Процесс
                                    </Link>
                                    <Link
                                        href="#security"
                                        className="block text-xs font-light text-gray-500 tracking-wide hover:text-gray-800 transition-colors"
                                    >
                                        Безопасность
                                    </Link>
                                </div>
                            </div>

                            <div>
                                <h3 className="text-xs font-light tracking-widest mb-4">КОНТАКТЫ</h3>
                                <div className="space-y-3">
                                    <Link
                                        href={whatsappLink}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="block text-xs font-light text-gray-500 tracking-wide hover:text-gray-800 transition-colors"
                                    >
                                        Связаться в WhatsApp
                                    </Link>
                                </div>
                            </div>

                            <div>
                                <h3 className="text-xs font-light tracking-widest mb-4">ПРИЛОЖЕНИЕ</h3>
                                <div className="space-y-3">
                                    <span className="block text-xs font-light text-gray-500 tracking-wide">Скоро в App Store</span>
                                    <span className="block text-xs font-light text-gray-500 tracking-wide">Скоро в Google Play</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="mt-16 pt-8 border-t border-gray-100">
                        <p className="text-xs font-light text-gray-500 tracking-wide">
                            © {new Date().getFullYear()} AZV Motors. Все права защищены.
                        </p>
                    </div>
                </div>
            </footer>
        </div>
    )
}

