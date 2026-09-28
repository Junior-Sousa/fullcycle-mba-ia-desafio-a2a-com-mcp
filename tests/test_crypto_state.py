import unittest
from unittest.mock import patch
import os

from crypto_state import seal_state, unseal_state

class TestCryptoState(unittest.TestCase):
    def setUp(self):
        # Garante que a variável existe para a maioria dos testes
        os.environ["REQUEST_STATE_SECRET"] = "04e1d4bd35723316e8c132e22c4133620570abee1ca38210bd78825bb0b8923b"

    def test_caminho_feliz(self):
        payload_original = {"sala": "sala-garagem", "responsavel": "Marty"}
        token = seal_state(payload_original)
        
        ok, data = unseal_state(token)
        self.assertTrue(ok)
        self.assertEqual(data["sala"], "sala-garagem")
        self.assertEqual(data["responsavel"], "Marty")

    def test_adulteracao_payload(self):
        token = seal_state({"teste": "123"})
        # Adultera o primeiro caractere (corrompe o payload)
        bad_token = "A" + token[1:]
        
        ok, msg = unseal_state(bad_token)
        self.assertFalse(ok)
        self.assertEqual(msg, "Assinatura invalida ou token adulterado")

    def test_adulteracao_assinatura(self):
        token = seal_state({"teste": "123"})
        # Adultera o penúltimo caractere do token (para evitar o fallback da decodificacao de bits ignorados)
        bad_token = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1:]
        
        ok, msg = unseal_state(bad_token)
        self.assertFalse(ok)
        self.assertEqual(msg, "Assinatura invalida ou token adulterado")

    def test_formato_invalido(self):
        ok, msg = unseal_state("string_sem_ponto")
        self.assertFalse(ok)
        self.assertEqual(msg, "Formato do token invalido")

    @patch('crypto_state.time.time')
    def test_token_expirado(self, mock_time):
        mock_time.return_value = 1000.0
        token = seal_state({"data": "old"}, ttl_seconds=10)
        
        # Avança o tempo além do TTL (11 segundos > 10)
        mock_time.return_value = 1011.0
        
        ok, msg = unseal_state(token)
        self.assertFalse(ok)
        self.assertEqual(msg, "Token expirado")

    def test_variavel_ambiente_ausente(self):
        if "REQUEST_STATE_SECRET" in os.environ:
            del os.environ["REQUEST_STATE_SECRET"]
            
        with self.assertRaises(ValueError) as context:
            seal_state({"a": "b"})
            
        self.assertTrue("deve ter no minimo 32 bytes" in str(context.exception))

if __name__ == '__main__':
    unittest.main()
