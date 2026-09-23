# H3 MAX — tudo que entra, o que faz e como usar

**Atualização:** a operação manual dos oito workflows descrita neste inventário foi substituída pelo painel único **H3 Studio**. O inventário continua válido como registro dos componentes. O uso atual está no [README](../README.md), e a pesquisa adicional em [PESQUISA_INTEGRACAO.md](PESQUISA_INTEGRACAO.md). A qualidade em GPU ainda não foi confirmada.

**Cobertura atual do painel (23/09):** texto, primeiro/último quadro, até nove imagens de referência, três vídeos e três áudios (até 12 referências ao todo); escolha automática de FL2VA/Ref2VA e opção Híbrido; ajustes de movimento, aparência e câmera; refino e reparo temporal combináveis quando compatíveis. Estes caminhos utilizam 12 dos 24 pesos do manifesto e quatro dos sete packs externos. Os outros pesos e packs continuam previstos como opcionais, sem integração automática ao painel.

A operação já inclui biblioteca persistente, reprodução/download, recuperação e exportação/importação da receita, cancelamento direcionado e comparação **Original / Com ajustes** quando há refino ou reparo temporal. A disponibilidade verifica pesos e nós reais; a comparação conserva o áudio original e não exige gerar a base novamente. Contratos, arquivos e operação HTTP têm testes locais; carregamento dos pesos, consumo e qualidade ainda dependem da execução real em GPU. A [auditoria de cobertura](audit/studio-feature-gap.json) distingue correções e pendências.

**Ainda não integrado:** pose/ControlNet, quadros intermediários, edição de vídeo existente, continuação/ponte de clipes, trilha musical contínua, LTX, checkpoints opcionais, Turbo e diretor multimodal. Referência de vídeo já disponível não equivale a editar ou continuar esse vídeo. A inicialização baixa os modelos antes de abrir o painel; nesse intervalo, o acompanhamento permanece nos registros do Runpod.

As seções seguintes preservam a conferência dos oito grafos anteriores. Seus limites de duas referências, ausência de último quadro e ajustes manuais entre passes descrevem esses arquivos antigos, não o compilador atual do Studio.

Conferência de 23/09/2026 sobre o pacote revisado. Este documento descreve o conteúdo completo, incluindo recursos auxiliares que não apareceram no resumo inicial.

**O conjunto inclui geração por texto, imagem e referências; áudio; perfis de movimento; aparência humana; câmera; diretor de texto; Hybrid; upscale/refine; processamento temporal; e ferramentas adicionais para fluxos futuros.** Estar instalado ou listado no manifesto não significa estar conectado aos oito workflows, nem ter passado por render real.

O inventário de máquinas, com nomes exatos de arquivos, revisões, hashes, tamanhos e tipos de nodes, está em [INVENTARIO_COMPLETO.json](INVENTARIO_COMPLETO.json). O JSON é uma conferência do pacote, não um registro de execução na GPU.

## 1. O núcleo que vamos usar

| Componente | Papel no resultado | Uso no pacote |
|---|---|---|
| ComfyUI | Interface visual, execução dos grafos e API | Presente em todos os caminhos; instalado em commit fixado |
| H3 FL2VA pruned/int8 | Gerador de vídeo e áudio a partir de texto e/ou quadro inicial | Workflows 01, 02, 05, 06, 07 e 08; base do Hybrid 04 |
| H3 Ref2VA pruned/int8 | Gerador condicionado por referências | Workflow 03; fornece parte do modelo no Hybrid 04 |
| Qwen3-VL-32B H3 NVFP4/AWQ | Encoder que transforma a entrada em condicionamento do H3 | Usado pelos oito workflows; não é o serviço externo do diretor |
| VAE de vídeo H3 | Converte representações internas em imagens | Decodifica o vídeo gerado e participa dos caminhos com imagens |
| VAE de áudio H3 | Converte a representação interna de áudio em som | Geração e montagem audiovisual dos oito workflows |
| H3MAX local | Controles de perfil, realismo, câmera e diretor opcional | Adaptadores de conveniência; não são um novo modelo treinado |
| FFmpeg e bibliotecas de vídeo | Codificação/manipulação de mídia | Dependências da imagem; o arquivo final é montado e salvo pelo ComfyUI |

