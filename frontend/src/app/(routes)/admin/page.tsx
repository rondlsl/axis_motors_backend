"use client"
import {useState, useMemo, useRef, useEffect} from "react"
import {GoogleMap, useLoadScript, OverlayView} from "@react-google-maps/api"
import toast from "react-hot-toast"
import Link from "next/link"
import {CarIcon, FileText, Map, Search} from "lucide-react"

const mapStyles = [
    // Скрываем все подписи
    {
        featureType: "all",
        elementType: "labels",
        stylers: [{visibility: "off"}],
    },
    // Но включаем текстовые подписи, относящиеся к номерам домов
    {
        featureType: "road",
        elementType: "labels.text",
        stylers: [{visibility: "on"}],
    },
    // Отключаем иконки
    {
        featureType: "all",
        elementType: "labels.icon",
        stylers: [{visibility: "off"}],
    },
    // Скрываем POI, транспорт и админку
    {
        featureType: "poi",
        elementType: "all",
        stylers: [{visibility: "off"}],
    },
    {
        featureType: "transit",
        elementType: "all",
        stylers: [{visibility: "off"}],
    },
    {
        featureType: "administrative",
        elementType: "all",
        stylers: [{visibility: "off"}],
    },
    // Убираем названия улиц (stroke — обводка текста)
    {
        featureType: "road",
        elementType: "labels.text.stroke",
        stylers: [{visibility: "off"}],
    },
]


type Car = {
    id: number
    name: string
    status: string
    lat: number
    lng: number
    fuel: number
    plate: string
    photos: string[]
    course: number
    user?: { name: string; selfie: string }
}

