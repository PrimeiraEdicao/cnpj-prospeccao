from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.user_data_updates import UserDataUpdates
from src.user_store import StoreError
from src.data_updates import DataUpdateError

JOB='11111111-1111-4111-8111-111111111111'
def controller():
    client=SimpleNamespace(repository='owner/repo',branch='main',runs=Mock(return_value=[]),request_update=Mock(return_value={'id':JOB.replace('-','')}),download_snapshot=Mock())
    store=SimpleNamespace(require_admin=Mock(),reserve_data_update=Mock(return_value={'id':JOB}),update_data_job=Mock(),data_jobs=Mock(return_value=[]))
    return UserDataUpdates(client,store),client,store

def test_denied_user_never_touches_github():
    control,client,store=controller();store.require_admin.side_effect=StoreError('denied')
    for call in [control.request_update,control.runs,lambda:control.download_snapshot(None)]:
        with pytest.raises(StoreError):call()
    client.runs.assert_not_called();client.request_update.assert_not_called();client.download_snapshot.assert_not_called()

def test_job_reserved_before_dispatch_with_persistent_identifier():
    control,client,store=controller()
    control.request_update()
    store.reserve_data_update.assert_called_once_with(None)
    client.request_update.assert_called_once_with(None,request_id=JOB.replace('-',''))
    store.update_data_job.assert_called_once_with(JOB,'queued')

def test_failed_dispatch_releases_database_reservation():
    control,client,store=controller();client.request_update.side_effect=DataUpdateError('failed')
    with pytest.raises(DataUpdateError):control.request_update()
    store.update_data_job.assert_called_once_with(JOB,'failed')

def test_completed_github_run_updates_persisted_job():
    control,client,store=controller()
    store.data_jobs.return_value=[{'id':JOB,'status':'queued'}]
    client.runs.return_value=[{'display_title':'CNPJ '+JOB.replace('-',''),'status':'completed','conclusion':'success'}]
    control.runs();store.update_data_job.assert_called_once_with(JOB,'succeeded')