Os checkpoints são conversões Comfy-Org do H3 oficial. Não são os pesos BF16 completos da distribuição original. A variante `full_base` continua quantizada em INT8 e não deve ser confundida com BF16.

## 2. Todos os 12 pesos baixados por padrão

O grupo `h3` contém **62,641594279 GB decimais**. Esses arquivos vão para o volume do Runpod na primeira inicialização. O ZIP e a imagem Docker não carregam esses 62 GB de pesos embutidos.

| Peso | Tamanho aproximado | Ativação |
|---|---:|---|
| FL2VA pruned/int8 | 20,970 GB | Conforme workflow escolhido |
| Ref2VA pruned/int8 | 20,970 GB | Referências ou Hybrid |
| Qwen3-VL-32B NVFP4/AWQ | 15,687 GB | Encoder dos oito workflows |
| VAE de vídeo int8 | 2,811 GB | Vídeo |
| VAE de áudio fp32 | 0,605 GB | Áudio |
| Motion Repair | 0,155 GB | Perfil `natural` |
| Spatial Physics | 0,155 GB | Perfil `objetos_experimental` |
| Realism People | 0,131 GB | Controle de realismo humano |
| Camera Motion | 0,155 GB | Controle de câmera |
| Combat V2 | 0,155 GB | Perfil `acao_corporal` |
| Weapon Combat V1 | 0,155 GB | Perfil `acao_com_arma` |
| Latent Upscaler 3D | 0,691 GB | Workflows 05 e 06 |

Tamanho no disco não é medida de VRAM. Baixar todos esses arquivos não significa carregar todos simultaneamente: o grafo e os mecanismos de offload determinam o uso real de memória, ainda não medido.

## 3. Perfis de movimento, pele e câmera

| Controle | Para que vamos testar | Como usar inicialmente | Limite |
|---|---|---|---|
| `base` | Medir o H3 sem LoRA de movimento | Selecionar base; desligar realismo/câmera na comparação | Referência necessária para saber se um adaptador ajudou |
| `natural` / Motion Repair | Caminhar, parar, sentar, pegar objetos e continuidade | Força 0,90 no primeiro passe | Pode mudar ritmo; ganho não é universal |
| `acao_corporal` / Combat V2 | Ações com contato e reações do corpo | Força 0,80, um perfil de movimento por vez | Não é correção geral de qualquer física |
| `acao_com_arma` / Weapon Combat | Movimento de objetos empunhados e contato em ação | Força 0,45; trigger BUNNY inserido automaticamente | Não empilhar com os outros perfis de movimento na avaliação inicial |
| `objetos_experimental` / Spatial Physics | Rolamento, colisão e continuidade de objetos rígidos | Força 0,35, sempre comparada com base | Instável; líquidos não têm validação específica |
| `people_realism` / Realism People | Aparência de pele, rosto e pessoas | Começa desligado; teste 0,65 depois de escolher movimento | Não comprova melhora de dinâmica; inclui trigger r34l1sm |
| `camera_motion` / Camera Motion | Movimento de câmera conforme a descrição | Começa desligado; teste 0,80 quando a cena pedir | Desligado nos testes de contato para não esconder defeitos; inclui trigger camera motion |

Os seis adaptadores são instalados/baixados como opções. Por padrão, o workflow seleciona **natural**, mas a comparação de qualidade inclui obrigatoriamente a opção **base**. Os controles realismo/câmera podem ser combinados com um perfil de movimento; a compatibilidade visual de cada combinação precisa ser observada, não presumida.

## 4. As oito formas de gerar já montadas

