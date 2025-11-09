from fastapi import HTTPException


class InsufficientBalanceException(HTTPException):
    def __init__(self, required_amount: int):
        formatted_amount = f"{required_amount:,}".replace(",", " ")
        super().__init__(
            status_code=402,
            detail=(
                f"Для аренды автомобиля на вашем балансе должна быть минимальная сумма {formatted_amount} ₸.\n\n"
                f"Оплата поездки списывается по фактическому использованию автомобиля, оставшиеся средства останутся на вашем балансе."
            )
        )
