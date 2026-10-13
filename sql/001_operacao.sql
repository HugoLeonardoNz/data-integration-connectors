-- Controle das rotinas: o que rodou, até onde leu, o que foi recusado e a
-- resposta bruta de cada página. Nada aqui é dado de negócio.

create schema if not exists ops;
create schema if not exists raw;
create schema if not exists core;
create schema if not exists marts;

-- Uma linha por execução de (fonte, recurso, empresa). Os contadores são
-- gravados na mesma transação do lote, então refletem só o que foi confirmado.
create table ops.execucao (
    id               bigint generated always as identity primary key,
    fonte            text not null,
    recurso          text not null,
    empresa          text not null,
    iniciada_em      timestamptz not null default now(),
    terminada_em     timestamptz,
    situacao         text not null default 'rodando'
                     check (situacao in ('rodando', 'ok', 'falhou')),
    paginas          integer not null default 0,
    lidas            integer not null default 0,
    inseridas        integer not null default 0,
    atualizadas      integer not null default 0,
    rejeitadas       integer not null default 0,
    marcador_inicial text,
    marcador_final   text,
    total_na_fonte   bigint,
    total_no_banco   bigint,
    conferencia      text check (conferencia in ('ok', 'divergente')),
    reprocesso_de    bigint references ops.execucao (id),
    erro             text
);

create index execucao_por_recurso on ops.execucao (fonte, recurso, empresa, id desc);

-- Até onde a leitura foi confirmada. Só avança junto com o lote, na mesma
-- transação; por isso uma queda no meio retoma daqui.
create table ops.marcador (
    fonte         text not null,
    recurso       text not null,
    empresa       text not null,
    valor         text not null,
    atualizado_em timestamptz not null default now(),
    primary key (fonte, recurso, empresa)
);

-- Itens que a fonte mandou e não passaram na validação. Ficam aqui até a
-- fonte mandar uma versão válida do mesmo item.
create table ops.rejeitado (
    id          bigint generated always as identity primary key,
    execucao_id bigint not null references ops.execucao (id),
    fonte       text not null,
    recurso     text not null,
    empresa     text not null,
    chave       text not null,
    motivo      text not null,
    item        jsonb not null,
    criado_em   timestamptz not null default now()
);

create index rejeitado_por_chave on ops.rejeitado (fonte, recurso, empresa, chave);

-- A resposta da API como chegou, antes de qualquer conversão. É o que
-- permite reprocessar sem chamar a fonte de novo.
create table raw.pagina (
    id          bigint generated always as identity primary key,
    execucao_id bigint not null references ops.execucao (id),
    fonte       text not null,
    recurso     text not null,
    empresa     text not null,
    numero      integer not null,
    marcador    text,
    recebida_em timestamptz not null default now(),
    corpo       jsonb not null
);

create index pagina_por_execucao on raw.pagina (execucao_id, numero);
