import pandas as pd
import pytest

from src.scopes import add_scopes, geographic_mask, validate_scopes


def test_multiple_states_match_pairs_without_cross_product():
    scopes = validate_scopes([{"uf": "MG", "municipio_code": "4553"},
                              {"uf": "ES", "municipio_code": "5705"}])
    frame = pd.DataFrame({"uf": ["MG", "ES", "MG", "ES"],
                          "municipio": ["4553", "5705", "5705", "4553"]})
    assert geographic_mask(frame, scopes).tolist() == [True, True, False, False]


def test_adding_cities_preserves_existing_scope_and_rejects_ibge_codes():
    scopes = [{"uf": "MG", "municipio_code": "4553", "nome": "Governador Valadares"}]
    added = add_scopes(scopes, "es", "5705, 5621")
    assert len(added) == 3
    assert added[0] == scopes[0]
    assert len(add_scopes(added, "ES", "5705")) == 3
    with pytest.raises(ValueError, match="IBGE"):
        add_scopes(scopes, "MG", "3127701")
    with pytest.raises(ValueError):
        add_scopes(scopes, "ES", "")