const mockCars: Car[] = [
    {
        id: 1,
        name: "MB CLA 45S",
        status: "В аренде",
        lat: 43.238949,
        lng: 76.945275,
        fuel: 50,
        plate: "666 AZV 02",
        photos: ["/car1.jpg"],
        course: 224,
        user: {name: "Иван Иванов", selfie: "/selfie.jpg"},
    },
    {
        id: 2,
        name: "BMW M4",
        status: "Свободно",
        lat: 43.225487,
        lng: 76.852154,
        fuel: 75,
        plate: "777 AZV 02",
        photos: ["/car2.jpg"],
        course: 356,
    },
    {
        id: 3,
        name: "Toyota Camry",
        status: "В аренде",
        lat: 43.259834,
        lng: 76.928672,
        fuel: 62,
        plate: "123 ABC 01",
        photos: ["/car3.jpg"],
        course: 13,
        user: {name: "Алексей Смирнов", selfie: "/selfie2.jpg"},
    },
    {
        id: 4,
        name: "Hyundai Sonata",
        status: "Свободно",
        lat: 43.203756,
        lng: 76.893451,
        fuel: 88,
        plate: "456 FGH 05",
        photos: ["/car4.jpg"],
        course: 175,
    },
    {
        id: 5,
        name: "Lexus RX",
        status: "У владельца",
        lat: 43.227658,
        lng: 76.949732,
        fuel: 45,
        plate: "789 XYZ 15",
        photos: ["/car5.jpg"],
        course: 152,
    },
    {
        id: 6,
        name: "Porsche Cayenne",
        status: "На тех обслуживании",
        lat: 43.233421,
        lng: 76.878965,
        fuel: 10,
        plate: "098 LMN 77",
        photos: ["/car6.jpg"],
        course: 168,
    },
    {
        id: 7,
        name: "Tesla Model 3",
        status: "Свободно",
        lat: 43.214587,
        lng: 76.926541,
        fuel: 85,
        plate: "001 EV 77",
        photos: ["/car7.jpg"],
        course: 264,
    },
    {
        id: 8,
        name: "Kia K5",
        status: "В аренде",
        lat: 43.241687,
        lng: 76.889324,
        fuel: 67,
        plate: "222 KIA 02",
        photos: ["/car8.jpg"],
        course: 82,
        user: {name: "Мария Петрова", selfie: "/selfie3.jpg"},
    },
    {
        id: 9,
        name: "Range Rover Sport",
        status: "Ожидает проверку",
        lat: 43.256789,
        lng: 76.945123,
        fuel: 30,
        plate: "555 RR 01",
        photos: ["/car9.jpg"],
        course: 115,
    },
    {
        id: 10,
        name: "Volkswagen Touareg",
        status: "Свободно",
        lat: 43.207896,
        lng: 76.911234,
        fuel: 94,
        plate: "321 VW 14",
        photos: ["/car10.jpg"],
        course: 105,
    },
    {
        id: 11,
        name: "Audi Q7",
        status: "Поломка",
        lat: 43.219876,
        lng: 76.876543,
        fuel: 15,
        plate: "007 AUD 01",
        photos: ["/car11.jpg"],
        course: 345,
    },
    {
        id: 12,
        name: "Nissan X-Trail",
        status: "В аренде",
        lat: 43.253421,
        lng: 76.912345,
        fuel: 56,
        plate: "999 NSN 06",
        photos: ["/car12.jpg"],
        course: 238,
        user: {name: "Сергей Казанцев", selfie: "/selfie4.jpg"},
    },
    {
        id: 13,
        name: "Chevrolet Malibu",
        status: "У владельца",
        lat: 43.231234,
        lng: 76.958765,
        fuel: 70,
        plate: "444 CHV 17",
        photos: ["/car13.jpg"],
        course: 53,
    },
    {
        id: 14,
        name: "Ford Mustang",
        status: "Свободно",
        lat: 43.244567,
        lng: 76.934521,
        fuel: 80,
        plate: "911 MST 02",
        photos: ["/car14.jpg"],
        course: 50,
    },
    {
        id: 15,
        name: "Mazda CX-5",
        status: "В аренде",
        lat: 43.211234,
        lng: 76.899876,
        fuel: 42,
        plate: "275 MZD 10",
        photos: ["/car15.jpg"],
        course: 126,
        user: {name: "Карина Ахметова", selfie: "/selfie5.jpg"},
    },
    {
        id: 16,
        name: "Honda Accord",
        status: "На тех обслуживании",
        lat: 43.235678,
        lng: 76.923456,
        fuel: 25,
        plate: "787 HND 02",
        photos: ["/car16.jpg"],
        course: 59,
    },
    {
        id: 17,
        name: "Subaru Forester",
        status: "Свободно",
        lat: 43.226789,
        lng: 76.889012,
        fuel: 89,
        plate: "345 SUB 19",
        photos: ["/car17.jpg"],
        course: 312,
    },
    {
        id: 18,
        name: "Mitsubishi Outlander",
        status: "Ожидает проверку",
        lat: 43.201234,
        lng: 76.935678,
        fuel: 37,
        plate: "567 MIT 05",
        photos: ["/car18.jpg"],
        course: 22,
    },
    {
        id: 19,
        name: "MINI Cooper S",
        status: "В аренде",
        lat: 43.248765,
        lng: 76.907654,
        fuel: 60,
        plate: "888 MIN 01",
        photos: ["/car19.jpg"],
        course: 280,
        user: {name: "Дмитрий Ли", selfie: "/selfie6.jpg"},
    },
    {
        id: 20,
        name: "Infiniti QX80",
        status: "Свободно",
        lat: 43.218765,
        lng: 76.945678,
        fuel: 82,
        plate: "100 INF 02",
        photos: ["/car20.jpg"],
        course: 118,
    },
]

const statuses = ["Все", "В аренде", "Свободно", "У владельца", "На тех обслуживании", "Ожидает проверку", "Поломка"]

