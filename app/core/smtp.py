"""
Отправка email через SMTP с перебором серверов/портов и аккаунтов при ошибке.
Жёсткий лимит 10 секунд на всю операцию — чтобы бекенд не зависал.
"""
import smtplib
import time
import socket
import urllib.request
from email.message import EmailMessage
from typing import List, Tuple, Optional

from app.core.config import SMTP_HOST, SMTP_PORT, SMTP_ACCOUNTS, SMTP_FROM
from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Максимум 10 секунд на всю отправку
SMTP_TOTAL_TIMEOUT = 10

# Fallback: несколько серверов/портов
SMTP_SERVERS = [
    ("smtp.gmail.com", 587),           # основной TLS
    ("smtp.gmail.com", 465),           # SSL
    ("smtp.gmail.com", 25),            # резервный порт
    ("smtp-relay.gmail.com", 587),     # альтернативный сервер
]

def _test_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """Быстрая проверка доступности порта."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False

def _get_smtp_servers() -> List[Tuple[str, int]]:
    """Список (host, port) для перебора: сначала из env, затем fallback."""
    servers = []
    
    # Основной из конфига
    if SMTP_HOST and SMTP_PORT:
        servers.append((SMTP_HOST, SMTP_PORT))
    
    # Добавляем fallback, исключая дубликаты
    for host, port in SMTP_SERVERS:
        if (host, port) not in servers:
            servers.append((host, port))
    
    return servers


def network_diagnostics() -> bool:
    """Проверка DNS, порта 443 и доступа в интернет. Результаты пишутся в лог."""
    tests = []

    # 1. Проверка DNS
    try:
        ip = socket.gethostbyname("google.com")
        tests.append(f"✓ DNS работает: google.com -> {ip}")
    except Exception:
        tests.append("✗ DNS не работает")

    # 2. Проверка порта 443 (HTTPS)
    try:
        sock = socket.create_connection(("google.com", 443), timeout=5)
        sock.close()
        tests.append("✓ Порт 443 (HTTPS) доступен")
    except Exception:
        tests.append("✗ Порт 443 заблокирован")

    # 3. Проверка доступа к интернету
    try:
        urllib.request.urlopen("https://google.com", timeout=5)
        tests.append("✓ Интернет доступен")
    except Exception:
        tests.append("✗ Нет доступа к интернету")

    for test in tests:
        logger.info("Диагностика сети: %s", test)

    return all("✓" in test for test in tests)


def send_email_with_fallback(
    msg: EmailMessage, 
    to_address: str | List[str], 
    from_override: Optional[str] = None
) -> bool:
    """
    Отправить письмо. Перебирает серверы (host, port) и аккаунты.
    Общее время всех попыток не превышает SMTP_TOTAL_TIMEOUT секунд.
    
    :param msg: готовое сообщение (Subject, From, To уже заданы у msg)
    :param to_address: email получателя или список адресов
    :param from_override: если задан, используется как From
    :return: True если отправка прошла, иначе False
    """
    try:
        if not SMTP_ACCOUNTS:
            logger.warning("SMTP not configured: no SMTP accounts")
            return False

        servers = _get_smtp_servers()
        if not servers:
            logger.warning("SMTP not configured: no servers")
            return False

        if not network_diagnostics():
            logger.error("SMTP: Сеть полностью недоступна!")
            return False

        to_list = [to_address] if isinstance(to_address, str) else list(to_address)
        to_display = to_list[0] if len(to_list) == 1 else ",".join(to_list[:3])
        
        logger.info("SMTP: отправка email на to=%s (макс %ss)", to_display, SMTP_TOTAL_TIMEOUT)

        deadline = time.monotonic() + SMTP_TOTAL_TIMEOUT
        last_error = None
        network_errors = 0
        auth_errors = 0
        relay_errors = 0  # 550 Mail relay denied и т.п.
        
        # Быстрая проверка: есть ли вообще сетевой доступ
        if deadline - time.monotonic() > 1:
            test_host, test_port = servers[0]
            if not _test_port(test_host, test_port, timeout=1):
                logger.warning("SMTP: базовый тест сети не пройден (%s:%s)", test_host, test_port)
                # Не прерываем, пробуем остальные серверы

        for host, port in servers:
            if time.monotonic() >= deadline:
                logger.warning("SMTP: превышен общий таймаут %ss, прерываем", SMTP_TOTAL_TIMEOUT)
                break
            
            # Быстрая проверка порта перед попыткой отправки
            time_left = deadline - time.monotonic()
            if time_left > 0.5:  # Если осталось время
                if not _test_port(host, port, timeout=min(1.0, time_left)):
                    logger.debug("SMTP: порт %s:%s недоступен, пропускаем", host, port)
                    continue
            
            for smtp_user, smtp_pass in SMTP_ACCOUNTS:
                if time.monotonic() >= deadline:
                    break
                
                from_addr = from_override or SMTP_FROM or smtp_user
                
                try:
                    # Устанавливаем заголовки
                    msg["From"] = from_addr
                    if msg.get("To") is None and len(to_list) == 1:
                        msg["To"] = to_list[0]
                    
                    # Определяем таймаут для этой попытки
                    attempt_timeout = max(1, min(3, int(deadline - time.monotonic())))
                    
                    if port == 465:  # SSL
                        # SMTP_SSL может игнорировать timeout в конструкторе
                        server = smtplib.SMTP_SSL(host, port, timeout=attempt_timeout)
                        try:
                            server.login(smtp_user, smtp_pass)
                            server.sendmail(from_addr, to_list, msg.as_string())
                            logger.info("SMTP: email отправлен на to=%s через %s@%s:%s", 
                                       to_display, smtp_user, host, port)
                            return True
                        finally:
                            try:
                                server.quit()
                            except Exception:
                                pass
                    else:  # TLS или plain
                        server = smtplib.SMTP(host, port, timeout=attempt_timeout)
                        try:
                            server.starttls()
                            server.login(smtp_user, smtp_pass)
                            server.sendmail(from_addr, to_list, msg.as_string())
                            logger.info("SMTP: email отправлен на to=%s через %s@%s:%s", 
                                       to_display, smtp_user, host, port)
                            return True
                        finally:
                            try:
                                server.quit()
                            except Exception:
                                pass
                            
                except smtplib.SMTPAuthenticationError as e:
                    auth_errors += 1
                    last_error = e
                    logger.warning("SMTP auth failed %s@%s:%s (to=%s): %s",
                                  smtp_user, host, port, to_display, e)
                except smtplib.SMTPException as e:
                    relay_errors += 1
                    last_error = e
                    err_str = str(e).lower()
                    if "relay denied" in err_str or "5.7.0" in str(e):
                        logger.warning("SMTP relay denied %s@%s:%s (to=%s): зарегистрируйте IP сервера в Google Workspace → SMTP Relay Settings. %s",
                                      smtp_user, host, port, to_display, e)
                    else:
                        logger.warning("SMTP response error %s@%s:%s (to=%s): %s",
                                      smtp_user, host, port, to_display, e)
                except (socket.error, ConnectionError, TimeoutError) as e:
                    network_errors += 1
                    last_error = e
                    logger.warning("SMTP network error %s@%s:%s (to=%s): %s",
                                  smtp_user, host, port, to_display, e)
                except Exception as e:
                    last_error = e
                    logger.warning("SMTP failed %s@%s:%s (to=%s): %s",
                                  smtp_user, host, port, to_display, e)

        # Анализ причины ошибки
        if last_error:
            err_str = str(last_error).lower()
            if "relay denied" in err_str or "5.7.0" in str(last_error):
                error_msg = (
                    "Gmail SMTP Relay: зарегистрируйте IP сервера в Google Workspace "
                    "(Admin → Apps → Google Workspace → Gmail → Routing → SMTP relay). "
                    "См. https://support.google.com/a/answer/6140680"
                )
            elif network_errors > 0 and auth_errors == 0 and relay_errors == 0:
                error_msg = "Сетевая ошибка: возможно, нет доступа к интернету или порты 587/465 заблокированы"
            elif auth_errors > 0:
                error_msg = "Ошибки аутентификации: проверьте учетные данные SMTP"
            else:
                error_msg = "Все попытки отправки не удались"

            logger.error("SMTP: %s; network_errors=%d, auth_errors=%d, relay_errors=%d, last error (to=%s): %s",
                        error_msg, network_errors, auth_errors, relay_errors, to_display, last_error)
        
        return False
        
    except Exception as e:
        try:
            to_fallback = to_address if isinstance(to_address, str) else (list(to_address)[0] if to_address else "?")
        except Exception:
            to_fallback = "?"
        logger.error("SMTP: неожиданная ошибка (to=%s): %s", to_fallback, e, exc_info=True)
        return False
