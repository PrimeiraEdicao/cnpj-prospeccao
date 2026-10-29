"""Reserva de cargas no banco, compartilhada por todas as instâncias do aplicativo."""
from .data_updates import checked_scope


class UserDataUpdates:
    def __init__(self, client, store):
        self.client, self.store = client, store
        self.repository, self.branch = client.repository, client.branch

    def request_update(self, scope=None):
        self.store.require_admin()
        scope = checked_scope(scope) if scope else None
        # Atualiza estados conhecidos antes de reservar a próxima carga.
        self.runs()
        job = self.store.reserve_data_update(scope)
        request_id = job["id"].replace("-", "")
        try:
            request = self.client.request_update(scope, request_id=request_id)
            self.store.update_data_job(job["id"], "queued")
            return request
        except Exception:
            self.store.update_data_job(job["id"], "failed")
            raise

    def runs(self):
        self.store.require_admin()
        runs = self.client.runs()
        for job in self.store.data_jobs():
            if job["status"] not in {"reserved", "queued", "running"}:
                continue
            match = next((r for r in runs if job["id"].replace("-", "") in r.get("display_title", "")), None)
            if match:
                status = ("succeeded" if match.get("conclusion") == "success" else "failed") if match["status"] == "completed" else "running"
                self.store.update_data_job(job["id"], status)
        return runs

    def download_snapshot(self, root):
        self.store.require_admin()
        return self.client.download_snapshot(root)