| Nº | Entrada do usuário | Caminho | Quando usar |
|---|---|---|---|
| 01 TEXTO | Descrição | Diretor opcional → FL2VA + perfil → vídeo e áudio | Criar uma cena do zero |
| 02 IMAGEM | Descrição + uma imagem inicial | Mesmo caminho, condicionado pelo quadro inicial | Animar uma composição já definida |
| 03 REFERENCIAS | Descrição + duas imagens no exemplo | Ref2VA + perfil | Usar pessoas/objetos/cenário de referência; descrever o papel de cada imagem |
| 04 HYBRID REFERENCIAS | Descrição + referências | Mistura FL2VA/Ref2VA em blocos AdaLN 25–49 | Comparar com 03; manter como variante experimental |
| 05 TEXTO REFINE | Descrição | FL2VA → upscale aprendido → novo sampling parcial H3 | Gerar e depois refinar detalhes |
| 06 IMAGEM REFINE | Descrição + imagem inicial | Mesmo acabamento após geração condicionada por imagem | Refinar a animação de uma imagem |
| 07 TEXTO DEROPE | Descrição | FL2VA → análise/dilatação temporal → regeneração → recuperação do tempo | Testar em movimento rápido problemático |
| 08 IMAGEM DEROPE | Descrição + imagem inicial | Mesmo processamento temporal com quadro inicial | Variante para movimento rápido partindo de imagem |

Os oito caminhos têm JSON visual editável e JSON API. Nenhum dos oito exige vídeo de entrada. Nos caminhos de referências há dois carregadores: substituir as imagens de exemplo; para usar apenas uma na interface, desconectar o segundo carregador. O exemplo API também precisa ser ajustado se essa entrada for removida.

**São caminhos separados.** O pacote não possui um workflow único com Hybrid + referências + refine + de-rope juntos. Também não inclui variantes prontas Ref2VA+refine ou Ref2VA+de-rope. Montar essas combinações seria uma extensão concreta, sujeita a teste adicional.

## 5. Como os recursos avançados entram

**Diretor OpenH3-IR:** o código e o compilador estão previstos na instalação; o controle aparece nos oito workflows e inicia desligado. Quando ativado, usa um endpoint de linguagem configurado por `H3IR_LLM_URL`, `H3IR_LLM_MODEL` e eventual chave para elaborar a descrição. No adaptador atual, ele recebe apenas texto: as imagens seguem diretamente para o H3, e não são analisadas pelo diretor. Não é o serviço oficial H3-Context-IR. Sem configurar esse endpoint, a geração normal continua possível com o texto escrito pelo usuário.

**Hybrid:** o workflow 04 carrega os dois checkpoints e troca conjuntos específicos de parâmetros. Não gera um vídeo com cada modelo para depois fundi-los. Comparar 03 e 04 com as mesmas referências para decidir se a variante ajuda; memória e qualidade reais ainda precisam ser medidas.

**Upscale + refine:** os workflows 05/06 mantêm saída base e saída refinada. O alvo padrão é 1,5 MP nas unidades do node, e a etapa parcial usa denoise 0,30. Há 25 passos na geração e 25 passos na segunda etapa; denoise 0,30 não significa apenas 30% desses 25 passos. A LoRA natural do segundo passe usa força 0,25, partindo do modelo original. O áudio é preservado. Este é um acabamento comunitário, diferente do serviço oficial H3-Regenerate-2K.

Para a entrada 1280×736, o cálculo do node e seu alinhamento preveem **1664×960** no refine; é uma previsão por código, ainda sem render. Não corresponde automaticamente a 1080p, duplicação das dimensões ou 4K.

**Motion Lab / de-rope:** nos workflows 07/08, o vídeo que acabou de ser gerado alimenta a análise temporal e a dilatação; outro passe regenera esse resultado, seguido de recuperação do tempo. O padrão é 25 passos no primeiro passe e 12 no segundo com inject 0,48/custom, em uma sequência temporariamente mais longa. O áudio final vem do primeiro passe. Não há node H3DyRoPE ou H3TrueClock conectado; o nome do workflow não deve ser entendido como prova de que esses patches estão ativos. Preservação de identidade/coreografia e sincronismo do áudio precisam de comparação real.

