"use client"

import { useParams, useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { ArrowLeft, Fuel, Calendar, User, CarIcon } from "lucide-react"
import Image from "next/image"

interface Car {
  id: number
  name: string
  status: string
  fuel: number
  plate: string
  photos: string[]
  owner?: { name: string; contact: string }
  user?: { name: string; selfie: string }
  trips?: { date: string; time: string; price: string }[]
}

const mockCars: Car[] = [
  {
    id: 1,
    name: "MB CLA 45S",
    status: "В аренде",
    fuel: 50,
    plate: "666 AZV 02",
    photos: ["/car1.jpg"],
    owner: { name: "Владимир Сидоров", contact: "+7 777 123 45 67" },
    user: { name: "Иван Иванов", selfie: "/selfie.jpg" },
    trips: [
      { date: "2025-03-10", time: "14:00", price: "5000₸" },
      { date: "2025-03-09", time: "12:30", price: "4500₸" },
    ],
  },
]

// Вспомогательная функция для определения цвета статуса
const getStatusColor = (status: string) => {
  switch (status) {
    case "В аренде":
      return "bg-blue-100 text-blue-800"
    case "Свободен":
      return "bg-green-100 text-green-800"
    case "На обслуживании":
      return "bg-orange-100 text-orange-800"
    default:
      return "bg-gray-100 text-gray-800"
  }
}

const CarDetailsPage = () => {
  const params = useParams()
  const router = useRouter()
  const [car, setCar] = useState<Car | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    setIsLoading(true)
    // В App Router, params.id будет строкой или массивом строк
    const carId =
      typeof params.id === "string" ? Number(params.id) : Array.isArray(params.id) ? Number(params.id[0]) : 0

    // Имитация загрузки для лучшего UX
    setTimeout(() => {
      const foundCar = mockCars.find((c) => c.id === carId)
      setCar(foundCar || null)
      setIsLoading(false)
    }, 300)
  }, [params.id])

  const handleGoBack = () => {
    router.push("/admin/cars")
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[200px] sm:min-h-[300px] p-4">
        <div className="w-10 h-10 sm:w-12 sm:h-12 border-4 border-t-4 border-blue-500 rounded-full animate-spin"></div>
        <p className="mt-4 text-gray-600">Загрузка данных...</p>
      </div>
    )
  }

  if (!car) {
    return (
      <div className="p-6 text-center">
        <div className="p-4 bg-red-50 rounded-lg mb-4">
          <p className="text-red-600">Автомобиль не найден</p>
        </div>
        <button
          onClick={handleGoBack}
          className="flex items-center justify-center px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors"
        >
          <ArrowLeft size={16} className="mr-2" />
          Вернуться к списку
        </button>
      </div>
    )
  }

  return (
    <div className="w-full max-w-4xl mx-auto p-3 sm:p-4 bg-white shadow-sm rounded-lg">
      {/* Шапка с кнопкой назад */}
      <div className="flex flex-wrap items-center gap-2 mb-6">
        <button
          onClick={handleGoBack}
          className="flex items-center justify-center p-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors"
          aria-label="Вернуться назад"
        >
          <ArrowLeft size={20} />
        </button>
        <h1 className="text-xl sm:text-2xl font-bold">{car.name}</h1>
        <span className={`ml-auto px-3 py-1 rounded-full text-sm font-medium ${getStatusColor(car.status)}`}>
          {car.status}
        </span>
      </div>

      {/* Фото автомобиля */}
      <div className="relative rounded-lg overflow-hidden mb-6 aspect-video">
        <Image
          src={car.photos[0] || "/placeholder.svg"}
          alt={car.name}
          className="object-cover"
          fill
          sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"
          priority
        />
        <div className="absolute bottom-4 right-4 bg-white px-3 py-1 rounded-full shadow-md">
          <p className="font-semibold">{car.plate}</p>
        </div>
      </div>

      {/* Информация об автомобиле в карточках */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
        <div className="p-4 bg-gray-50 rounded-lg flex items-center">
          <div className="p-3 bg-blue-100 rounded-full mr-3">
            <Fuel size={24} className="text-blue-600" />
          </div>
          <div>
            <p className="text-sm text-gray-500">Уровень топлива</p>
            <div className="relative w-full h-3 bg-gray-200 rounded-full mt-1 overflow-hidden">
              <div className="absolute top-0 left-0 h-full bg-blue-500" style={{ width: `${car.fuel}%` }}></div>
            </div>
            <p className="text-sm font-medium mt-1">{car.fuel}%</p>
          </div>
        </div>
        <div className="p-4 bg-gray-50 rounded-lg flex items-center">
          <div className="p-3 bg-purple-100 rounded-full mr-3">
            <CarIcon size={24} className="text-purple-600" />
          </div>
          <div>
            <p className="text-sm text-gray-500">Государственный номер</p>
            <p className="font-medium">{car.plate}</p>
          </div>
        </div>
      </div>

      {/* Владелец */}
      {car.owner && (
        <div className="mb-6 p-3 sm:p-4 border border-gray-100 rounded-lg">
          <h2 className="text-base sm:text-lg font-semibold mb-2 sm:mb-3 flex items-center">
            <User size={18} className="mr-2 text-gray-600" />
            Владелец
          </h2>
          <div className="pl-2 border-l-2 border-gray-200">
            <p className="font-medium">{car.owner.name}</p>
            <p className="text-gray-600">{car.owner.contact}</p>
          </div>
        </div>
      )}

      {/* Текущий арендатор */}
      {car.status === "В аренде" && car.user && (
        <div className="mb-6 p-3 sm:p-4 border border-blue-100 bg-blue-50 rounded-lg">
          <h2 className="text-base sm:text-lg font-semibold mb-2 sm:mb-3">Текущий арендатор</h2>
          <div className="flex items-center gap-3 pl-2">
            <div className="relative w-10 h-10 sm:w-12 sm:h-12 rounded-full overflow-hidden">
              <Image
                src={car.user.selfie || "/placeholder.svg"}
                alt={car.user.name}
                className="object-cover border-2 border-white shadow-sm"
                fill
                sizes="48px"
              />
            </div>
            <div>
              <p className="font-medium">{car.user.name}</p>
              <p className="text-sm text-blue-700 underline cursor-pointer">Показать детали</p>
            </div>
          </div>
        </div>
      )}

      {/* История поездок */}
      {car.trips && car.trips.length > 0 && (
        <div className="mb-4">
          <h2 className="text-lg font-semibold mb-3 flex items-center">
            <Calendar size={18} className="mr-2 text-gray-600" />
            История поездок
          </h2>
          <div className="bg-gray-50 rounded-lg overflow-hidden">
            <ul className="divide-y divide-gray-200">
              {car.trips.map((trip, index) => (
                <li
                  key={index}
                  className="flex flex-wrap justify-between items-center p-4 hover:bg-gray-100 transition-colors gap-2"
                >
                  <div className="flex flex-col">
                    <span className="font-medium">{trip.date}</span>
                    <span className="text-sm text-gray-500">{trip.time}</span>
                  </div>
                  <span className="font-semibold">{trip.price}</span>
                  <button className="px-3 py-1 bg-white border border-blue-200 text-blue-600 rounded-md hover:bg-blue-50 transition-colors">
                    Подробнее
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div className="mt-2 text-right">
            <button className="text-blue-600 font-medium hover:underline">Показать всю историю</button>
          </div>
        </div>
      )}
    </div>
  )
}

export default CarDetailsPage

