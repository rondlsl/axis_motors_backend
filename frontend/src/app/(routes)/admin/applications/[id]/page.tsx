"use client"

import {useState, useEffect} from "react"
import {useRouter} from "next/navigation"
import Image from "next/image"
import Link from "next/link"
import {ChevronLeft, X} from "lucide-react"

// First, add proper TypeScript interfaces at the top of the file
interface Application {
    id: number
    fullName: string
    phoneNumber: string
    status: "pending" | "approved" | "rejected"
    date: string
    idCardFront: string
    idCardBack: string
    driverLicense: string
    selfieWithLicense: string
}

// Update the getMockApplication function to use the interface
const getMockApplication = (id: number): Application => ({
    id,
    fullName: "Иван Иванов",
    phoneNumber: "+7 (999) 123-45-67",
    status: "pending",
    date: "2024-03-10",
    idCardFront: "/placeholder.svg?height=300&width=500",
    idCardBack: "/placeholder.svg?height=300&width=500",
    driverLicense: "/placeholder.svg?height=300&width=500",
    selfieWithLicense: "/placeholder.svg?height=300&width=500",
})

export default function ApplicationDetail({params}: { params: { id: string } }) {
    const router = useRouter()
    const id = Number.parseInt(params.id)

    const [application, setApplication] = useState<Application | null>(null)
    const [documentName, setDocumentName] = useState("")
    const [showRejectModal, setShowRejectModal] = useState(false)
    const [rejectReason, setRejectReason] = useState("")
    const [showToast, setShowToast] = useState(false)
    const [toastMessage, setToastMessage] = useState("")
    const [toastType, setToastType] = useState<"success" | "error">("success")

    useEffect(() => {
        // In a real app, fetch the application data from an API
        setApplication(getMockApplication(id))
    }, [id])

    if (!application) {
        return (
            <div className="flex justify-center items-center h-screen">
                <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
            </div>
        )
    }

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

    const handleApprove = () => {
        if (!documentName.trim()) {
            setToastMessage("Пожалуйста, введите ФИО на документах")
            setToastType("error")
            setShowToast(true)
            return
        }

        // Update application status
        setApplication({
            ...application,
            status: "approved",
        })

        // Show success toast
        setToastMessage("Заявка успешно подтверждена")
        setToastType("success")
        setShowToast(true)
    }

    const handleReject = () => {
        if (!rejectReason.trim()) {
            return
        }

        // Update application status
        setApplication({
            ...application,
            status: "rejected",
        })

        // Close modal and show toast
        setShowRejectModal(false)
        setToastMessage("Заявка отклонена")
        setToastType("error")
        setShowToast(true)
    }

    return (
        <div className="container mx-auto px-4 py-8 max-w-4xl">
            {/* Back button */}
            <Link href="/admin/applications" className="inline-flex items-center text-blue-600 hover:text-blue-800 mb-6">
                <ChevronLeft className="h-5 w-5"/>
                <span>Назад к списку</span>
            </Link>

            <div className="bg-white rounded-lg shadow-lg overflow-hidden">
                {/* Header */}
                <div className="bg-gray-50 px-6 py-4 border-b">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                        <h1 className="text-xl font-bold text-gray-900">Заявка №{application.id}</h1>
                        <span
                            className={`px-3 py-1 inline-flex text-sm leading-5 font-semibold rounded-full ${statusColors[application.status]}`}
                        >
              {statusText[application.status]}
            </span>
                    </div>
                </div>

                {/* Content */}
                <div className="p-6">
                    {/* Personal information */}
                    <div className="mb-8">
                        <h2 className="text-lg font-semibold mb-4">Личная информация</h2>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <p className="text-sm text-gray-500">ФИО</p>
                                <p className="font-medium">{application.fullName}</p>
                            </div>
                            <div>
                                <p className="text-sm text-gray-500">Номер телефона</p>
                                <p className="font-medium">{application.phoneNumber}</p>
                            </div>
                            <div>
                                <p className="text-sm text-gray-500">Дата подачи</p>
                                <p className="font-medium">{new Date(application.date).toLocaleDateString("ru-RU")}</p>
                            </div>
                        </div>
                    </div>

                    {/* Documents */}
                    <div className="mb-8">
                        <h2 className="text-lg font-semibold mb-4">Документы</h2>

                        <div className="mb-6">
                            <h3 className="text-md font-medium mb-2">Удостоверение личности</h3>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <div className="border rounded-lg overflow-hidden">
                                    <div className="aspect-[3/2] relative">
                                        <Image
                                            src={application.idCardFront || "/placeholder.svg"}
                                            alt="Удостоверение личности (лицевая сторона)"
                                            fill
                                            className="object-cover"
                                        />
                                    </div>
                                    <div className="p-2 text-sm text-center text-gray-500">Лицевая сторона</div>
                                </div>
                                <div className="border rounded-lg overflow-hidden">
                                    <div className="aspect-[3/2] relative">
                                        <Image
                                            src={application.idCardBack || "/placeholder.svg"}
                                            alt="Удостоверение личности (обратная сторона)"
                                            fill
                                            className="object-cover"
                                        />
                                    </div>
                                    <div className="p-2 text-sm text-center text-gray-500">Обратная сторона</div>
                                </div>
                            </div>
                        </div>

                        <div className="mb-6">
                            <h3 className="text-md font-medium mb-2">Водительское удостоверение</h3>
                            <div className="max-w-sm mx-auto sm:mx-0">
                                <div className="border rounded-lg overflow-hidden">
                                    <div className="aspect-[3/2] relative">
                                        <Image
                                            src={application.driverLicense || "/placeholder.svg"}
                                            alt="Водительское удостоверение"
                                            fill
                                            className="object-cover"
                                        />
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div>
                            <h3 className="text-md font-medium mb-2">Селфи с водительским удостоверением</h3>
                            <div className="max-w-sm mx-auto sm:mx-0">
                                <div className="border rounded-lg overflow-hidden">
                                    <div className="aspect-[3/2] relative">
                                        <Image
                                            src={application.selfieWithLicense || "/placeholder.svg"}
                                            alt="Селфи с водительским удостоверением"
                                            fill
                                            className="object-cover"
                                        />
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Verification form */}
                    {application.status === "pending" && (
                        <div className="border-t pt-6">
                            <h2 className="text-lg font-semibold mb-4">Верификация</h2>

                            <div className="mb-6">
                                <label htmlFor="documentName" className="block text-sm font-medium text-gray-700 mb-1">
                                    ФИО на документах
                                </label>
                                <input
                                    type="text"
                                    id="documentName"
                                    className="w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                                    placeholder="Введите ФИО как указано в документах"
                                    value={documentName}
                                    onChange={(e) => setDocumentName(e.target.value)}
                                />
                            </div>

                            <div className="flex flex-col sm:flex-row gap-4">
                                <button
                                    onClick={handleApprove}
                                    className="px-6 py-2 bg-green-600 text-white font-medium rounded-lg hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
                                >
                                    Подтвердить
                                </button>
                                <button
                                    onClick={() => setShowRejectModal(true)}
                                    className="px-6 py-2 bg-red-600 text-white font-medium rounded-lg hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
                                >
                                    Отклонить
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Rejection Modal */}
            {showRejectModal && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
                    <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
                        <div className="flex justify-between items-center p-6 border-b">
                            <h3 className="text-lg font-semibold">Отклонение заявки</h3>
                            <button onClick={() => setShowRejectModal(false)}
                                    className="text-gray-400 hover:text-gray-500">
                                <X className="h-5 w-5"/>
                            </button>
                        </div>
                        <div className="p-6">
                            <label htmlFor="rejectReason" className="block text-sm font-medium text-gray-700 mb-2">
                                Причина отклонения
                            </label>
                            <textarea
                                id="rejectReason"
                                rows={4}
                                className="w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                                placeholder="Укажите причину отклонения заявки"
                                value={rejectReason}
                                onChange={(e) => setRejectReason(e.target.value)}
                            ></textarea>
                        </div>
                        <div className="px-6 py-4 bg-gray-50 flex justify-end gap-4 rounded-b-lg">
                            <button
                                onClick={() => setShowRejectModal(false)}
                                className="px-4 py-2 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50"
                            >
                                Отмена
                            </button>
                            <button
                                onClick={handleReject}
                                className="px-4 py-2 bg-red-600 text-white font-medium rounded-lg hover:bg-red-700 disabled:bg-red-300"
                                disabled={!rejectReason.trim()}
                            >
                                Отклонить
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Toast Notification */}
            {showToast && (
                <div
                    className={`fixed bottom-4 right-4 px-6 py-3 rounded-lg shadow-lg flex items-center gap-3 z-50 ${
                        toastType === "success" ? "bg-green-500 text-white" : "bg-red-500 text-white"
                    }`}
                >
                    <span>{toastMessage}</span>
                    <button onClick={() => setShowToast(false)} className="text-white hover:text-gray-100">
                        <X className="h-4 w-4"/>
                    </button>
                </div>
            )}
        </div>
    )
}