"""Exemplos sintéticos para visualizar a interface antes da primeira carga."""
from datetime import date

import pandas as pd


def demo_data(today: date) -> pd.DataFrame:
    rows = []
    examples = [
        ("Loja Exemplo", "CENTRO", 3, "Maria", False),
        ("Oficina Exemplo", "ILHA DOS ARAÚJOS", 2, "João", False),
        ("Mercado Exemplo", "CENTRO", 1, "Ana", False),
        ("Contabilidade Exemplo", "CENTRO", 5, "Pedro", True),
    ]
    for i, (name, bairro, years, contact, accounting) in enumerate(examples, 1):
        rows.append({
            "cnpj": f"DEMO-{i:09d}", "razao_social": name,
            "nome_fantasia": name, "bairro": bairro,
            "data_abertura": pd.Timestamp(today) - pd.DateOffset(years=years),
            "cnae_fiscal_principal": "6920601" if accounting else "4712100",
            "cnae_principal_descricao": "Contabilidade" if accounting else "Comércio (exemplo)",
            "primeiro_nome": contact, "nomes_socios": f"{contact} Exemplo",
            "origem_nome_contato": "demonstração fictícia",
            "whatsapp_1": "5500000000000", "whatsapp_2": "",
            "celular_1_provavel": True, "celular_2_provavel": False,
            "tem_telefone": True, "is_contabilidade": accounting,
        })
    return pd.DataFrame(rows)