export default function AdminMap() {
    const {isLoaded} = useLoadScript({googleMapsApiKey: "AIzaSyApE0cRqsT5FYfskKs5w5NjLfZwEBJQiJk"})
    const [selectedCar, setSelectedCar] = useState<Car | null>(null)
    const [filter, setFilter] = useState<string>("Все")
    const [searchQuery, setSearchQuery] = useState<string>("")
    const [isStatusDropdownOpen, setIsStatusDropdownOpen] = useState<boolean>(false)
    const [mapCenter, setMapCenter] = useState({lat: 43.222, lng: 76.851})
    const [mapZoom, setMapZoom] = useState(13)
    const [cars, setCars] = useState<Car[]>([])
    const [loading, setLoading] = useState(true)

    // Ссылка на карту
    const mapRef = useRef<google.maps.Map | null>(null)

    // Загрузка данных автомобилей
    useEffect(() => {
        const fetchCars = async () => {
            try {
                const token = localStorage.getItem('token')
                const response = await fetch('/api/admin/cars', {
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    }
                })
                
                if (response.ok) {
                    const data = await response.json()
                    setCars(data.cars || [])
                } else {
                    console.error('Failed to fetch cars')
                    // Fallback to mock data
                    setCars(mockCars)
                }
            } catch (error) {
                console.error('Error fetching cars:', error)
                // Fallback to mock data
                setCars(mockCars)
            } finally {
                setLoading(false)
            }
        }

        fetchCars()
    }, [])

    // Хук для установки ссылки на карту
    const onMapLoad = (map: google.maps.Map) => {
        mapRef.current = map
    }

    // Функция для выбора автомобиля и центрирования карты
    const handleCarSelect = (car: Car) => {
        setSelectedCar(car)
        setMapCenter({lat: car.lat, lng: car.lng})
        setMapZoom(16) // Увеличиваем зум при выборе машины

        // Если карта загружена, центрируем на выбранной машине
        if (mapRef.current) {
            mapRef.current.panTo({lat: car.lat, lng: car.lng})
            mapRef.current.setZoom(16)
        }
    }

    // Фильтрация по статусу и поиск по номеру
    const filteredCars = useMemo(() => {
        let result = cars

        // Применяем фильтр по статусу
        if (filter !== "Все") {
            result = result.filter((car) => car.status === filter)
        }

        // Применяем поиск по номеру
        if (searchQuery.trim() !== "") {
            const query = searchQuery.toLowerCase()
            result = result.filter((car) => car.plate.toLowerCase().includes(query))
        }

        return result
    }, [cars, filter, searchQuery])

    if (!isLoaded || loading) return <div className="flex items-center justify-center h-screen">Загрузка...</div>

    return (
        <div className="flex flex-col md:flex-row h-screen">
            {/* Responsive Navigation */}
            <nav
                className="fixed top-0 left-0 right-0 z-20 bg-white shadow-md p-3 flex justify-center gap-4 md:absolute md:top-4 md:left-4 md:right-auto">
                <Link href="/admin" className="hover:underline flex items-center gap-1">
                    <Map className="h-4 w-4"/>
                    <span>Карта</span>
                </Link>
                <Link href="/admin/applications" className="hover:underline flex items-center gap-1">
                    <FileText className="h-4 w-4"/>
                    <span>Пользователи</span>
                </Link>
                <Link href="/admin/cars" className="hover:underline flex items-center gap-1">
                    <CarIcon className="h-4 w-4"/>
                    <span>Машины</span>
                </Link>
            </nav>

            {/* Map - Full height on mobile, 2/3 width on desktop */}
            <div className="w-full h-[50vh] md:w-2/3 md:h-full mt-12 md:mt-0">
                <GoogleMap
                    mapContainerClassName="w-full h-full"
                    center={mapCenter}
                    zoom={mapZoom}
                    options={{
                        styles: mapStyles,
                        mapTypeControl: false,
                        fullscreenControl: false,
                        streetViewControl: false,
                        zoomControl: true,
                    }}
                    onLoad={onMapLoad}
                >
                    {filteredCars.map((car) => (
                        <OverlayView
                            key={car.id}
                            position={{lat: car.lat, lng: car.lng}}
                            mapPaneName={OverlayView.OVERLAY_MOUSE_TARGET}
                        >
                            <div className="relative w-12 h-12 cursor-pointer" onClick={() => handleCarSelect(car)}>
                                <img
                                    src="/bdb484610a7d3841199733ee9963ab8e.png"
                                    alt="Car Icon"
                                    className="w-4"
                                    style={{
                                        transform: `rotate(${car.course}deg)`,
                                        transformOrigin: "center",
                                        transition: "transform 0.3s ease",
                                    }}
                                />
                                <span
                                    className={`absolute -top-6 left-1/2 transform -translate-x-1/2 bg-white px-2 py-1 text-xs font-bold shadow-md rounded ${
                                        car.status === "В аренде"
                                            ? "text-green-600"
                                            : car.status === "Свободно"
                                                ? "text-blue-600"
                                                : car.status === "Ожидает проверку"
                                                    ? "text-yellow-600"
                                                    : car.status === "Поломка"
                                                        ? "text-red-600"
                                                        : car.status === "У владельца"
                                                            ? "text-purple-600"
                                                            : car.status === "На тех обслуживании"
                                                                ? "text-orange-600"
                                                                : "text-gray-600"
                                    }`}
                                >
                  {car.name}
                </span>
                            </div>
                        </OverlayView>
                    ))}
                </GoogleMap>
            </div>

            {/* Car list - Full width on mobile, 1/3 width on desktop */}
            <div className="w-full md:w-1/3 p-4 overflow-y-auto bg-gray-100 flex flex-col h-[50vh] md:h-full">
                {/* Поиск по номеру */}
                <div className="mb-4 relative">
                    <div className="flex w-full relative">
                        <input
                            type="text"
                            placeholder="Поиск по номеру..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="px-4 py-2 w-full rounded border focus:outline-none focus:ring-2 focus:ring-blue-300 pl-10"
                        />
                        <Search className="absolute left-3 top-2.5 text-gray-400" size={18}/>
                    </div>
                </div>

                {/* Выпадающее меню со статусами */}
                <div className="mb-4 relative">
                    <button
                        className="px-4 py-2 bg-white rounded border shadow w-full text-left flex justify-between items-center"
                        onClick={() => setIsStatusDropdownOpen(!isStatusDropdownOpen)}
                    >
                        <span>Статус: {filter}</span>
                        <span>{isStatusDropdownOpen ? "▲" : "▼"}</span>
                    </button>

                    {isStatusDropdownOpen && (
                        <div className="absolute left-0 right-0 mt-1 bg-white border rounded shadow-lg z-10">
                            {statuses.map((status) => (
                                <div
                                    key={status}
                                    className={`px-4 py-2 cursor-pointer hover:bg-gray-100 ${filter === status ? "bg-gray-200" : ""}`}
                                    onClick={() => {
                                        setFilter(status)
                                        setIsStatusDropdownOpen(false)
                                    }}
                                >
                                    {status}
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* Счетчик найденных автомобилей */}
                <div className="mb-2 text-sm text-gray-600">Найдено автомобилей: {filteredCars.length}</div>

                {/* Список машин */}
                {filteredCars.length > 0 ? (
                    filteredCars.map((car) => (
                        <div
                            key={car.id}
                            className={`p-4 bg-white rounded shadow mb-2 cursor-pointer hover:bg-gray-50 border-l-4 ${
                                car.status === "В аренде"
                                    ? "border-green-500"
                                    : car.status === "Свободно"
                                        ? "border-blue-500"
                                        : car.status === "Ожидает проверку"
                                            ? "border-yellow-500"
                                            : car.status === "Поломка"
                                                ? "border-red-500"
                                                : car.status === "У владельца"
                                                    ? "border-purple-500"
                                                    : car.status === "На тех обслуживании"
                                                        ? "border-orange-500"
                                                        : "border-gray-300"
                            } ${selectedCar?.id === car.id ? "ring-2 ring-blue-400" : ""}`}
                            onClick={() => handleCarSelect(car)}
                        >
                            <h3 className="text-lg font-bold">{car.name}</h3>
                            <div className="flex justify-between items-center">
                                <p className="text-sm font-medium">{car.plate}</p>
                                <span
                                    className={`text-xs px-2 py-1 rounded-full ${
                                        car.status === "В аренде"
                                            ? "bg-green-100 text-green-800"
                                            : car.status === "Свободно"
                                                ? "bg-blue-100 text-blue-800"
                                                : car.status === "Ожидает проверку"
                                                    ? "bg-yellow-100 text-yellow-800"
                                                    : car.status === "Поломка"
                                                        ? "bg-red-100 text-red-800"
                                                        : car.status === "У владельца"
                                                            ? "bg-purple-100 text-purple-800"
                                                            : car.status === "На тех обслуживании"
                                                                ? "bg-orange-100 text-orange-800"
                                                                : "bg-gray-100 text-gray-800"
                                    }`}
                                >
                  {car.status}
                </span>
                            </div>
                        </div>
                    ))
                ) : (
                    <div className="text-center py-8 text-gray-500">Автомобили не найдены</div>
                )}
            </div>

            {/* Детали машины - Full width on mobile, centered on desktop */}
            {selectedCar && (
                <div
                    className="fixed bottom-0 left-0 right-0 md:left-1/2 md:transform md:-translate-x-1/2 w-full md:w-96 p-4 bg-white shadow-lg rounded-t-lg z-20 border-t-4 border-blue-500">
                    <div className="flex justify-between items-center mb-2">
                        <h3 className="text-xl font-bold">{selectedCar.name}</h3>
                        <button onClick={() => setSelectedCar(null)} className="text-gray-500 hover:text-gray-700">
                            ✕
                        </button>
                    </div>

                    <div className="flex justify-between items-center">
                        <p className="text-sm font-medium">{selectedCar.plate}</p>
                        <span
                            className={`text-xs px-2 py-1 rounded-full ${
                                selectedCar.status === "В аренде"
                                    ? "bg-green-100 text-green-800"
                                    : selectedCar.status === "Свободно"
                                        ? "bg-blue-100 text-blue-800"
                                        : selectedCar.status === "Ожидает проверку"
                                            ? "bg-yellow-100 text-yellow-800"
                                            : selectedCar.status === "Поломка"
                                                ? "bg-red-100 text-red-800"
                                                : selectedCar.status === "У владельца"
                                                    ? "bg-purple-100 text-purple-800"
                                                    : selectedCar.status === "На тех обслуживании"
                                                        ? "bg-orange-100 text-orange-800"
                                                        : "bg-gray-100 text-gray-800"
                            }`}
                        >
              {selectedCar.status}
            </span>
                    </div>

                    {/* Координаты машины */}
                    <div className="text-xs text-gray-500 mt-1">
                        Координаты: {selectedCar.lat.toFixed(6)}, {selectedCar.lng.toFixed(6)}
                    </div>

                    {/* Прогресс-бар топлива */}
                    <div className="mt-3 mb-2">
                        <div className="flex justify-between text-xs mb-1">
                            <span>Топливо</span>
                            <span>{selectedCar.fuel}%</span>
                        </div>
                        <div className="w-full bg-gray-200 rounded-full h-2">
                            <div
                                className={`h-2 rounded-full ${
                                    selectedCar.fuel > 70 ? "bg-green-500" : selectedCar.fuel > 30 ? "bg-yellow-500" : "bg-red-500"
                                }`}
                                style={{width: `${selectedCar.fuel}%`}}
                            ></div>
                        </div>
                    </div>

                    <div className="flex gap-2 my-2 overflow-x-auto py-1">
                        {selectedCar.photos.map((photo, index) => (
                            <img
                                key={index}
                                src={photo || "/placeholder.svg"}
                                className="w-20 h-20 object-cover rounded shadow"
                                alt="Car"
                            />
                        ))}
                    </div>

                    {selectedCar.status === "В аренде" && selectedCar.user && (
                        <div className="mt-3 p-3 bg-gray-50 rounded">
                            <div className="flex items-center">
                                <img
                                    src={selectedCar.user.selfie || "/placeholder.svg"}
                                    className="w-10 h-10 rounded-full mr-3 object-cover border"
                                    alt="User Selfie"
                                />
                                <div>
                                    <p className="text-sm font-semibold">Арендатор</p>
                                    <p className="text-xs">{selectedCar.user.name}</p>
                                </div>
                            </div>
                        </div>
                    )}

                    <div className="flex gap-2 mt-4">
                        <button
                            className="flex-1 p-2 bg-green-500 text-white rounded hover:bg-green-600 transition"
                            onClick={() => toast.success("Машина открыта")}
                        >
                            Открыть
                        </button>
                        <button
                            className="flex-1 p-2 bg-red-500 text-white rounded hover:bg-red-600 transition"
                            onClick={() => toast.error("Машина закрыта")}
                        >
                            Закрыть
                        </button>
                    </div>
                </div>
            )}
        </div>
    )
}

