from datetime import date, datetime, timezone
from urllib.parse import parse_qs

import pytest

from src.demo import demo_data
from src.prospecting import (DEFAULT_TEMPLATE, EXCLUSIONS, SAO_PAULO, contact_link,
                             exclusion_reasons, filter_data, greeting,
                             prepare_data, render_message)


@pytest.mark.parametrize("hour,expected", [(0, "Boa noite"), (5, "Boa noite"), (6, "Bom dia"),
                                         (11, "Bom dia"), (12, "Boa tarde"), (15, "Boa tarde"),
                                         (17, "Boa tarde"), (18, "Boa noite"), (23, "Boa noite")])
def test_greeting_uses_brasilia_time(hour, expected):
    assert greeting(datetime(2026, 10, 6, hour, tzinfo=SAO_PAULO)) == expected
    assert greeting(datetime(2026, 10, 6, 18, tzinfo=timezone.utc)) == "Boa tarde"


@pytest.mark.parametrize("principal,secondary,nature,expected", [
    ("8511200", "", "2062", "educacao"),
    ("4712100", "8512100,8599604", "2062", "educacao"),
    ("9491000", "", "", "religiao"),
    ("4712100", "", "3220", "religiao"),
    ("9492800", "", "", "politica"),
    ("4712100", "", "3263", "politica"),
    ("8411600", "", "", "governo"),
    ("8610101", "", "1031", "governo"),
    ("4712100", "", "2011", "governo"),
    ("4712100", "", "2038", "governo"),
])
def test_exclusions_use_main_secondary_and_legal_nature(principal, secondary, nature, expected):
    assert expected in exclusion_reasons({"cnae_fiscal_principal": principal,
                                          "cnae_fiscal_secundaria": secondary,
                                          "natureza_juridica": nature})


def test_filters_combine_neighborhood_porte_and_exclusions():
    df = demo_data(date(2026, 10, 6))
    df.loc[0, "bairro"] = "  Ilha  dos Araújos "
    df.loc[2, "bairro"] = "ILHA DOS ARAUJOS"
    df.loc[2, "cnae_fiscal_secundaria"] = "8511200"
    df = prepare_data(df)
    df["idade_anos"], df["attempt_count"] = 2, 0
    result = filter_data(df, neighborhoods=["ilha dos araújos"], portes=["01"])
    assert result.cnpj.tolist() == ["DEMO-000000001"]
    assert len(filter_data(df, neighborhoods=["ILHA DOS ARAUJOS"], exclusions=[])) == 3
    assert filter_data(df, portes=[]).empty
    df.loc[0, "attempt_count"] = 1
    assert len(filter_data(df, contact_status="Já tentado")) == 1
    assert exclusion_reasons({"cnae_fiscal_principal": "4712100", "natureza_juridica": "2062"}) == []


def test_link_preserves_template_and_does_not_freeze_auto_greeting():
    row = {"cnpj": "11111111000111", "primeiro_nome": "Maria"}
    template = DEFAULT_TEMPLATE + " Oferta 20%20 + café."
    query = parse_qs(contact_link(row, "5533999999999", template, "Daniel", attempt_id="test")[1:])
    assert "salutation" not in query
    assert query["template"] == [template]
    assert query["attempt"] == ["test"]
    message = render_message(template, "Maria", "Daniel", "Boa tarde")
    assert message.startswith("Boa tarde! Tudo bem?")
    assert message.endswith("20%20 + café.")
    assert "a pessoa responsável" in render_message(DEFAULT_TEMPLATE, "", "Daniel")
    with pytest.raises(ValueError):
        render_message("Olá {nome.__class__}", "Maria", "Daniel")