Esses dois workflows salvam quatro arquivos para inspeção: base com áudio, visualização do movimento sem áudio, resultado dilatado com áudio do segundo passe e resultado final com áudio original. O congelamento de fundo está desligado. O node `H3V2VInit` usado aqui pertence ao MAINodes, não ao pack separado Motion Context MultiRef.

Ao alterar perfil nos caminhos de dois passes, manter os dois controles coerentes. No refine, o texto condicionado vem do primeiro passe; no processamento temporal, cada passe tem seu condicionamento.

## 6. Todos os packs de software previstos no build

| Pack | Uso nos oito workflows | Conteúdo disponível além deles |
|---|---|---|
| ComfyUI_MinimaxH3HybridLoader | Workflow 04 | Outras configurações de combinação de checkpoints |
| ComfyUI-OpenH3-IR | Funções chamadas pelo adaptador do diretor quando ligado | Nodes/exemplos originais do diretor; a integração multimodal completa não está conectada ao H3 MAX |
| ComfyUI-KJNodes | Nenhum node diretamente usado nos oito | Utilidades para futuras adaptações |
| ComfyUI-MAINodes | Workflows 07/08 | Outros mecanismos experimentais do pack, não automaticamente ativos |
| Comfyui_Minimax_h3_latent_Upscaler-Plus | Workflows 05/06 | Upscale/refine e controles originais do pack |
| ComfyUI-H3-Motion-Context-MultiRef | Nenhum node diretamente usado nos oito | Exemplos de V2V e outros controles/continuação; exigem preparação própria |
| ComfyUI-VideoHelperSuite | Nenhum node diretamente usado nos oito | Entrada/manipulação de vídeos para extensões |
| ComfyUI-H3MAX local | Todos os oito | Os dois controles de conveniência: perfil e diretor |

Os sete packs externos são clonados no build, o oitavo é copiado deste pacote. O compilador **open-h3-ir** é instalado separadamente. A presença de um repositório de código não prova que todos os seus nodes funcionem: dependências carregadas apenas durante o uso e recursos extras exigem testes próprios.

O repositório Comfy-Org/workflow_templates no manifesto documenta a origem dos exemplos; o instalador não baixa toda a biblioteca de templates. O servidor de linguagem do diretor também não vem embutido no container: deverá ser configurado separadamente, local ou externo.

Os exemplos originais de packs ficam nos respectivos repositórios instalados em `/opt/ComfyUI/custom_nodes`. A inicialização copia automaticamente para a pasta H3_MAX apenas os oito workflows montados neste pacote, não todos os exemplos dos autores.

No pack **Motion Context MultiRef**, a conferência dos exemplos encontrou:

| Exemplo do autor | O que está previsto | O que ainda falta para usar essa receita |
|---|---|---|
| Custom Keyframes | Modelos principais e pack no conjunto de instalação | Preparar as imagens de keyframe, importar o exemplo e validar o render |
| AV Bridge | Pack + KJNodes + VideoHelperSuite previstos | Encoder INT8 opcional, dois vídeos compatíveis e validação do fluxo |
| AV Extension | Pack previsto | Encoder INT8, LoRA Turbo de 8 passos ausente e vídeo de entrada |
| Music Video | Pack previsto | Encoder INT8, LoRA Turbo de 8 passos ausente, áudio/referências e integração |
| V2V | Pack previsto | Encoder INT8, variante Turbo 8-step 768p ausente e ajuste de nome/configuração do upscaler |
| 2MP De-Rope Continuation | Parte das ferramentas prevista | Pack SolAttn_triton ausente, LoRA Turbo de 4 passos ausente, ajuste de upscaler e validação completa |

