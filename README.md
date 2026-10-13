# Conectores de dados: API → PostgreSQL

![CI](https://github.com/HugoLeonardoNz/data-integration-connectors/actions/workflows/ci.yml/badge.svg)

Rotinas que leem APIs de terceiros (reservas, anúncios e CRM) e mantêm uma base PostgreSQL em dia, para um grupo com várias empresas. O foco é o que dá errado em integração: a execução que cai no meio, a API que muda um campo sem avisar, o número que a plataforma de anúncios corrige depois, o lead que chega sem origem.

> Peça do portfólio de **Hugo Nazário**. Os outros projetos estão em **[hugonazario.com](https://hugonazario.com/)**.

## O que é e o que não é

É um projeto de demonstração, feito para ser lido e rodado. As três APIs são um **simulador** que acompanha o repositório (`simulador/`), não serviços reais. Escolhi assim por dois motivos: quem avalia roda tudo sem pedir credencial de ninguém, e cada falha pode ser provocada na hora, do mesmo jeito, quantas vezes for preciso. Com uma API real eu só conseguiria contar que a falha aconteceu.

O simulador imita o que dá trabalho numa API de verdade: OAuth com token que vence, paginação por cursor e por número de página, limite de requisições com `Retry-After`, erro 500 passageiro e mudança de campo. O que muda para uma fonte real está em [Limites](#limites).

Não é um sistema em produção e os dados são fictícios (um grupo de turismo com três empresas).

**Com cinco minutos:** leia [`conectores/motor.py`](conectores/motor.py) e [`docs/decisoes.md`](docs/decisoes.md). **Com dez:** rode os comandos de [Como rodar](#como-rodar) e provoque uma falha.

## O que ele garante, e onde está a prova

Cada linha aponta para o teste que falha se a garantia quebrar. Os testes rodam contra um PostgreSQL de verdade.

| Garantia | Como | Teste |
|---|---|---|
| Rodar duas vezes dá o mesmo resultado | Gravação por chave; linha igual não é tocada | `test_rodar_de_novo_nao_duplica_nem_toca_no_que_ja_esta_igual` |
| Queda no meio não perde nem duplica | Lote e marcador na mesma transação; a próxima execução retoma do último lote confirmado | `test_queda_no_meio_retoma_do_ultimo_lote_confirmado` |
| Registros com a mesma data de alteração não somem na retomada | O filtro inclui o marcador | `test_queda_entre_registros_com_a_mesma_data_nao_perde_nenhum` |
| Erro ao gravar desfaz o lote inteiro | Transação por página | `test_erro_ao_gravar_desfaz_o_lote_inteiro` |
| Campo renomeado pela fonte não publica dado pela metade | A execução para, o marcador não anda, a resposta bruta fica guardada | `test_campo_renomeado_para_a_execucao_sem_estragar_o_que_ja_existe` |
| Depois da correção, nada precisa ser pedido de novo à fonte | Reprocesso a partir da resposta bruta | `test_depois_de_corrigir_o_conector_o_bruto_e_reaplicado_sem_chamar_a_fonte` |
| Um item ruim não derruba o lote | Vai para `ops.rejeitado` e sai de lá quando a fonte corrige | `test_item_ruim_fica_separado_e_o_resto_do_lote_entra` |
| Número revisto pela plataforma de anúncios é corrigido | Releitura de uma janela de 7 dias | `test_numero_revisto_pela_plataforma_e_corrigido_sem_duplicar` |
| Reaplicar uma leitura antiga não desfaz um dado mais novo | Cada linha guarda quando foi lida na fonte; leitura mais antiga não entra | `test_reprocesso_de_execucao_antiga_nao_passa_por_cima_de_dado_mais_novo` |
| Falha de rede, 429, token vencido e página de erro com status 200 são tratados cada um do seu jeito | `conectores/cliente.py` | `tests/test_cliente.py` |
| Duas execuções do mesmo recurso não rodam juntas | Trava do PostgreSQL por recurso e empresa | `test_duas_execucoes_do_mesmo_recurso_nao_rodam_juntas` |
| O que o banco tem bate com a fonte | Conferência de contagem ao fim de cada execução | `test_carga_inicial_traz_tudo_e_confere_com_a_fonte` |
| Falha e rotina parada são visíveis | `status` aponta falha, atraso, divergência e recusados | `tests/test_saude.py` |
| Fonte fora do ar a noite toda gera um aviso, não um por execução | Avisa quando a situação muda: ao quebrar e ao voltar | `test_falha_repetida_avisa_uma_vez_e_avisa_de_novo_quando_volta` |
| A receita do painel fecha com as vendas | Lead sem origem fica como "não identificada", sem rateio | `test_receita_e_investimento_do_painel_fecham_com_a_fonte` |
| As empresas não se misturam | A empresa faz parte da chave de toda tabela | `test_cada_empresa_fica_com_os_proprios_dados` |

## Como rodar

Precisa de Docker e Python 3.11.

```bash
docker compose up -d                      # PostgreSQL (porta 5544) e a API simulada (porta 8090)
python -m venv .venv && source .venv/bin/activate    # no Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

python -m conectores migrar               # cria as tabelas
python -m conectores ciclo                # sincroniza tudo, das três empresas
python -m conectores status               # situação de cada rotina
pytest -v                                 # os testes, em banco separado
```

Rode `python -m conectores ciclo` de novo: nenhuma linha nova, nenhuma alterada.

```
anuncios.campanhas   rota-sul        lidas    96  novas     0  alteradas     0  recusadas   0  conferência -
anuncios.cliques     rota-sul        lidas     1  novas     0  alteradas     0  recusadas   0  conferência ok
crm.leads            rota-sul        lidas     1  novas     0  alteradas     0  recusadas   0  conferência ok
crm.vendas           rota-sul        lidas    23  novas     0  alteradas     0  recusadas   0  conferência ok
reservas.produtos    rota-sul        lidas     1  novas     0  alteradas     0  recusadas   0  conferência ok
```

As campanhas releem a janela de revisão (8 dias, 12 campanhas). As outras leem só os registros que empatam com o marcador: um produto, e 23 vendas fechadas no mesmo instante.

O resultado por campanha da empresa `rota-sul`, somado por plataforma, é o que um painel leria:

```sql
select plataforma, sum(investimento) as investimento, sum(leads) as leads,
       sum(vendas) as vendas, sum(receita) as receita
from marts.resultado_por_campanha
where empresa = 'rota-sul'
group by plataforma order by plataforma;
```

| plataforma | investimento | leads | vendas | receita |
|---|---:|---:|---:|---:|
| google | 74490.74 | 187 | 33 | 157118.50 |
| meta | 75032.90 | 190 | 35 | 154328.70 |
| nao_identificada | 0 | 206 | 69 | 306439.35 |
| tiktok | 68839.96 | 217 | 33 | 132899.84 |

A linha `nao_identificada` é a maior em receita. Num painel real, esse seria o primeiro achado: o problema a resolver é o rastreamento, antes de comparar campanhas. Esta tabela é conferida contra o simulador em `tests/test_readme.py`.

### Provocar uma falha

Com tudo no ar, o simulador aceita falhas por `POST /_caos`:

```bash
# A fonte fica instável: duas respostas 500. O cliente espera e repete.
curl -X POST localhost:8090/_caos -H 'content-type: application/json' -d '{"erros_500": 2}'
python -m conectores sincronizar reservas.produtos

# 30 produtos mudam de preço e a fonte troca o campo "price" por "price_amount".
curl -X POST localhost:8090/_caos -H 'content-type: application/json' \
     -d '{"alterar_produtos": 30, "renomear": {"produtos": {"price": "price_amount"}}}'
python -m conectores sincronizar reservas.produtos    # falha e avisa
python -m conectores status                           # sai com código 1 e mostra o motivo

# A fonte volta ao normal. A execução seguinte retoma do mesmo ponto.
curl -X POST localhost:8090/_caos -H 'content-type: application/json' -d '{"renomear": {}}'
python -m conectores sincronizar reservas.produtos
```

## Como funciona

```
API da fonte ──> cliente.py ──> motor.py ──┬──> raw.pagina      resposta como chegou
   (OAuth, paginação,     (por página)     ├──> core.*          dado convertido, por chave
    429, 5xx)                              ├──> ops.rejeitado   item que não passou
                                           ├──> ops.marcador    até onde a leitura foi confirmada
                                           └──> ops.execucao    o que cada execução fez
                                                     │
                                marts.*  <───────────┘          visões que o painel lê
```

Para cada página, o motor grava a resposta bruta e confirma. Depois, numa transação só, grava os itens válidos, separa os inválidos e avança o marcador. O arquivo [`conectores/motor.py`](conectores/motor.py) é o centro do projeto e cabe numa leitura.

Há dois jeitos de ler uma fonte, em [`conectores/fontes.py`](conectores/fontes.py):

- **por alteração**, quando a fonte informa a data de alteração (reservas, CRM, cliques): lê só o que mudou desde o marcador;
- **por janela**, quando a fonte entrega números por dia e os revê depois (investimento em anúncios): relê os últimos 7 dias a cada execução.

### Ligar a venda à campanha

A visão `marts.atribuicao_lead` procura a origem de cada lead por três caminhos, nesta ordem: o identificador de clique gravado no lead, o formulário nativo da plataforma e o nome da campanha no link. O que não fecha por nenhum deles fica como `nao_identificada` e aparece em `marts.resultado_por_campanha` com o tamanho que tem. Distribuir esses leads entre as campanhas faria o painel parecer completo e inventaria retorno para campanha que não o teve.

### Acrescentar uma fonte

Escreva a função que converte um item e registre um `Recurso` em `fontes.py`, com a tabela, a chave e o jeito de paginar. O motor não muda. Cada recurso atual é uma função de conversão e uma declaração de poucas linhas.

## Limites

- **Exclusão na origem.** Se a fonte apaga um registro em vez de marcá-lo como inativo, a linha fica no banco. A conferência de contagem acusa a diferença, mas não a resolve.
- **Registro que aparece atrasado.** Se a fonte publicar um registro com data de alteração anterior ao marcador (relógio defasado, gravação que demora a confirmar do lado dela), a leitura por alteração não o vê. O remédio usual é reler alguns minutos antes do marcador a cada execução; a gravação por chave já comporta isso, mas não está feito.
- **Revisão antiga.** Número de anúncio corrigido há mais de 7 dias não é relido. A janela é um parâmetro de cada conector, porque cada plataforma revê os dias fechados por um prazo diferente.
- **Uma origem por lead.** A atribuição liga o lead a uma campanha. Não há modelo de vários toques (primeiro clique, último clique, peso por posição).
- **Uma credencial para o grupo.** O cliente HTTP usa uma credencial e passa a empresa como parâmetro, como numa conta gerenciadora. Se cada empresa tiver conta e credencial próprias, a mudança fica em `cli.py`, onde o cliente é criado.
- **Resposta bruta sem limpeza.** `raw.pagina` só cresce. Falta a rotina que apaga o que passou de um prazo.
- **OAuth.** O simulador usa o fluxo de credenciais do cliente. Google, Meta e TikTok usam autorização do usuário com token de renovação, e cada uma exige aprovação do aplicativo. O cliente HTTP precisa de mais um jeito de obter o token; o motor não muda.
- **Alerta do silêncio.** Rotina que não rodou não avisa sozinha. O comando `status` acusa o atraso, mas alguém de fora precisa chamá-lo (veja [docs/operacao.md](docs/operacao.md)).
- **Volume.** A gravação é linha a linha dentro do lote, o que serve para milhares de registros por execução. Para milhões, o caminho é `COPY` para uma tabela temporária.

## Documentação

- [docs/decisoes.md](docs/decisoes.md): as decisões que não são óbvias no código, com o motivo.
- [docs/operacao.md](docs/operacao.md): o que fazer quando uma rotina falha.

## Estrutura

```
conectores/
  cliente.py     HTTP: token, nova tentativa, limite de requisições
  contrato.py    leitura tipada dos campos da fonte
  motor.py       sincronização e reprocesso
  fontes.py      os conectores
  saude.py       situação de cada rotina
  cli.py         linha de comando
  alerta.py      aviso de falha (log e webhook)
  banco.py       conexão e migrações
  config.py      configuração lida do ambiente e do .env
simulador/       a API de terceiros simulada
sql/             migrações: controle (ops, raw), dados (core) e visões (marts)
tests/           testes contra PostgreSQL e contra a API por HTTP
```

## Licença

MIT.
