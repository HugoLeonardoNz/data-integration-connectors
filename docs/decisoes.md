# Decisões

O que não dá para deduzir lendo o código, com o motivo de cada escolha.

## 1. O marcador avança na mesma transação do lote

O jeito comum de errar é gravar os dados, confirmar e só então gravar o marcador. Se o processo cai entre os dois passos, o resultado depende da ordem: ou relê tudo, ou pula um lote. Aqui os dois são gravados juntos. Ou o lote entrou e o marcador andou, ou nenhum dos dois.

## 2. O filtro inclui o marcador ("a partir de", não "depois de")

Dois registros podem ter a mesma data de alteração. Se a página termina entre eles e a execução cai, pedir "depois do marcador" na retomada pula o segundo, e ninguém percebe. Pedir "a partir do marcador" relê um ou dois registros que já estão no banco, e isso não custa nada porque a gravação é por chave. O teste `test_queda_entre_registros_com_a_mesma_data_nao_perde_nenhum` cobre exatamente esse caso.

## 3. A resposta bruta é confirmada antes da conversão

Ela é gravada numa transação separada, antes de qualquer validação. Se a conversão falhar, o que a fonte mandou continua guardado. Isso serve para duas coisas: ver o que chegou no dia da falha e reaplicar tudo depois de corrigir o conector, sem depender de a fonte ainda ter aquele dado.

Fica no próprio PostgreSQL, em `jsonb`, porque assim entra no mesmo backup e na mesma consulta que o resto. Com volume grande, o lugar dela é um armazenamento de arquivos, com só o endereço no banco.

## 4. Item ruim é separado; formato mudado para a execução

Um produto sem preço é um problema daquele produto. Vai para `ops.rejeitado` e o resto do lote entra. Mas se mais da metade da página vem sem o mesmo campo, e são pelo menos cinco itens, quem mudou foi a fonte. Gravar o que sobrou publicaria um dado pela metade com cara de completo, então a execução para e o marcador fica onde estava.

O piso de cinco itens existe porque, sem ele, um único item ruim numa página de um item travaria a rotina para sempre.

## 5. Linha igual não é regravada

O `on conflict ... do update` tem um `where ... is distinct from`. Sem ele, toda execução regravaria as linhas relidas, a coluna `gravado_em` mudaria sem motivo e o contador "alteradas" contaria leitura como alteração. Com ele, "alteradas" é o número de linhas que mudaram de verdade.

## 6. Anúncios são relidos por janela, não por data de alteração

As plataformas de anúncio corrigem investimento e conversão de dias já fechados. Ler só o dia novo deixaria o banco com o número de primeira versão. Cada execução relê os últimos 7 dias e grava por chave (empresa, plataforma, campanha, dia), então a correção substitui o valor antigo.

## 7. A trava é do PostgreSQL, não uma coluna "rodando"

A trava de aviso (`pg_try_advisory_lock`) é solta sozinha quando a conexão cai. Uma coluna de situação ficaria presa em "rodando" se o processo morresse, e alguém teria que destravar à mão. Como efeito colateral, quem pega a trava e encontra uma execução ainda "rodando" sabe que ela é de um processo que morreu, e a registra como falha.

## 8. O marcador é texto

Guarda uma data e hora ISO para as fontes lidas por alteração e uma data ISO para as lidas por janela. As duas ordenam corretamente como texto, e é isso que permite o `greatest` que impede o marcador de andar para trás num reprocesso. Um formato novo de marcador que não ordene como texto quebra essa regra.

## 9. Lead sem origem não é rateado

Cerca de um quarto dos leads do simulador chega sem identificação. Distribuir esses leads entre as campanhas, na proporção das outras, faria todo lead ter uma campanha e o painel parecer completo. Também inflaria o retorno de cada campanha com venda que ela não gerou. A visão mantém a linha "não identificada", e o tamanho dela é uma medida de quanto do rastreamento está funcionando.

## 10. Leitura antiga não passa por cima de leitura nova

Cada linha guarda `lido_em`, o momento em que aquele valor saiu da fonte, e a gravação só acontece se a leitura que chega não for mais antiga que a que está no banco. O caso que isso resolve: uma execução falha, a resposta bruta dela fica guardada, a fonte muda o dado, uma execução nova o lê, e só depois alguém reaplica o bruto antigo. Sem a comparação, o valor velho voltaria e ninguém veria. É também o que permite reprocessar qualquer execução sem medo de ordem.

## 11. O aviso sai quando a situação muda

Uma rotina que roda a cada 15 minutos contra uma fonte fora do ar falharia umas trinta vezes numa noite. Trinta avisos iguais ensinam quem recebe a ignorar o canal. O motor avisa na primeira falha, fica quieto enquanto o erro for do mesmo tipo, avisa se o tipo do erro mudar e avisa quando a rotina volta. O mesmo vale para a contagem que não confere. As falhas repetidas continuam no log e em `ops.execucao`.

## 12. A conferência que falha não derruba a carga

A contagem na fonte é uma chamada a mais, feita depois que os dados entraram. Se ela falhar, a execução termina como "ok" sem conferência. Marcar como falha diria a quem olha o painel que a carga não aconteceu, e aconteceu.

## 13. Sem ORM e sem orquestrador

O SQL está à vista em `sql/` e no motor, porque é ele que precisa ser revisado numa integração. Para agendar, o projeto traz um laço simples (`agendar`) e funciona com `cron`. Cinco rotinas não justificam um Airflow. Se passarem de algumas dezenas, ou se uma depender do término de outra, a conta muda.

## 14. As APIs são simuladas

Está explicado no README. O custo é que o simulador só cobre os comportamentos que eu sabia que queria testar. Uma API real tem surpresas que nenhum simulador escrito por quem fez o conector vai ter.
