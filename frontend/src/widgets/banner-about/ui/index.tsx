'use client'

import {useState, useRef, useEffect} from 'react'
import {BannerTitle} from "shared/ui"

export const BannerAbout = () => {
    const [isModalOpen, setIsModalOpen] = useState(false)
    const [successMessage, setSuccessMessage] = useState('')
    const [errorMessage, setErrorMessage] = useState('')
    const [phone, setPhone] = useState('')
    const modalRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (modalRef.current && !modalRef.current.contains(event.target as Node)) {
                setIsModalOpen(false)
            }
        }

        if (isModalOpen) {
            document.addEventListener('mousedown', handleClickOutside)
        }

        return () => {
            document.removeEventListener('mousedown', handleClickOutside)
        }
    }, [isModalOpen])

    const formatPhoneNumber = (value: string) => {
        // Убираем все не цифры
        const number = value.replace(/[^\d]/g, '')

        // Ограничиваем длину до 11 цифр (с учетом +7)
        const truncated = number.slice(0, 11)

        // Форматируем номер
        if (truncated.length === 0) return ''
        if (truncated.length <= 1) return `+7 ${truncated}`
        if (truncated.length <= 4) return `+7 ${truncated.slice(1)}`
        if (truncated.length <= 7) return `+7 ${truncated.slice(1, 4)} ${truncated.slice(4)}`
        if (truncated.length <= 9) return `+7 ${truncated.slice(1, 4)} ${truncated.slice(4, 7)} ${truncated.slice(7)}`
        return `+7 ${truncated.slice(1, 4)} ${truncated.slice(4, 7)} ${truncated.slice(7, 9)} ${truncated.slice(9)}`
    }

    const handlePhoneChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const value = e.target.value
        setPhone(formatPhoneNumber(value))
    }

    const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault()

        // Симулируем успешную отправку формы
        setSuccessMessage('Спасибо! Ваша заявка успешно отправлена. Наши представители свяжутся с вами в ближайшее время.')
        setErrorMessage('')
        event.currentTarget.reset()
        setPhone('')

        // Опционально: можно добавить вывод данных формы в консоль для отладки
        const formData = new FormData(event.currentTarget)
        formData.set('phone', phone) // Добавляем телефон к формдате
        console.log('Отправленные данные:', Object.fromEntries(formData))
    }

    return (
        <div className="self-center flex flex-col items-center space-y-6 px-4 max-w-4xl w-full">
            <BannerTitle title="Сдать авто"/>
            <div className="space-y-6 text-center">
                <h2 className="text-4xl font-bold">Пассивный заработок на своем авто</h2>
                <p className="text-gray-600 text-md">
                    Мы сотрудничаем с владельцами автомобилей для расширения нашего автопарка.
                    Если вы хотите сдать свой автомобиль в аренду, нажмите на кнопку ниже и отправьте информацию о своей
                    машине.
                </p>
                <button
                    onClick={() => setIsModalOpen(true)}
                    className="bg-blue-600 text-white px-6 py-3 rounded-lg text-lg font-semibold hover:bg-blue-700 transition-colors"
                >
                    Сдать свой автомобиль в аренду
                </button>
            </div>

            {isModalOpen && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
                    <div ref={modalRef}
                         className="relative bg-white rounded-lg p-6 max-w-md w-full max-h-[90vh] overflow-y-auto">
                        <h3 className="text-2xl font-bold mb-2">Отправьте данные о вашем автомобиле</h3>
                        <p className="text-gray-600 mb-4 text-sm">Заполните форму, чтобы предложить свой автомобиль в
                            аренду. Мы с вами свяжемся.</p>

                        {/* Отображение сообщений об успехе или ошибке */}
                        {successMessage && (
                            <div className="bg-green-100 text-green-800 p-3 rounded-md mb-3">
                                {successMessage}
                            </div>
                        )}
                        {errorMessage && (
                            <div className="bg-red-100 text-red-800 p-3 rounded-md mb-3">
                                {errorMessage}
                            </div>
                        )}

                        <form onSubmit={handleSubmit} className="space-y-3">
                            <input
                                placeholder="Ваше полное имя"
                                name="fullName"
                                required
                                className="w-full px-3 py-2 border border-gray-300 rounded-md"
                            />

                            <input
                                placeholder="Номер телефона"
                                name="phone"
                                required
                                value={phone}
                                onChange={handlePhoneChange}
                                className="w-full px-3 py-2 border border-gray-300 rounded-md"
                            />

                            <div className="grid grid-cols-2 gap-3">
                                <input
                                    placeholder="Марка автомобиля"
                                    name="carBrand"
                                    required
                                    className="px-3 py-2 border border-gray-300 rounded-md"
                                />
                                <input
                                    placeholder="Модель автомобиля"
                                    name="carModel"
                                    required
                                    className="px-3 py-2 border border-gray-300 rounded-md"
                                />
                            </div>

                            <div className="grid grid-cols-3 gap-3">
                                <input
                                    placeholder="Объем двигателя (л)"
                                    name="engineCapacity"
                                    type="number"
                                    step="0.1"
                                    required
                                    className="px-3 py-2 border border-gray-300 rounded-md"
                                />
                                <input
                                    placeholder="Год выпуска"
                                    name="yearOfManufacture"
                                    type="number"
                                    required
                                    className="px-3 py-2 border border-gray-300 rounded-md"
                                />
                                <input
                                    placeholder="Пробег"
                                    name="mileage"
                                    type="number"
                                    required
                                    className="px-3 py-2 border border-gray-300 rounded-md"
                                />
                            </div>

                            <input
                                name="photos"
                                type="file"
                                multiple
                                required
                                accept="image/*"
                                className="w-full px-3 py-2 border border-gray-300 rounded-md"
                            />

                            <button type="submit"
                                    className="w-full bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 transition-colors">
                                Отправить
                            </button>
                        </form>
                        <button
                            onClick={() => setIsModalOpen(false)}
                            className="absolute top-2 right-2 text-gray-500 hover:text-gray-700"
                            aria-label="Закрыть модальное окно"
                        >
                            ✕
                        </button>
                    </div>
                </div>
            )}
        </div>
    )
}