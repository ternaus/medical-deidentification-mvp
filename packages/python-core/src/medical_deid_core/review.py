from __future__ import annotations

from datetime import UTC, datetime


def create_review_session(session_id: str) -> dict[str, object]:
    return {
        "id": session_id,
        "status": "completed",
        "sourceLabel": "synthetic-review.pdf",
        "sourceText": (
            "Пациент: Иван Петров\n"
            "Дата рождения: 14.03.1984\n"
            "Дата визита: 02.09.2026\n"
            "Телефон: +7 900 123-45-67\n"
            "Результат: контрольный осмотр без особенностей."
        ),
        "resultText": (
            "Пациент: [ИМЯ УДАЛЕНО]\n"
            "Дата рождения: [ДАТА УДАЛЕНА]\n"
            "Дата визита: 02.09.2026\n"
            "Телефон: [ТЕЛЕФОН УДАЛЁН]\n"
            "Результат: контрольный осмотр без особенностей."
        ),
        "changes": [
            {
                "kind": "identifier",
                "source": "Иван Петров",
                "replacement": "[ИМЯ УДАЛЕНО]",
                "reason": "person_name",
            },
            {
                "kind": "identifier",
                "source": "14.03.1984",
                "replacement": "[ДАТА УДАЛЕНА]",
                "reason": "date_of_birth",
            },
            {
                "kind": "identifier",
                "source": "+7 900 123-45-67",
                "replacement": "[ТЕЛЕФОН УДАЛЁН]",
                "reason": "phone_number",
            },
        ],
        "warnings": [
            "Интерфейсный fixture: исходный документ не покидает приложение.",
            "Результат не предназначен для клинического или production-использования.",
        ],
        "createdAt": datetime.now(UTC).isoformat(),
    }
