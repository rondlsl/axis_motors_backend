"use client"

import type React from "react"

import { useState, useEffect, useRef } from "react"
import Link from "next/link"
import { FileText, Map, Search, CarIcon, Plus, Filter, ArrowUpDown, X, Camera, Check } from "lucide-react"

interface Car {
  id: number
  name: string
  status: string
  photos: string[]
  plate: string
}

interface CarFormData {
  name: string
  vin: string
  plate: string
  pricePerMinute: string
  pricePerHour: string
  pricePerDay: string
  ownerPhone: string
  ownerFullName: string
  photos: string[]
}

const mockCars: Car[] = [
  { id: 1, name: "MB CLA 45S", status: "В аренде", photos: ["/car1.jpg"], plate: "666 AZV 02" },
  { id: 2, name: "BMW M4", status: "Свободно", photos: ["/car2.jpg"], plate: "777 AZV 02" },
  { id: 3, name: "Toyota Camry", status: "В аренде", photos: ["/car3.jpg"], plate: "123 AZV 02" },
  { id: 4, name: "Hyundai Sonata", status: "Свободно", photos: ["/car4.jpg"], plate: "456 AZV 02" },
  { id: 5, name: "Lexus RX", status: "У владельца", photos: ["/car5.jpg"], plate: "789 AZV 02" },
  { id: 6, name: "Tesla Model 3", status: "Свободно", photos: ["/car6.jpg"], plate: "321 AZV 02" },
]

// Вспомогательная функция для определения цвета статуса
const getStatusColor = (status: string) => {
  switch (status) {
    case "В аренде":
      return "bg-blue-100 text-blue-800"
    case "Свободно":
      return "bg-green-100 text-green-800"
    case "У владельца":
      return "bg-orange-100 text-orange-800"
    default:
      return "bg-gray-100 text-gray-800"
  }
}