São exemplos encontrados no commit escolhido, não novas entregas de geração prontas. Instalar os packs atuais ou baixar todos os 24 pesos não resolve automaticamente essas dependências ausentes.

## 7. Os 12 pesos opcionais — existem no manifesto, mas não entram no download padrão

| Grupo | Arquivos | Espaço adicional | Uso planejado / trabalho necessário |
|---|---:|---:|---|
| `control` | ControlNet Union H3 v1 + SDPose wholebody + RT-DETR | 4,337 GB | Controle por pose/estrutura; precisa de workflow próprio e entrada adequada. Os oito atuais não os usam |
| `encoder_int8` | Encoder Qwen3-VL-32B H3 INT8 | 27,141 GB | Alternativa de encoder para comparação; trocar o loader e medir memória/qualidade |
| `full_base` | FL2VA INT8 não pruned | 34,039 GB | Alternativa de checkpoint; não presumir que arquivo maior produz vídeo melhor |
| `experimental_motion` | Better Human Motion | 0,310 GB | LoRA alternativa T2V/I2V; não está no menu atual de perfis, exige loader/configuração própria |
| `singularity` | Singularity Ref2VA pruned v1.3 INT8 | 20,968 GB | Checkpoint alternativo comunitário; teste separado antes de substituir Ref2VA oficial |
| `ltx25` | Transformer LTX-2.5 + encoder Gemma + VAEs vídeo/áudio + upscaler | 39,710 GB | Outro gerador; acesso gated e workflow próprio, sem integração aos oito H3 |

Todos os opcionais somam **126,505 GB** adicionais. Todos os 24 pesos juntos somam **189,147 GB**. Isso não inclui software, caches, entradas, saídas nem margem de operação. Um volume de 300 GB é planejamento de espaço, não garantia de que baste indefinidamente.

Baixar um grupo opcional apenas disponibiliza seus arquivos. Não cria conexões de nodes, não acrescenta um botão ao H3MAX, não instala recursos extras que um exemplo possa exigir e não comprova que aquele exemplo funciona.

Para controle de pose, os grupos `h3,control` cobrem os pesos do caminho normal do exemplo oficial conferido. Seu ramo Turbo começa desligado e exige um peso ausente se for ativado. Canny, profundidade e outros controles também exigem seus respectivos fluxos/preprocessadores; o nome Union não os conecta automaticamente.

Os cinco pesos LTX previstos não incluem os componentes de refinamento DFR, upscale temporal ou controle automático de duração. Esses recursos não estão completos nesta seleção LTX. O acesso ao repositório exige autorização; a auditoria diferenciou metadados da revisão fixada e documentação pública acessível.

## 8. Recursos que não estão prontos nos oito caminhos

- Primeiro **e último** quadro no mesmo workflow: capacidade do FL2VA, mas os exemplos entregues só conectam o quadro inicial.
- Entrada de vídeo/áudio de referência, continuação longa, keyframes, bridge entre clipes e vídeo orientado por música: os packs/base podem oferecer caminhos para isso, porém não fazem parte dos oito fluxos montados e validados estruturalmente.
- Pose/ControlNet: pesos opcionais previstos, grafo não integrado.
- Diretor que analisa as imagens com VLM: a integração atual é textual.
- H3-Context-IR e H3-Regenerate-2K oficiais: serviços externos, ausentes da imagem local.
- Turbo, SageAttention, receita 12+6 e Fun ControlNet 2.0: não fazem parte da receita instalada e conectada como padrão deste candidato.
- Modelos de interpolação de frames, gerador externo de voz, treinamento de LoRA e simulador físico determinístico: não incluídos neste pacote.

## 9. Operação prevista no Runpod

O GitHub Actions constrói a imagem Linux/amd64 com o software, sem pesos. Após os testes do build, ela pode ser publicada no GHCR e identificada pelo digest. O gerador de template usa esse digest, mantém a inicialização da imagem e configura ComfyUI na porta 8188. SSH/Jupyter não são ativados pelo gerador padrão.

