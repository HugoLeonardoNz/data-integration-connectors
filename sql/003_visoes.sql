-- O que o painel lê.

create view marts.campanha as
select distinct on (empresa, plataforma, id_campanha)
       empresa, plataforma, id_campanha, nome_campanha
from core.campanha_dia
order by empresa, plataforma, id_campanha, dia desc;

-- De onde veio cada lead. Três caminhos verificáveis, nesta ordem:
--   clique      o identificador de clique gravado no lead existe no relatório
--               de cliques da plataforma;
--   formulario  o lead veio do formulário nativo, que já informa a campanha;
--   utm         o nome da campanha no link bate com uma campanha da plataforma.
-- O que não fecha por nenhum deles fica como 'nao_identificada'. Não é
-- distribuído entre as campanhas: aparece no painel com o tamanho que tem.
create view marts.atribuicao_lead as
with campanha_por_nome as (
    select distinct on (empresa, plataforma, nome_campanha)
           empresa, plataforma, nome_campanha, id_campanha
    from marts.campanha
    order by empresa, plataforma, nome_campanha, id_campanha
)
select l.empresa,
       l.id_origem as id_lead,
       l.loja,
       case when c.id_campanha is not null then 'clique'
            when f.id_campanha is not null then 'formulario'
            when u.id_campanha is not null then 'utm'
            else 'nao_identificada'
       end as metodo,
       coalesce(c.plataforma, f.plataforma, u.plataforma, 'nao_identificada') as plataforma,
       coalesce(c.id_campanha, f.id_campanha, u.id_campanha, '') as id_campanha
from core.lead l
left join core.clique c
       on c.empresa = l.empresa and c.id_origem = l.id_clique
left join marts.campanha f
       on f.empresa = l.empresa
      and f.plataforma = l.plataforma_formulario
      and f.id_campanha = l.id_campanha_formulario
left join campanha_por_nome u
       on u.empresa = l.empresa
      and u.plataforma = l.utm_source
      and u.nome_campanha = l.utm_campaign;

-- Investimento, leads, vendas e receita por campanha. A venda sem lead, ou de
-- lead sem origem, cai na linha 'nao_identificada': a receita da visão soma
-- exatamente a receita das vendas ganhas.
create view marts.resultado_por_campanha as
with gasto as (
    select empresa, plataforma, id_campanha,
           sum(investimento) as investimento
    from core.campanha_dia
    group by empresa, plataforma, id_campanha
),
leads as (
    select empresa, plataforma, id_campanha, count(*) as leads
    from marts.atribuicao_lead
    group by empresa, plataforma, id_campanha
),
vendas as (
    select v.empresa,
           coalesce(a.plataforma, 'nao_identificada') as plataforma,
           coalesce(a.id_campanha, '') as id_campanha,
           count(*) as vendas,
           sum(v.valor) as receita
    from core.venda v
    left join marts.atribuicao_lead a
           on a.empresa = v.empresa and a.id_lead = v.id_lead
    where v.situacao = 'ganha'
    group by 1, 2, 3
)
select empresa, plataforma, id_campanha,
       c.nome_campanha,
       coalesce(g.investimento, 0) as investimento,
       coalesce(l.leads, 0) as leads,
       coalesce(v.vendas, 0) as vendas,
       coalesce(v.receita, 0) as receita,
       round(v.receita / nullif(g.investimento, 0), 2) as retorno
from gasto g
full join leads l using (empresa, plataforma, id_campanha)
full join vendas v using (empresa, plataforma, id_campanha)
left join marts.campanha c using (empresa, plataforma, id_campanha);

-- Uma linha por rotina: como terminou a última execução, quando foi o último
-- sucesso e quanto está pendente. É o que o comando `status` lê.
create view marts.saude_das_fontes as
with ultima as (
    select distinct on (fonte, recurso, empresa) *
    from ops.execucao
    order by fonte, recurso, empresa, id desc
),
sucesso as (
    select fonte, recurso, empresa, max(terminada_em) as ultimo_sucesso
    from ops.execucao
    where situacao = 'ok'
    group by fonte, recurso, empresa
),
pendente as (
    select fonte, recurso, empresa, count(*) as rejeitados
    from ops.rejeitado
    group by fonte, recurso, empresa
)
select u.fonte, u.recurso, u.empresa,
       u.situacao as ultima_situacao,
       u.conferencia,
       u.erro as ultimo_erro,
       s.ultimo_sucesso,
       m.valor as marcador,
       coalesce(p.rejeitados, 0) as rejeitados
from ultima u
left join sucesso s using (fonte, recurso, empresa)
left join ops.marcador m using (fonte, recurso, empresa)
left join pendente p using (fonte, recurso, empresa);