const CarsPage = () => {
  const [page, setPage] = useState(1)
  const [searchQuery, setSearchQuery] = useState("")
  const [filteredCars, setFilteredCars] = useState<Car[]>(mockCars)
  const [sortBy, setSortBy] = useState<"name" | "status">("name")
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc")
  const [statusFilter, setStatusFilter] = useState<string>("")
  const pageSize = 4

  // Состояния для модального окна
  const [isModalOpen, setIsModalOpen] = useState(false)
  const modalRef = useRef<HTMLDivElement>(null)
  const initialFormData: CarFormData = {
    name: "",
    vin: "",
    plate: "",
    pricePerMinute: "",
    pricePerHour: "",
    pricePerDay: "",
    ownerPhone: "",
    ownerFullName: "",
    photos: ["", "", "", "", ""],
  }
  const [formData, setFormData] = useState<CarFormData>(initialFormData)
  const [activeStep, setActiveStep] = useState(1)
  const [errors, setErrors] = useState<{ [key: string]: string }>({})
  const [photoUploading, setPhotoUploading] = useState<{ [key: number]: boolean }>({})

  // Обработка поиска, фильтрации и сортировки
  useEffect(() => {
    let result = [...mockCars]

    // Поиск по номеру
    if (searchQuery) {
      result = result.filter(
        (car) =>
          car.plate.toLowerCase().includes(searchQuery.toLowerCase()) ||
          car.name.toLowerCase().includes(searchQuery.toLowerCase()),
      )
    }

    // Фильтрация по статусу
    if (statusFilter) {
      result = result.filter((car) => car.status === statusFilter)
    }

    // Сортировка
    result.sort((a, b) => {
      if (sortBy === "name") {
        return sortDirection === "asc" ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name)
      } else {
        return sortDirection === "asc" ? a.status.localeCompare(b.status) : b.status.localeCompare(a.status)
      }
    })

    setFilteredCars(result)
    // Сбрасываем страницу при изменении результатов поиска
    setPage(1)
  }, [searchQuery, sortBy, sortDirection, statusFilter])

  // Закрытие модального окна при клике вне его области
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (modalRef.current && !modalRef.current.contains(event.target as Node)) {
        setIsModalOpen(false)
      }
    }

    if (isModalOpen) {
      document.addEventListener("mousedown", handleClickOutside)
    }

    return () => {
      document.removeEventListener("mousedown", handleClickOutside)
    }
  }, [isModalOpen])

  const toggleSort = (field: "name" | "status") => {
    if (sortBy === field) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc")
    } else {
      setSortBy(field)
      setSortDirection("asc")
    }
  }

  // Открытие модального окна
  const openModal = () => {
    setIsModalOpen(true)
    setFormData(initialFormData)
    setActiveStep(1)
    setErrors({})
  }

  // Закрытие модального окна
  const closeModal = () => {
    setIsModalOpen(false)
  }

  // Обработка изменения полей формы
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target
    setFormData((prev) => ({ ...prev, [name]: value }))

    // Очистка ошибки при изменении поля
    if (errors[name]) {
      setErrors((prev) => ({ ...prev, [name]: "" }))
    }
  }

  // Симуляция загрузки фотографии
  const handlePhotoUpload = (index: number) => {
    setPhotoUploading((prev) => ({ ...prev, [index]: true }))

    // Имитация загрузки
    setTimeout(() => {
      setPhotoUploading((prev) => ({ ...prev, [index]: false }))
      setFormData((prev) => {
        const newPhotos = [...prev.photos]
        newPhotos[index] = `/car${Math.floor(Math.random() * 6) + 1}.jpg`
        return { ...prev, photos: newPhotos }
      })
    }, 1500)
  }

  // Удаление фотографии
  const removePhoto = (index: number) => {
    setFormData((prev) => {
      const newPhotos = [...prev.photos]
      newPhotos[index] = ""
      return { ...prev, photos: newPhotos }
    })
  }

  // Валидация формы
  const validateForm = () => {
    const newErrors: { [key: string]: string } = {}

    if (activeStep === 1) {
      if (!formData.name.trim()) newErrors.name = "Введите название автомобиля"
      if (!formData.vin.trim()) newErrors.vin = "Введите VIN номер"
      if (!formData.plate.trim()) newErrors.plate = "Введите номер автомобиля"
    } else if (activeStep === 2) {
      if (!formData.pricePerMinute.trim()) newErrors.pricePerMinute = "Введите стоимость поминутно"
      if (!formData.pricePerHour.trim()) newErrors.pricePerHour = "Введите стоимость почасово"
      if (!formData.pricePerDay.trim()) newErrors.pricePerDay = "Введите стоимость посуточно"
    } else if (activeStep === 3) {
      if (!formData.ownerFullName.trim()) newErrors.ownerFullName = "Введите ФИО владельца"
      if (!formData.ownerPhone.trim()) newErrors.ownerPhone = "Введите телефон владельца"
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  // Переход к следующему шагу
  const goToNextStep = () => {
    if (validateForm()) {
      setActiveStep((prev) => Math.min(prev + 1, 4))
    }
  }

  // Переход к предыдущему шагу
  const goToPrevStep = () => {
    setActiveStep((prev) => Math.max(prev - 1, 1))
  }

  // Обработка отправки формы
  const handleSubmit = () => {
    // Здесь будет логика добавления нового автомобиля в базу
    alert("Автомобиль успешно добавлен!")
    setIsModalOpen(false)

    // В реальном приложении здесь был бы запрос к API
    const newCar: Car = {
      id: mockCars.length + 1,
      name: formData.name,
      status: "Свободно",
      photos: formData.photos.filter((p) => p !== ""),
      plate: formData.plate,
    }

    mockCars.push(newCar)
    setFilteredCars([...mockCars])
  }

  // Получаем статусы для фильтра
  const uniqueStatuses = Array.from(new Set(mockCars.map((car) => car.status)))

  // Пагинация отфильтрованных результатов
  const paginatedCars = filteredCars.slice((page - 1) * pageSize, page * pageSize)
  const totalPages = Math.ceil(filteredCars.length / pageSize)

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Навигация/хедер */}
      <header className="bg-white shadow-sm border-b border-gray-200 sticky top-0 z-10">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="text-lg font-semibold text-gray-800">Azv Motors</div>
          <nav className="hidden md:flex items-center space-x-6">
            <Link href="/admin" className="flex items-center gap-2 text-gray-600 hover:text-blue-600 transition-colors">
              <Map className="h-4 w-4" />
              <span>Карта</span>
            </Link>
            <Link
              href="/admin/applications"
              className="flex items-center gap-2 text-gray-600 hover:text-blue-600 transition-colors"
            >
              <FileText className="h-4 w-4" />
              <span>Пользователи</span>
            </Link>
            <Link href="/admin/cars" className="flex items-center gap-2 text-blue-600 font-medium">
              <CarIcon className="h-4 w-4" />
              <span>Машины</span>
            </Link>
          </nav>
          <div className="md:hidden">
            <button className="p-2 text-gray-600">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                className="h-6 w-6"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6">
        {/* Заголовок и контролы */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between mb-6 gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-800">Список автомобилей</h1>
            <p className="text-gray-500 mt-1">Всего автомобилей: {filteredCars.length}</p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={openModal}
              className="inline-flex items-center gap-2 px-4 py-2 bg-white-100 border-2 border-gray-200 font-medium rounded-lg hover:bg-gray-300 transition-colors"
            >
              <Plus size={16} />
              <span>Добавить авто</span>
            </button>
          </div>
        </div>

        {/* Строка поиска и фильтры */}
        <div className="bg-white p-4 rounded-lg shadow-sm mb-6">
          <div className="flex flex-col space-y-4 md:space-y-0 md:flex-row md:gap-4">
            <div className="relative flex-grow">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <Search className="h-5 w-5 text-gray-400" />
              </div>
              <input
                type="text"
                placeholder="Поиск по номеру или названию..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="block w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            <div className="flex flex-wrap gap-2">
              <div className="relative w-full sm:w-auto">
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="appearance-none w-full sm:w-auto pl-8 pr-8 py-2 border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                >
                  <option value="">Все статусы</option>
                  {uniqueStatuses.map((status) => (
                    <option key={status} value={status}>
                      {status}
                    </option>
                  ))}
                </select>
                <div className="absolute inset-y-0 left-0 pl-2 flex items-center pointer-events-none">
                  <Filter className="h-4 w-4 text-gray-400" />
                </div>
              </div>

              <button
                onClick={() => toggleSort("name")}
                className={`flex items-center gap-1 px-3 py-2 border rounded-lg ${sortBy === "name" ? "border-blue-500 text-blue-600" : "border-gray-300 text-gray-600"}`}
              >
                <span>Название</span>
                <ArrowUpDown size={14} />
              </button>

              <button
                onClick={() => toggleSort("status")}
                className={`flex items-center gap-1 px-3 py-2 border rounded-lg ${sortBy === "status" ? "border-blue-500 text-blue-600" : "border-gray-300 text-gray-600"}`}
              >
                <span>Статус</span>
                <ArrowUpDown size={14} />
              </button>
            </div>
          </div>
        </div>

        {/* Список автомобилей */}
        {paginatedCars.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {paginatedCars.map((car) => (
              <Link key={car.id} href={`/admin/cars/${car.id}`} className="block">
                <div className="bg-white border border-gray-200 rounded-lg overflow-hidden hover:shadow-md transition-shadow duration-300 h-full flex flex-col">
                  <div className="relative">
                    <img
                      src={car.photos[0] || "/placeholder.svg"}
                      alt={car.name}
                      className="w-full h-40 sm:h-48 object-cover"
                    />
                    <div className="absolute bottom-2 right-2">
                      <span
                        className={`inline-block px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(car.status)}`}
                      >
                        {car.status}
                      </span>
                    </div>
                  </div>
                  <div className="p-4 flex-grow flex flex-col justify-between">
                    <h2 className="text-lg font-semibold text-gray-800">{car.name}</h2>
                    <div className="flex justify-between items-center mt-2">
                      <span className="text-sm font-medium bg-gray-100 px-2 py-1 rounded text-gray-700">
                        {car.plate}
                      </span>
                      <span className="text-blue-600 text-sm">Подробнее →</span>
                    </div>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <div className="bg-white p-8 rounded-lg text-center">
            <div className="mx-auto w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mb-4">
              <Search className="h-6 w-6 text-gray-400" />
            </div>
            <h3 className="text-lg font-medium text-gray-800">Ничего не найдено</h3>
            <p className="text-gray-500 mt-1">Попробуйте изменить параметры поиска</p>
            {searchQuery && (
              <button
                onClick={() => {
                  setSearchQuery("")
                  setStatusFilter("")
                }}
                className="mt-4 text-blue-600 hover:text-blue-800"
              >
                Сбросить фильтры
              </button>
            )}
          </div>
        )}

        {/* Пагинация */}
        {filteredCars.length > pageSize && (
          <div className="mt-6 flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="text-sm text-gray-600 order-2 sm:order-1">
              Страница {page} из {totalPages}
            </div>
            <div className="flex gap-2 w-full sm:w-auto justify-center sm:justify-end order-1 sm:order-2">
              <button
                disabled={page === 1}
                onClick={() => setPage(page - 1)}
                className="px-4 py-2 bg-white border border-gray-300 rounded-lg disabled:opacity-50 hover:bg-gray-50 transition-colors"
              >
                Назад
              </button>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage(page + 1)}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg disabled:opacity-50 hover:bg-blue-700 transition-colors"
              >
                Вперед
              </button>
            </div>
          </div>
        )}
      </main>

      {/* Модальное окно добавления автомобиля */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-2 sm:p-4">
          <div
            ref={modalRef}
            className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col"
          >
            {/* Заголовок модального окна */}
            <div className="flex items-center justify-between border-b border-gray-200 p-3 sm:p-4">
              <h2 className="text-lg sm:text-xl font-semibold text-gray-800">Добавление нового автомобиля</h2>
              <button onClick={closeModal} className="text-gray-500 hover:text-gray-700 transition-colors">
                <X size={20} />
              </button>
            </div>

            {/* Прогресс заполнения формы */}
            <div className="px-3 sm:px-6 pt-4">
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center flex-grow">
                  <div
                    className={`w-6 h-6 sm:w-8 sm:h-8 rounded-full flex items-center justify-center text-xs sm:text-sm ${activeStep >= 1 ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-600"}`}
                  >
                    1
                  </div>
                  <div
                    className={`h-1 flex-grow mx-1 sm:mx-2 ${activeStep >= 2 ? "bg-blue-600" : "bg-gray-200"}`}
                  ></div>
                  <div
                    className={`w-6 h-6 sm:w-8 sm:h-8 rounded-full flex items-center justify-center text-xs sm:text-sm ${activeStep >= 2 ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-600"}`}
                  >
                    2
                  </div>
                  <div
                    className={`h-1 flex-grow mx-1 sm:mx-2 ${activeStep >= 3 ? "bg-blue-600" : "bg-gray-200"}`}
                  ></div>
                  <div
                    className={`w-6 h-6 sm:w-8 sm:h-8 rounded-full flex items-center justify-center text-xs sm:text-sm ${activeStep >= 3 ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-600"}`}
                  >
                    3
                  </div>
                  <div
                    className={`h-1 flex-grow mx-1 sm:mx-2 ${activeStep >= 4 ? "bg-blue-600" : "bg-gray-200"}`}
                  ></div>
                  <div
                    className={`w-6 h-6 sm:w-8 sm:h-8 rounded-full flex items-center justify-center text-xs sm:text-sm ${activeStep >= 4 ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-600"}`}
                  >
                    4
                  </div>
                </div>
              </div>

              <div className="text-xs text-gray-500 mb-2">
                {activeStep === 1 && "Основная информация об автомобиле"}
                {activeStep === 2 && "Стоимость аренды"}
                {activeStep === 3 && "Информация о владельце"}
                {activeStep === 4 && "Фотографии автомобиля"}
              </div>
            </div>

            {/* Содержимое формы */}
            <div className="px-3 sm:px-6 py-4 overflow-y-auto flex-grow">
              {/* Шаг 4: Загрузка фотографий */}
              {activeStep === 4 && (
                <div>
                  <p className="text-sm text-gray-600 mb-4">Загрузите до 5 фотографий автомобиля в хорошем качестве</p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4">
                    {formData.photos.map((photo, index) => (
                      <div key={index} className="relative">
                        {photo ? (
                          <div className="relative rounded-lg overflow-hidden group h-32 sm:h-40">
                            <img
                              src={photo || "/placeholder.svg"}
                              alt={`Фото ${index + 1}`}
                              className="w-full h-full object-cover"
                            />
                            <div className="absolute inset-0 bg-black bg-opacity-50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                              <button
                                onClick={() => removePhoto(index)}
                                className="p-2 bg-red-600 rounded-full text-white"
                              >
                                <X size={16} />
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div
                            className={`border-2 border-dashed rounded-lg p-3 sm:p-4 flex flex-col items-center justify-center h-32 sm:h-40 ${errors[`photo${index}`] ? "border-red-500" : "border-gray-300"} hover:border-blue-500 cursor-pointer transition-colors`}
                            onClick={() => handlePhotoUpload(index)}
                          >
                            {photoUploading[index] ? (
                              <div className="flex flex-col items-center">
                                <div className="w-6 h-6 sm:w-8 sm:h-8 border-2 border-t-2 border-blue-500 border-t-transparent rounded-full animate-spin mb-2"></div>
                                <span className="text-sm text-gray-500">Загрузка...</span>
                              </div>
                            ) : (
                              <>
                                <Camera className="w-6 h-6 sm:w-8 sm:h-8 text-gray-400 mb-2" />
                                <span className="text-sm text-gray-500">Фото {index + 1}</span>
                                <span className="text-xs text-gray-400 mt-1">Нажмите для загрузки</span>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
            {/* Футер модального окна с кнопками */}
            <div className="border-t border-gray-200 p-3 sm:p-4 bg-gray-50 flex justify-between">
              {activeStep > 1 && (
                <button
                  onClick={goToPrevStep}
                  className="px-3 sm:px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition-colors text-sm sm:text-base"
                >
                  Назад
                </button>
              )}

              {activeStep < 4 ? (
                <button
                  onClick={goToNextStep}
                  className="px-4 sm:px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors ml-auto text-sm sm:text-base"
                >
                  Далее
                </button>
              ) : (
                <button
                  onClick={handleSubmit}
                  className="px-4 sm:px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors flex items-center gap-2 ml-auto text-sm sm:text-base"
                >
                  <Check size={16} />
                  <span className="hidden sm:inline">Добавить автомобиль</span>
                  <span className="sm:hidden">Добавить</span>
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default CarsPage

