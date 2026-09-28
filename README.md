# Desafio A2A com MCP - A Ponte

**Projeto:** MBA Engenharia de Software com IA, curso de MCP e A2A

Este repositório contém a solução do desafio de construção de um Servidor MCP e um Agente A2A, demonstrando a "ponte" entre os protocolos através de MRTR (Model-Round-Trip-Resolution) e state management.

## Como rodar

A partir de um clone limpo do repositório, execute os passos abaixo. 
Requer Python 3.10+.

1. **Inicie os Servidores (MCP e Agente):**
   Abra o **primeiro terminal** e execute o script abaixo. Ele fará o setup das dependências, gerará o secret (se necessário) e subirá o MCP e o Agente em background no mesmo terminal.
   ```bash
   python3 start_servers.py
   ```
   *(Pressione `CTRL+C` a qualquer momento nesse terminal para derrubar ambos os servidores)*

2. **Execute o Validador:**
   Abra um **segundo terminal** e execute:
   ```bash
   python3 validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301
   ```

## Onde a ponte acontece

A ponte entre os dois protocolos (MCP interno, A2A externo) ocorre dentro da função `processar_task` do arquivo `agente/app.py`:

1. **Ida (Pausa da Task):** Quando o cliente MCP recebe uma resposta com `resultType == "input_required"`, o agente intercepta isso, não tenta responder por conta própria e coloca a Task no estado `TASK_STATE_INPUT_REQUIRED`. O `requestState` devolvido pelo MCP é guardado na memória do agente, no dicionário `PAUSED_STATES`, atrelado ao ID daquela Task. Para o cliente A2A, as alternativas são retornadas como a última mensagem do histórico da Task (`alternativas: sala1, sala2`).
2. **Volta (Retomada da Task):** Quando o cliente A2A envia um novo comando `SendMessage` para a mesma Task (ex: `escolha=sala-mirante`), o agente recupera o `requestState` e a chave de `inputRequests` em `PAUSED_STATES`. Em seguida, repete a chamada MCP (`tools/call` de reserva) gerando um novo `id` de JSON-RPC, porém enviando o `requestState` opaco de volta e a `action` no bloco `inputResponses` exatamente como o servidor exige, fechando a ponte sem que o `requestState` jamais vaze para a rede externa A2A.

## Decisões técnicas

* **Proteção do `requestState`:** O `requestState` é construído como um payload assinado (HMAC-SHA256). No arquivo `servidor-mcp/app.py`, foi usada a variável de ambiente `REQUEST_STATE_SECRET` como chave criptográfica para um `hmac.new`. O JSON das propriedades originais e a data de expiração (UTC) são selados juntos (hash da string base64 concatenda com timestamp).
* **Validade do `requestState`:** O estado tem validade fixa de **15 minutos** a partir de sua criação. O payload inclui uma timestamp `expires_at` que é verificada durante o retry.
* **Armazenamento das Tasks:** O agente não usa banco de dados externo. O estado é mantido inteiramente em memória nos dicionários `TASKS` e `PAUSED_STATES` (`agente/app.py`). Essa é uma escolha arquitetural válida pelo escopo do projeto, garantindo isolamento total de `requestState` entre requests de pausa paralelos.
* **Assincronicidade A2A vs Sincronicidade A2A+MCP:** Embora a interface A2A seja modelada em formato assíncrono baseado em polling (`GetTask`), o processamento atual na ponte `agente/app.py` é realizado como uma state-machine que aguarda a promisse do HTTP cliente com o servidor MCP (chamadas a `httpx.AsyncClient`).
* **Testabilidade e Injeção de Dependência:** O cliente HTTPX do Agente A2A foi modelado através de uma `AsyncClientFactory`, permitindo injetar mocks durante os testes de unidade e não ferir a semântica da biblioteca `TestClient` da FastAPI.

## Saída do validador

```text
trace-id desta execucao: d6305aab2733d01f80879c5c8ba0fbde
procure esse valor no stderr do servidor MCP para conferir a propagacao do traceparent.

PASS 01 tools/list traz as tres tools
PASS 02 toda tool tem inputSchema de objeto
PASS 03 listar_salas devolve structuredContent e o mesmo JSON em texto
PASS 04 _meta sem protocolVersion devolve -32602 e HTTP 400
PASS 05 _meta sem clientCapabilities devolve -32602 e HTTP 400
PASS 06 tool inexistente e recusada, por -32602 ou por isError
PASS 07 resources/read de politica://uso devolve a politica
PASS 08 resources/read de URI inexistente devolve -32602
PASS 09 sala inexistente devolve isError com a mensagem exata
PASS 10 fora da janela devolve isError com a mensagem exata
PASS 11 duracao acima de 2h devolve isError com a mensagem exata
PASS 12 intervalo invertido devolve isError com a mensagem exata
PASS 13 conflito devolve input_required com inputRequests e requestState
PASS 14 a elicitation e form mode e oferece as alternativas na ordem certa
PASS 15 conflito sem a capability elicitation devolve -32021 e HTTP 400
PASS 16 retry com inputResponses e requestState conclui a reserva
PASS 17 requestState adulterado e rejeitado com -32602
PASS 18 argumentos adulterados no retry nao tomam efeito
PASS 19 recusa conclui sem reservar e sem isError
PASS 20 conflito sem alternativa possivel devolve isError com a mensagem exata

PASS 21 agent card responde 200 no well-known com JSON
PASS 22 o card declara a interface JSON-RPC com url e versao 1.0
PASS 23 o card declara a skill reservar-sala
PASS 24 SendMessage com sala livre conclui a Task
PASS 25 o artifact chama reserva e traz a versao da politica
PASS 26 GetTask devolve id, contextId e estado corrente
PASS 27 SendMessage com sala ocupada pausa a Task
PASS 28 a Task pausada lista as alternativas na ordem certa
PASS 29 escolha fora do enum mantem a Task pausada
PASS 30 a continuacao conclui a Task na sala escolhida
PASS 31 SendMessage em Task terminal e recusado
PASS 32 a recusa termina a Task em CANCELED
PASS 33 duas Tasks pausadas ao mesmo tempo concluem cada uma com a sua reserva
PASS 34 nenhuma resposta A2A carrega o requestState
PASS 35 sala inexistente termina a Task em FAILED com a mensagem da tool
PASS 36 o agente e deterministico: o mesmo pedido produz a mesma pausa

resumo: 36 passaram, 0 falharam, de 36 verificacoes
```
