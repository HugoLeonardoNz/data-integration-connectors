# Operação

Para quem vai manter as rotinas sem ter escrito o código.

## Agendar

Com Docker, o ciclo completo a cada 15 minutos:

```bash
docker compose --profile agendado up -d
```

Com `cron`, uma linha para o ciclo e outra para a verificação:

```cron
*/15 * * * *  cd /app && python -m conectores ciclo
0 * * * *     cd /app && python -m conectores status || /usr/local/bin/avisar "rotina com problema"
```

A segunda linha é necessária. Quando uma rotina falha, ela mesma avisa. Quando ela não roda (agendador parado, máquina desligada), ninguém avisa, e só o `status` percebe pelo tempo sem sucesso. Ele sai com código 1 se houver qualquer problema.

## Avisos

Toda falha vai para o log e para `ops.execucao`. O aviso sai quando a situação muda: na primeira falha, quando o tipo do erro muda e quando a rotina volta ao normal. Enquanto a mesma falha se repete, não há aviso novo.

Se `ALERTA_WEBHOOK_URL` estiver preenchida, o aviso vai também para esse endereço, como `{"text": "..."}`. É o formato do Slack e do Google Chat; outros serviços podem pedir outro nome de campo, e a troca é uma linha em `conectores/alerta.py`.

## O que o `status` mostra, e o que fazer

**`falhou: FonteIndisponivel`**
A fonte não respondeu depois de cinco tentativas. Nada a fazer no código: a próxima execução retoma de onde parou. Se persistir, o problema é da fonte ou da rede.

**`falhou: ContratoQuebrado: campo 'x' ausente em N de M itens`**
A fonte mudou o formato. O marcador não andou e o que já estava no banco não foi tocado.

1. Veja o que chegou: `select corpo from raw.pagina where execucao_id = <id>`.
2. Corrija a função de conversão do recurso em `conectores/fontes.py` e acrescente um teste com o formato novo.
3. Reaplique o que chegou durante a falha: `python -m conectores reprocessar <recurso> <id>`. A ordem não importa: se uma execução mais nova já trouxe o dado, o bruto antigo não passa por cima.
4. Rode `python -m conectores sincronizar <recurso>` para trazer o que veio depois.

**`falhou: ErroDeApi: autenticação recusada: 401`** ou **`ErroDeApi: 403 em ...`**
Credencial vencida ou sem permissão. Renove `API_CLIENT_ID` e `API_CLIENT_SECRET`.

**`atrasada: Nh sem sucesso`**
A rotina não termina com sucesso há mais tempo que `HORAS_DE_TOLERANCIA`. Veja se o agendador está de pé e olhe as últimas execuções:

```sql
select id, iniciada_em, situacao, lidas, erro
from ops.execucao
where fonte = 'crm' and recurso = 'leads'
order by id desc limit 10;
```

**`contagem não confere com a fonte`**
O banco tem um número de registros diferente do que a fonte informa. As causas, da mais comum para a menos: itens recusados (veja abaixo), registro apagado na origem, ou registro criado na fonte durante a execução (some na execução seguinte).

**`N item(ns) recusado(s)`**

```sql
select chave, motivo, item from ops.rejeitado where recurso = 'produtos';
```

O item sai da fila sozinho quando a fonte manda uma versão válida. Se o motivo for uma regra do conector que está errada (um valor novo e legítimo de situação, por exemplo), corrija a conversão e reprocesse a execução.

## Recarregar um recurso do zero

Apague o marcador. A próxima execução lê tudo de novo e regrava por chave, sem duplicar.

```sql
delete from ops.marcador where fonte = 'crm' and recurso = 'leads' and empresa = 'rota-sul';
```

## Incluir uma empresa

Acrescente o identificador em `EMPRESAS`. A primeira execução faz a carga completa dela. Nenhuma tabela muda: a empresa já é parte da chave de todas.
