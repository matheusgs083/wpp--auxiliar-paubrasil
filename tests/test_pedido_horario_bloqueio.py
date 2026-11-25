from __future__ import annotations

import unittest
from datetime import UTC, datetime

from bot_api.services.pedido_horario_bloqueio import (
    FUSO_PEDIDOS,
    normalizar_horario_bloqueio,
    situacao_bloqueio,
)


class NormalizarHorarioBloqueioTest(unittest.TestCase):
    def test_vazio_significa_sem_bloqueio(self) -> None:
        self.assertEqual(normalizar_horario_bloqueio(""), "")
        self.assertEqual(normalizar_horario_bloqueio(None), "")
        self.assertEqual(normalizar_horario_bloqueio("  "), "")

    def test_aceita_hh_mm_e_completa_hora_com_um_digito(self) -> None:
        self.assertEqual(normalizar_horario_bloqueio("17:30"), "17:30")
        self.assertEqual(normalizar_horario_bloqueio("9:05"), "09:05")

    def test_recusa_formato_invalido_e_meia_noite(self) -> None:
        for valor in ("24:00", "17:60", "1730", "17h30", "abc", "00:00"):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                normalizar_horario_bloqueio(valor)


class SituacaoBloqueioTest(unittest.TestCase):
    def _agora(self, hora: int, minuto: int, segundo: int = 0) -> datetime:
        return datetime(2026, 11, 23, hora, minuto, segundo, tzinfo=FUSO_PEDIDOS)

    def test_sem_horario_nunca_bloqueia(self) -> None:
        situacao = situacao_bloqueio("", self._agora(23, 59))
        self.assertFalse(situacao["bloqueado"])
        self.assertIsNone(situacao["segundos_ate_bloqueio"])
        self.assertEqual(situacao["mensagem"], "")

    def test_janela_abre_e_fecha_nos_limites(self) -> None:
        self.assertTrue(situacao_bloqueio("17:30", self._agora(7, 59), horario_abertura="08:00")["bloqueado"])
        self.assertFalse(situacao_bloqueio("17:30", self._agora(8, 0), horario_abertura="08:00")["bloqueado"])
        self.assertTrue(situacao_bloqueio("17:30", self._agora(17, 30), horario_abertura="08:00")["bloqueado"])
        self.assertIn("08:00", situacao_bloqueio("17:30", self._agora(18, 0), horario_abertura="08:00")["mensagem"])

    def test_janela_invertida_e_rejeitada(self) -> None:
        with self.assertRaises(ValueError):
            situacao_bloqueio("08:00", self._agora(10, 0), horario_abertura="17:00")

    def test_antes_do_horario_libera_e_conta_os_segundos(self) -> None:
        situacao = situacao_bloqueio("17:30", self._agora(17, 0))
        self.assertFalse(situacao["bloqueado"])
        self.assertEqual(situacao["segundos_ate_bloqueio"], 30 * 60)
        self.assertIn("até as 17:30", situacao["mensagem"])

    def test_no_horario_exato_ja_bloqueia(self) -> None:
        situacao = situacao_bloqueio("17:30", self._agora(17, 30))
        self.assertTrue(situacao["bloqueado"])
        self.assertIsNone(situacao["segundos_ate_bloqueio"])
        self.assertIn("encerrada às 17:30", situacao["mensagem"])

    def test_depois_da_meia_noite_libera_de_novo(self) -> None:
        situacao = situacao_bloqueio("17:30", self._agora(0, 5))
        self.assertFalse(situacao["bloqueado"])

    def test_usa_o_fuso_de_patos_mesmo_com_relogio_em_utc(self) -> None:
        # 20:10 UTC = 17:10 em Patos: ainda liberado.
        liberado = situacao_bloqueio("17:30", datetime(2026, 11, 23, 20, 10, tzinfo=UTC))
        self.assertFalse(liberado["bloqueado"])
        # 20:40 UTC = 17:40 em Patos: encerrado.
        encerrado = situacao_bloqueio("17:30", datetime(2026, 11, 23, 20, 40, tzinfo=UTC))
        self.assertTrue(encerrado["bloqueado"])


if __name__ == "__main__":
    unittest.main()
