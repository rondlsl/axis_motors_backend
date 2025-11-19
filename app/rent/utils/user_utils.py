from sqlalchemy.orm import Session
from typing import List
from app.models.user_model import User, UserRole
from app.models.guarantor_model import Guarantor


def get_user_available_auto_classes(user: User, db: Session) -> List[str]:
    """
    Получить доступные классы автомобилей для пользователя.
    
    Если у пользователя есть auto_class, возвращает их.
    Если пользователь REJECTFIRST и у него есть активный гарант, 
    возвращает классы гаранта.
    Иначе возвращает пустой список.
    """
    if user.auto_class and len(user.auto_class) > 0:
        return user.auto_class
    
    if user.role == UserRole.REJECTFIRST:
        active_guarantor = db.query(Guarantor).join(User, Guarantor.guarantor_id == User.id).filter(
            Guarantor.client_id == user.id,
            Guarantor.is_active == True
        ).first()
        
        if active_guarantor and active_guarantor.guarantor_user.auto_class:
            return active_guarantor.guarantor_user.auto_class
    
    return []

