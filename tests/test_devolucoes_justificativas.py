from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bot_api.routes.admin_liga_entrega import create_admin_liga_entrega_router
from bot_api.services.devolucoes_justificativas_service import (
    DevolucoesJustificativasService, JustificativaConflict, devolucao_id,
)


class JustificativasTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'justificativas.json'
        self.service = DevolucoesJustificativasService(self.path)
        self.row = dict(filial='PATOS', cliente_cod='00123', nota='0456', serie='1',
                        data='2026-11-09', data_devolucao='2026-11-10', cliente='Cliente A')

    def test_identity_and_reimport_preserve_history(self):
        first = self.service.save(self.row, 'Cliente estava fechado', actor='admin:1')
        reimported = {**self.row, 'cliente_cod': '123', 'nota': '456', 'cliente': 'Nome corrigido', 'valor': 999}
        self.assertEqual(devolucao_id(self.row), devolucao_id(reimported))
        self.service.annotate([reimported])
        self.assertEqual(reimported['justificativa']['text'], 'Cliente estava fechado')
        second = self.service.save(reimported, 'Cliente confirmou fechamento', actor='admin:2', version=first['version'])
        reopened = DevolucoesJustificativasService(self.path)
        self.assertEqual(len(reopened.get(second['id'])['history']), 2)
        self.assertEqual(reopened.list('fechamento')['total'], 1)
        self.assertEqual(reopened.list('456')['total'], 1)
        self.assertNotEqual(devolucao_id({**self.row, 'filial': 'SUME'}), first['id'])
        self.assertNotEqual(devolucao_id({**self.row, 'data_devolucao': '2026-11-11'}), first['id'])

    def test_conflict_and_empty_do_not_erase_saved_text(self):
        self.service.save(self.row, 'Primeira versão', actor='a')
        with self.assertRaises(JustificativaConflict):
            self.service.save(self.row, 'Sobrescrita', actor='b')
        with self.assertRaises(ValueError):
            self.service.save(self.row, '   ', actor='a')
        self.assertEqual(self.service.get(devolucao_id(self.row))['text'], 'Primeira versão')

    def client(self, denied=False):
        def feature(context, name):
            if denied:
                raise HTTPException(status_code=403, detail='Sem permissão')
        app = FastAPI()
        source = {'competencia': '2026-11', 'devolucoes_auxiliares': [self.row]}
        app.include_router(create_admin_liga_entrega_router(
            require_admin_panel_auth=lambda **kw: {'mode': 'user', 'user_id': '42'},
            require_admin_panel_feature=feature,
            liga_entrega_expurgo_service=None,
            liga_entrega_snapshot_store=SimpleNamespace(get_latest=lambda **kw: ('sig', source)),
            devolucoes_justificativas_service=self.service,
            record_security_event=lambda *a, **kw: None,
        ))
        return TestClient(app), source

    def test_endpoints_save_query_conflict_and_removed_source(self):
        client, source = self.client()
        response = client.get('/api/admin/liga-entrega/devolucoes?competencia=2026-11')
        self.assertEqual(response.status_code, 200, response.text)
        key = response.json()['rows'][0]['justificativa_id']
        url = '/api/admin/liga-entrega/devolucoes/justificativas/' + key
        response = client.put(url, json={'competencia': '2026-11', 'texto': 'Comércio fechado'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['item']['updated_by'], 'user:42')
        self.assertEqual(client.put(url, json={'competencia': '2026-11', 'texto': 'Mudança'}).status_code, 409)
        source['devolucoes_auxiliares'] = []
        response = client.get('/api/admin/liga-entrega/devolucoes/justificativas?q=fechado')
        self.assertEqual(response.json()['total'], 1)
        self.assertEqual(client.put(url + 'missing', json={'competencia': '2026-11', 'texto': 'Inválido'}).status_code, 404)

    def test_feature_permission_required_for_read_and_write(self):
        client, _ = self.client(denied=True)
        base = '/api/admin/liga-entrega/devolucoes/justificativas'
        self.assertEqual(client.get(base).status_code, 403)
        self.assertEqual(client.put(base + '/' + devolucao_id(self.row), json={'competencia': '2026-11', 'texto': 'Teste'}).status_code, 403)


if __name__ == '__main__':
    unittest.main()
