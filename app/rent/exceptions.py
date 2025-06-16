from fastapi import HTTPException


class InsufficientBalanceException(HTTPException):
    def __init__(self, required_amount: int):
        super().__init__(
            status_code=402,
            detail=(
                f"Пожалуйста, пополните счёт: для бронирования необходимо минимум {required_amount}₸."
            )
        )
