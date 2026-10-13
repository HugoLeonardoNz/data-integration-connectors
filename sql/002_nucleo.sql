-- Dados de negócio, já convertidos. Toda tabela tem a empresa na chave: as
-- empresas do grupo ficam separadas e comparáveis. `execucao_id` diz qual
-- execução gravou a linha por último, `lido_em` quando aquele valor foi lido
-- na fonte e `gravado_em` quando entrou aqui.
--
-- Não há chave estrangeira entre as tabelas (venda -> lead, lead -> clique):
-- cada uma vem de uma fonte, em rotina própria, e a venda pode chegar antes do
-- lead. As visões juntam o que existir.

create table core.produto (
    empresa              text not null,
    id_origem            text not null,
    nome                 text not null,
    categoria            text,
    preco                numeric(12, 2) not null check (preco >= 0),
    moeda                text not null,
    vagas                integer not null check (vagas >= 0),
    ativo                boolean not null,
    atualizado_na_origem timestamptz not null,
    execucao_id          bigint not null references ops.execucao (id),
    lido_em              timestamptz not null,
    gravado_em           timestamptz not null default now(),
    primary key (empresa, id_origem)
);

create table core.campanha_dia (
    empresa       text not null,
    plataforma    text not null,
    id_campanha   text not null,
    dia           date not null,
    nome_campanha text not null,
    investimento  numeric(12, 2) not null check (investimento >= 0),
    impressoes    integer not null check (impressoes >= 0),
    cliques       integer not null check (cliques >= 0),
    execucao_id   bigint not null references ops.execucao (id),
    lido_em       timestamptz not null,
    gravado_em    timestamptz not null default now(),
    primary key (empresa, plataforma, id_campanha, dia)
);

create table core.clique (
    empresa     text not null,
    id_origem   text not null,
    plataforma  text not null,
    id_campanha text not null,
    clicado_em  timestamptz not null,
    execucao_id bigint not null references ops.execucao (id),
    lido_em     timestamptz not null,
    gravado_em  timestamptz not null default now(),
    primary key (empresa, id_origem)
);

create table core.lead (
    empresa                text not null,
    id_origem              text not null,
    loja                   text not null,
    criado_em              timestamptz not null,
    id_clique              text,
    utm_source             text,
    utm_campaign           text,
    plataforma_formulario  text,
    id_campanha_formulario text,
    atualizado_na_origem   timestamptz not null,
    execucao_id            bigint not null references ops.execucao (id),
    lido_em                timestamptz not null,
    gravado_em             timestamptz not null default now(),
    primary key (empresa, id_origem)
);

create table core.venda (
    empresa              text not null,
    id_origem            text not null,
    id_lead              text,
    loja                 text not null,
    valor                numeric(12, 2) not null check (valor >= 0),
    situacao             text not null check (situacao in ('aberta', 'ganha', 'perdida')),
    fechada_em           timestamptz,
    atualizado_na_origem timestamptz not null,
    execucao_id          bigint not null references ops.execucao (id),
    lido_em              timestamptz not null,
    gravado_em           timestamptz not null default now(),
    primary key (empresa, id_origem)
);

create index venda_por_lead on core.venda (empresa, id_lead);
