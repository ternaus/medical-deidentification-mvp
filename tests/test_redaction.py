from medical_deid.redaction import EntityMatch, RedactionError, apply_replacements


def test_replacements_are_exact_typed_and_stable() -> None:
    text = "Пациент: ИВАНОВ ИВАН ИВАНОВИЧ. Телефон: +7 999 123-45-67."

    redacted, changes = apply_replacements(
        text,
        [
            EntityMatch(text="ИВАНОВ ИВАН ИВАНОВИЧ", kind="patient_name"),
            EntityMatch(text="+7 999 123-45-67", kind="phone"),
        ],
    )

    assert redacted == "Пациент: [ПАЦИЕНТ_1]. Телефон: [ТЕЛЕФОН_1]."
    assert [change.replacement for change in changes] == ["[ПАЦИЕНТ_1]", "[ТЕЛЕФОН_1]"]


def test_replacement_rejects_an_llm_span_that_is_not_in_ocr_text() -> None:
    try:
        apply_replacements("Врач: Петрова Ольга", [EntityMatch(text="Петров", kind="patient_name")])
    except RedactionError as error:
        assert "exact OCR text" in str(error)
    else:
        raise AssertionError("An unverified span must fail closed.")


def test_replacement_accepts_a_name_joined_to_a_date_by_ocr() -> None:
    redacted, _ = apply_replacements(
        "ИВАНОВ ИВАН01.01.1980",
        [EntityMatch(text="ИВАНОВ ИВАН", kind="patient_name")],
    )

    assert redacted == "[ПАЦИЕНТ_1]01.01.1980"


def test_replacement_rejects_overlapping_spans() -> None:
    try:
        apply_replacements(
            "Пациент Иванов Иван",
            [
                EntityMatch(text="Иванов Иван", kind="patient_name"),
                EntityMatch(text="Иван", kind="patient_name"),
            ],
        )
    except RedactionError as error:
        assert "overlapping" in str(error)
    else:
        raise AssertionError("Overlapping spans must fail closed.")
