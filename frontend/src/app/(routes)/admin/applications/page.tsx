"use client"

import {useState} from "react"
import Link from "next/link"
import {ChevronLeft, ChevronRight, Search, SortAsc, Eye, Map, FileText} from "lucide-react"

// Define the Application interface
interface Application {
    id: number
    fullName: string
    status: "pending" | "approved" | "rejected"
    date: string
}

// Mock data
const MOCK_APPLICATIONS: Application[] = [
    {id: 1, fullName: "Иван Иванов", status: "pending", date: "2024-03-10"},
    {id: 2, fullName: "Петр Петров", status: "approved", date: "2024-03-08"},
    {id: 3, fullName: "Анна Сидорова", status: "rejected", date: "2024-03-05"},
    {id: 4, fullName: "Мария Кузнецова", status: "pending", date: "2024-03-12"},
    {id: 5, fullName: "Алексей Смирнов", status: "approved", date: "2024-03-01"},
    {id: 6, fullName: "Ольга Новикова", status: "pending", date: "2024-03-15"},
    {id: 7, fullName: "Дмитрий Козлов", status: "rejected", date: "2024-03-07"},
    {id: 8, fullName: "Елена Морозова", status: "pending", date: "2024-03-09"},
    {id: 9, fullName: "Сергей Волков", status: "approved", date: "2024-03-11"},
    {id: 10, fullName: "Наталья Лебедева", status: "rejected", date: "2024-03-04"},
    {id: 11, fullName: "Андрей Соколов", status: "pending", date: "2024-03-14"},
    {id: 12, fullName: "Татьяна Павлова", status: "approved", date: "2024-03-02"},
]

const ITEMS_PER_PAGE = 5

