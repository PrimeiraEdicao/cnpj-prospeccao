"""Dados privados via Data API, sempre com o JWT do próprio usuário e RLS."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import requests

from .auth import AuthConfig, AuthSession
from .reviews import REVIEW_LABELS, import_cnpj


class StoreError(RuntimeError):
    pass


class SupabaseStore:
    def __init__(self, config: AuthConfig, session: AuthSession, transport=None):
        self.config, self.session = config, session
        self.transport = transport or requests.Session()
        self.user_id = session.identity.user_id

    def _request(self, method, resource, *, params=None, body=None, prefer=None):
        headers = {"apikey": self.config.publishable_key, "Authorization": f"Bearer {self.session.access_token}",
                   "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        try:
            result = self.transport.request(method, self.config.url + "/rest/v1/" + resource,
                                            headers=headers, params=params, json=body, timeout=(5, 20))
            if result.status_code in (401, 403):
                raise StoreError("Acesso negado ou sessão expirada. Entre novamente.")
            if not 200 <= result.status_code < 300:
                try:
                    message = result.json().get("message", "")
                except (ValueError, AttributeError):
                    message = ""
                if message == "data_update_in_progress":
                    raise StoreError("Já existe uma atualização em andamento.")
                if message == "data_update_daily_limit":
                    raise StoreError("O limite de três solicitações de carga por dia foi atingido.")
                raise StoreError("Não foi possível salvar ou consultar seus dados. Confira a configuração do banco e tente novamente.")
            return result.json() if result.content else None
        except (requests.RequestException, ValueError):
            raise StoreError("O banco não respondeu. Nenhuma confirmação de sucesso foi emitida.") from None

    def account(self):
        rows = self._request("GET", "app_accounts", params={"select": "user_id,email,role,status,access_until,created_at", "user_id": "eq." + self.user_id})
        if len(rows) != 1:
            raise StoreError("Sua conta ainda não foi provisionada. Contate o administrador.")
        return rows[0]

    def provision(self):
        self._request("POST", "rpc/app_provision_account", body={})
        return self.account()

    def require_active(self):
        account = self.account()
        until = account.get("access_until")
        expired = until and datetime.fromisoformat(until.replace("Z", "+00:00")) <= datetime.now(timezone.utc)
        if account["status"] != "active" or expired:
            raise StoreError("Seu acesso está pendente, bloqueado ou vencido. Solicite a liberação ao administrador.")
        return account

    def require_admin(self):
        account = self.require_active()
        if account["role"] != "admin":
            raise StoreError("Esta operação é exclusiva de administradores.")
        return account

    def get_reviews(self):
        # Paginação explícita: não perde revisões quando a conta ultrapassa o limite da API.
        rows, offset = [], 0
        while True:
            batch = self._request("GET", "app_reviews", params={"select": "cnpj,status,source,reviewed_at", "user_id": "eq." + self.user_id,
                                                                  "order": "cnpj", "limit": 500, "offset": offset})
            rows.extend(batch)
            if len(batch) < 500:
                return rows
            offset += 500

    def import_reviews(self, records):
        records = list(records)
        if not records or len(records) > 50000:
            raise ValueError("Importe de 1 a 50.000 empresas por vez.")
        cleaned = {}
        for row in records:
            number = import_cnpj(row.get("cnpj"))
            if number != row.get("cnpj") or row.get("status") not in REVIEW_LABELS:
                raise ValueError("A lista contém CNPJ ou motivo inválido.")
            cleaned.setdefault(number, {"cnpj": number, "status": row["status"], "source": str(row.get("source", ""))[:2000]})
        result = self._request("POST", "rpc/app_import_reviews", body={"p_records": list(cleaned.values())})
        return int(result["added"]), int(result["existing"])

    def confirm_contacts(self, cnpjs, visible):
        if not isinstance(cnpjs, list) or not 1 <= len(cnpjs) <= 100 or any(not isinstance(n, str) for n in cnpjs):
            raise ValueError("Selecione de 1 a 100 empresas da página atual.")
        allowed = set(visible.loc[~visible["reviewed"], "cnpj"].astype(str))
        if not set(cnpjs).issubset(allowed):
            raise ValueError("A seleção mudou ou inclui uma empresa revisada. Atualize a lista.")
        return self.import_reviews([{"cnpj": n, "status": "contatado", "source": "Confirmação manual no aplicativo"} for n in dict.fromkeys(cnpjs)])

    def get_states(self, cnpjs):
        # Compatibilidade com aberturas antigas; novas confirmações não inventam envios.
        wanted, rows, offset = set(cnpjs), [], 0
        while wanted:
            batch = self._request("GET", "app_contact_state", params={"select": "cnpj,attempt_count,first_attempt_at,last_attempt_at,last_phone,last_contact_name",
                                                                        "user_id": "eq." + self.user_id, "order": "cnpj", "limit": 500, "offset": offset})
            rows.extend(row for row in batch if row["cnpj"] in wanted)
            if len(batch) < 500:
                break
            offset += 500
        return rows

    def record_attempt(self, attempt_id, cnpj, phone, contact_name, message):
        if not isinstance(attempt_id, str) or not 1 <= len(attempt_id) <= 64:
            raise ValueError("Tentativa inválida.")
        return self._request("POST", "rpc/app_record_attempt", body={"p_attempt_id": attempt_id, "p_cnpj": cnpj,
                             "p_phone": phone, "p_contact_name": contact_name[:255], "p_message": message[:10000]})

    def preferences(self):
        rows = self._request("GET", "app_preferences", params={"select": "value", "user_id": "eq." + self.user_id})
        return rows[0]["value"] if rows else {}

    def save_preferences(self, values):
        allowed = {"template", "sender", "appearance"}
        if set(values) - allowed or len(json.dumps(values)) > 8000 or any(not isinstance(v, str) for v in values.values()):
            raise ValueError("Preferências inválidas.")
        self._request("POST", "app_preferences", params={"on_conflict": "user_id"},
                      body={"user_id": self.user_id, "value": values}, prefer="resolution=merge-duplicates,return=minimal")

    def list_accounts(self):
        self.require_admin()
        return self._request("GET", "app_accounts", params={"select": "user_id,email,role,status,access_until,created_at", "order": "created_at.desc", "limit": 200})

    def set_access(self, user_id, role, status, access_until):
        self.require_admin()
        target = str(UUID(user_id))
        if target == self.user_id or role not in {"user", "admin"} or status not in {"pending", "active", "blocked"}:
            raise ValueError("Selecione outra conta e permissões válidas.")
        self._request("POST", "rpc/app_admin_set_access", body={"p_user_id": target, "p_role": role, "p_status": status, "p_access_until": access_until})

    def reserve_data_update(self, scope):
        self.require_admin()
        return self._request("POST", "rpc/app_reserve_data_update", body={"p_scope": scope})

    def update_data_job(self, job_id, status):
        self.require_admin()
        self._request("POST", "rpc/app_update_data_job", body={"p_job_id": str(UUID(job_id)), "p_status": status})

    def data_jobs(self):
        self.require_admin()
        return self._request("GET", "app_data_requests", params={"select": "*", "order": "created_at.desc", "limit": 30})