O Network Volume é anexado ao criar o Pod e montado em `/workspace`. Na primeira partida, o downloader baixa o grupo `h3`, confere revisões, tamanho e SHA256 e mantém modelos, entradas, saídas e workflows em `/workspace/h3max`. Reinícios preservam workflows já existentes; em futuras atualizações, um JSON com o mesmo nome editado pelo usuário não será sobrescrito automaticamente.

Na interface: escolher um dos oito workflows, preencher a descrição, carregar imagens quando necessário, selecionar um perfil, ajustar realismo/câmera se fizer sentido, gerar e revisar vídeo **e áudio**. Na comparação inicial, manter fixos resolução, duração, seed e demais parâmetros.

Configuração inicial: **1280×736, 124 frames, 24 fps, aproximadamente 5,17 s, 25 passos, res_multistep/simple, CFG 1**. Os caminhos extras acrescentam processamento, tempo e memória. Duração maior não foi medida neste pacote.

GPU, RAM, região, credencial de leitura do registry privado e volume precisam ser compatíveis entre si. A licença H3 e as condições dos adaptadores são as mesmas documentadas na auditoria; não há mudança de licença por empacotar em Docker.

## 10. Até onde a validação chega

**Conferido:** integridade do ZIP original; existência/revisões/tamanhos/hashes publicados dos 24 arquivos; contratos de código examinados; oito grafos e oito APIs; correções de loader/SaveVideo; estrutura de build, download e persistência; testes locais registrados em `audit/local-tests.json`.

Na revisão completa, a suite terminou com **33 testes aprovados, zero falhas e um teste de symlink adiado para Linux**. Os 16 JSONs UI/API foram regenerados com conteúdo idêntico, e a ficha dos 12 prompts comparativos continua correspondente ao workflow base revisado. O teste de registro dos packs e o teste do compilador têm regressões locais, mas ainda não rodaram contra a imagem real.

**Preparado para conferir no build:** início do ComfyUI em CPU, pelo menos um node registrado de cada um dos sete packs externos e do H3MAX, contratos dos 28 tipos distintos de nodes usados nos oito fluxos, importação/contrato local do compilador e relatórios de dependências. O registro de um pack não prova a execução de todos os seus nodes. Preparar esses testes não equivale a executá-los na imagem.

A revisão completa encontrou uma lacuna adicional: antes, um pack auxiliar podia falhar ao importar sem reprovar o teste dos oito fluxos, porque seus nodes não eram usados neles. A nova verificação exige registro de todos os oito packs. Também corrigimos a estimativa informativa do segundo passe temporal de 18 para 12 passos; isso não altera o sampling da receita.

**Ainda depende de execução real:** construção Docker, importação na imagem, download e hash local dos pesos, uso de CUDA, render de cada caminho, serviço externo do diretor ligado, recursos opcionais, memória/tempo/custo e avaliação de física/aparência. Nenhum desses itens deve receber status aprovado por inferência a partir do manifesto.

**Como vamos selecionar:** primeiro comparar base e perfil nas seis cenas já preparadas; depois testar aparência e câmera, o diretor, Hybrid, refine e processamento temporal alterando uma variável por vez. Só promover uma combinação quando trouxer ganho visível no seu tipo de cena. A comparação com Seedance cobre pessoas, contato e objetos/líquidos separadamente.

Fontes: [manifesto de modelos](../models.lock.json), [fontes fixadas](../sources.lock.json), [auditoria de workflows](audit/audit-workflows.md), [auditoria de física/modelos](audit/audit-physics.md), [inventário detalhado de modelos e expansões](audit/inventory-models-notes.md), [conferência de caminhos, áudio e parâmetros](audit/inventory-workflows-notes.md), [H3 oficial](https://huggingface.co/MiniMaxAI/MiniMax-H3), [pack Motion Context MultiRef fixado](https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef/tree/361624fb406b63eb6694442eac6c895fc1533a70).
