from src.utils import cnpj_full, first_name, has_any_cnae, phone_br


def test_cnpj_full():
    assert cnpj_full("12345678", "1", "90") == "12345678000190"


def test_first_name():
    assert first_name("MARIA DA SILVA") == "Maria"
    assert first_name("123 EMPRESA") == ""


def test_accounting_cnae():
    excluded = {"6920601", "6920602"}
    assert has_any_cnae("6920601", "", excluded)
    assert has_any_cnae("4711302", "6920602,7020400", excluded)
    assert not has_any_cnae("4711302", "7020400", excluded)


def test_phone_br():
    assert phone_br("33", "999991234") == "5533999991234"
    assert phone_br("33", "33331234") == "553333331234"


def test_age_changes_on_exact_calendar_anniversary():
    from datetime import date
    from src.utils import age_years
    assert age_years(date(2025, 10, 6), date(2026, 10, 5)) < 1
    assert age_years(date(2025, 10, 6), date(2026, 10, 6)) == 1
    assert age_years(date(2024, 2, 29), date(2025, 2, 28)) == 1