export default function ApplicationList() {
    const [currentPage, setCurrentPage] = useState(1)
    const [statusFilter, setStatusFilter] = useState<"all" | "pending" | "approved" | "rejected">("all")
    const [searchTerm, setSearchTerm] = useState("")

    // Filter applications by status and search term
    const filteredApplications = MOCK_APPLICATIONS.filter((app) => {
        const matchesStatus = statusFilter === "all" || app.status === statusFilter
        const matchesSearch = app.fullName.toLowerCase().includes(searchTerm.toLowerCase())
        return matchesStatus && matchesSearch
    })

    // Calculate pagination
    const totalPages = Math.ceil(filteredApplications.length / ITEMS_PER_PAGE)
    const startIndex = (currentPage - 1) * ITEMS_PER_PAGE
    const paginatedApplications = filteredApplications.slice(startIndex, startIndex + ITEMS_PER_PAGE)

    // Status badge color mapping
    const statusColors: Record<Application["status"], string> = {
        pending: "bg-yellow-100 text-yellow-800",
        approved: "bg-green-100 text-green-800",
        rejected: "bg-red-100 text-red-800",
    }

    // Status text mapping
    const statusText: Record<Application["status"], string> = {
        pending: "Ожидает",
        approved: "Подтверждено",
        rejected: "Отклонено",
    }

    return (
        <div className="min-h-screen bg-gray-50">
            {/* Минималистичная навигация/хедер */}
            <header className="bg-white shadow-sm border-b border-gray-200">
                <div className="container mx-auto px-4 py-4 flex items-center justify-between">
                    <div className="text-lg font-semibold text-gray-800">Azv Motors</div>
                    <nav className="flex items-center space-x-6">
                        <Link href="/admin"
                              className="flex items-center gap-2 text-gray-600 hover:text-blue-600 transition-colors">
                            <Map className="h-4 w-4"/>
                            <span>Карта</span>
                        </Link>
                        <Link href="/admin/applications" className="flex items-center gap-2 text-blue-600 font-medium">
                            <FileText className="h-4 w-4"/>
                            <span>Пользователи</span>
                        </Link>
                        <Link href="/admin/cars" className="flex items-center gap-2 text-blue-600 font-medium">
                            <FileText className="h-4 w-4"/>
                            <span>Машины</span>
                        </Link>
                    </nav>
                </div>
            </header>

            <div className="container mx-auto px-4 py-8 max-w-6xl">
                <h1 className="text-2xl font-bold mb-6">Список пользователей</h1>

                {/* Filters and search */}
                <div className="flex flex-col md:flex-row gap-4 mb-6">
                    <div className="relative flex-1">
                        <input
                            type="text"
                            placeholder="Поиск по ФИО"
                            className="w-full pl-10 pr-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                        />
                        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 h-5 w-5"/>
                    </div>

                    <div className="flex items-center gap-2">
                        <SortAsc className="h-5 w-5 text-gray-500"/>
                        <select
                            className="border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                            value={statusFilter}
                            onChange={(e) => setStatusFilter(e.target.value as "all" | "pending" | "approved" | "rejected")}
                        >
                            <option value="all">Все статусы</option>
                            <option value="pending">Ожидает</option>
                            <option value="approved">Подтверждено</option>
                            <option value="rejected">Отклонено</option>
                        </select>
                    </div>
                </div>

                {/* Applications list */}
                <div className="bg-white rounded-lg shadow overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                            <tr>
                                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ФИО</th>
                                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Статус
                                </th>
                                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Дата подачи
                                </th>
                                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Действия
                                </th>
                            </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                            {paginatedApplications.length > 0 ? (
                                paginatedApplications.map((application) => (
                                    <tr key={application.id} className="hover:bg-gray-50">
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <div
                                                className="text-sm font-medium text-gray-900">{application.fullName}</div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                          <span
                                              className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${statusColors[application.status]}`}
                                          >
                                            {statusText[application.status]}
                                          </span>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <div className="text-sm text-gray-500">
                                                {new Date(application.date).toLocaleDateString("ru-RU")}
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                                            <Link
                                                href={`/admin/applications/${application.id}`}
                                                className="text-blue-600 hover:text-blue-900 inline-flex items-center gap-1"
                                            >
                                                <Eye className="h-4 w-4"/>
                                                <span className="hidden sm:inline">Просмотр</span>
                                            </Link>
                                        </td>
                                    </tr>
                                ))
                            ) : (
                                <tr>
                                    <td colSpan={4} className="px-6 py-4 text-center text-sm text-gray-500">
                                        Пользователи не найдены
                                    </td>
                                </tr>
                            )}
                            </tbody>
                        </table>
                    </div>

                    {/* Pagination */}
                    {totalPages > 1 && (
                        <div className="px-4 py-3 flex items-center justify-between border-t border-gray-200 sm:px-6">
                            <div className="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
                                <div>
                                    <p className="text-sm text-gray-700">
                                        Показано <span className="font-medium">{startIndex + 1}</span> -{" "}
                                        <span className="font-medium">
                        {Math.min(startIndex + ITEMS_PER_PAGE, filteredApplications.length)}
                      </span>{" "}
                                        из <span className="font-medium">{filteredApplications.length}</span> заявок
                                    </p>
                                </div>
                                <div>
                                    <nav className="relative z-0 inline-flex rounded-md shadow-sm -space-x-px"
                                         aria-label="Pagination">
                                        <button
                                            onClick={() => setCurrentPage((prev) => Math.max(prev - 1, 1))}
                                            disabled={currentPage === 1}
                                            className={`relative inline-flex items-center px-2 py-2 rounded-l-md border border-gray-300 bg-white text-sm font-medium ${
                                                currentPage === 1 ? "text-gray-300" : "text-gray-500 hover:bg-gray-50"
                                            }`}
                                        >
                                            <span className="sr-only">Предыдущая</span>
                                            <ChevronLeft className="h-5 w-5"/>
                                        </button>

                                        {Array.from({length: totalPages}).map((_, index) => (
                                            <button
                                                key={index}
                                                onClick={() => setCurrentPage(index + 1)}
                                                className={`relative inline-flex items-center px-4 py-2 border text-sm font-medium ${
                                                    currentPage === index + 1
                                                        ? "z-10 bg-blue-50 border-blue-500 text-blue-600"
                                                        : "bg-white border-gray-300 text-gray-500 hover:bg-gray-50"
                                                }`}
                                            >
                                                {index + 1}
                                            </button>
                                        ))}

                                        <button
                                            onClick={() => setCurrentPage((prev) => Math.min(prev + 1, totalPages))}
                                            disabled={currentPage === totalPages}
                                            className={`relative inline-flex items-center px-2 py-2 rounded-r-md border border-gray-300 bg-white text-sm font-medium ${
                                                currentPage === totalPages ? "text-gray-300" : "text-gray-500 hover:bg-gray-50"
                                            }`}
                                        >
                                            <span className="sr-only">Следующая</span>
                                            <ChevronRight className="h-5 w-5"/>
                                        </button>
                                    </nav>
                                </div>
                            </div>

                            {/* Mobile pagination */}
                            <div className="flex items-center justify-between w-full sm:hidden">
                                <button
                                    onClick={() => setCurrentPage((prev) => Math.max(prev - 1, 1))}
                                    disabled={currentPage === 1}
                                    className={`relative inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md ${
                                        currentPage === 1 ? "text-gray-300 bg-gray-100" : "text-gray-700 bg-white hover:bg-gray-50"
                                    }`}
                                >
                                    Назад
                                </button>
                                <div className="text-sm text-gray-700">
                                    <span>{currentPage}</span> из <span>{totalPages}</span>
                                </div>
                                <button
                                    onClick={() => setCurrentPage((prev) => Math.min(prev + 1, totalPages))}
                                    disabled={currentPage === totalPages}
                                    className={`relative inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md ${
                                        currentPage === totalPages ? "text-gray-300 bg-gray-100" : "text-gray-700 bg-white hover:bg-gray-50"
                                    }`}
                                >
                                    Вперед
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}