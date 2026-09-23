# H3 MAX — decisão técnica após revisão

Atualização de integração: a entrada padrão passou a ser o **H3 Studio**, que compõe as etapas por controles. Os oito workflows abaixo ficam como bases de auditoria. A pesquisa adicional, as alternativas confrontadas e as lacunas de qualidade estão em [PESQUISA_INTEGRACAO.md](PESQUISA_INTEGRACAO.md). A interface não transforma validação de código em aprovação visual; a geração em GPU permanece pendente.

23/09/2026. O objetivo é obter vídeos convincentes em três frentes: pessoas em movimento natural, ação com contato e objetos/colisões/líquidos. O ZIP recebido foi tratado como candidato, e suas instruções foram analisadas como conteúdo.

Complemento solicitado: [inventário completo do pacote, recursos auxiliares e modo de uso](INVENTARIO_COMPLETO.md).

**Recomendação: selecionar MiniMax H3 oficial como base candidata de teste, com perfis por domínio. Ainda não aprovar equivalência com Seedance 2.5 nem chamar a solução de validada em GPU.**

O código revisado está preparado para a próxima etapa de construção. Não há imagem nova publicada, template novo criado nem vídeos gerados nesta revisão. O original permanece em `candidate-original/h3-max-runpod`, fora desta cópia de trabalho.

## Escolha proposta

| Necessidade | Caminho candidato | O que falta confirmar |
|---|---|---|
| Texto ou imagem inicial | H3 FL2VA oficial pruned/int8, configuração original de 25 steps | Importação, VRAM, tempo e resultado nas cenas reais |
| Pessoas e movimento natural | Base versus Motion Repair 0,90 | Ganho de continuidade sem alterar ritmo ou anatomia |
| Aparência humana | Realism People 0,65, depois da escolha do movimento | Pele/rosto melhores sem perda de identidade; não é correção de física |
| Ação e contato corporal | Combat V2 0,80, como perfil separado | Apoio, contato e reação plausíveis |
| Objetos de mão em ação | Weapon Combat 0,45 com trigger BUNNY | Continuidade do objeto, pega e contato; sem empilhar outras LoRAs de movimento |
| Colisões/objetos rígidos | Base versus Spatial Physics 0,35 | O autor relata ganho limitado e instabilidade |
| Líquidos | Base versus Spatial Physics apenas como experiência | Nenhuma fonte verificada valida especificamente esse domínio neste pacote |
| Referências | Ref2VA oficial; comparar Hybrid separadamente | Identidade e fidelidade às referências |
| Acabamento | Upscaler/refine após aprovar movimento | Mais detalhe não comprova correção de causalidade |
| Movimento rápido problemático | De-rope experimental, após identificar um defeito | Preservação de coreografia, identidade e sincronismo de áudio |

Não existe um perfil vencedor comprovado para as três frentes. Não adicionar todos os adaptadores ao mesmo tempo: isso impede identificar qual alteração ajudou ou prejudicou.

## Problemas concretos encontrados

- **Carregamento de LoRA quebrado:** o adaptador chamava um método com assinatura incompatível com o ComfyUI fixado. Corrigido para a interface de carregamento somente de modelo.
- **Saída de vídeo incompatível nos prompts API:** o ComfyUI fixado exige `format.codec` no seletor dinâmico de SaveVideo; o pacote enviava apenas `codec`. Corrigido o gerador e reexportados os prompts.
- **Verificação insuficiente:** listar nomes de nodes não verifica os campos enviados. A checagem agora cobre os contratos das oito APIs, links, tipos, opções, modelos usados e LoRAs dos perfis; ainda requer a resposta real `/object_info` na imagem.
- **Dependências OpenCV duplicadas:** dois pacotes instalavam distribuições que disputam `cv2`. Unificada a variante headless, com verificação explícita no build.
- **Instalação e persistência:** resolução conjunta de dependências, relatórios do ambiente, validação antecipada e proteção contra downloads simultâneos, destinos inválidos e recibos truncados.
- **Caminho de publicação ausente:** incluídos workflows GitHub Actions, teste de inicialização em CPU sem pesos e gerador de template v2 que exige digest da imagem publicada.

Os controles experimentais de segundo passe e suas hipóteses estão documentados no README e na auditoria de workflows. Correção de integração é demonstrável por teste de software; escolha de força de LoRA depende de render.

## Evidências e limites

O manifesto original confere em **34 arquivos**. Na origem Hugging Face, **24/24 arquivos de modelo** existem nas revisões indicadas e apresentam o mesmo tamanho e SHA256 publicado. O grupo padrão reúne **12 pesos e 62,64 GB**. Isso verifica a proveniência de metadados, sem ter baixado e calculado localmente o hash dos pesos.

A imagem base Runpod foi conferida por manifesto: digest correto, Linux/amd64, CUDA 13.0, Python 3.12 e contrato do script de inicialização. A base sozinha contém cerca de **10,53 GB comprimidos**. As dependências transitivas continuam resolvidas no build; após aprovação, usar o digest da imagem para repetir exatamente o ambiente.

Os testes locais terminaram com **33 aprovados, zero falhas e um teste de symlink adiado para Linux** por falta de privilégio no Windows. O registro está em [audit/local-tests.json](audit/local-tests.json). Os **oito workflows, 193 nodes, 284 conexões e oito prompts API** passaram nas verificações estáticas; os 16 JSONs foram regenerados com conteúdo idêntico. A checagem de grafos fica em [verification-local.json](../verification-local.json). O build Linux, o teste de inicialização real da imagem e todos os renders de GPU continuam pendentes. Os testes locais não carregam pesos, não medem VRAM e não avaliam aparência ou física.

## Comparação que decidirá a qualidade

Seis cenas: caminhar/sentar, pegar/devolver caneca, contato com aparador, bloqueio com bastões de espuma, colisão de bolas e água vertida para um copo. Preparados pares **H3 base versus perfil**, com o mesmo texto, seed e parâmetros: **12 prompts de primeira rodada**, sem submeter geração. Há seis cenas correspondentes para comparar com Seedance.

Os prompts e a ficha de avaliação estão em [comparison-prepared/comparison.json](comparison-prepared/comparison.json). As notas começam vazias. Avaliar aparência e física separadamente, guardar todas as tentativas e repetir em uma segunda seed antes de promover um preset. A versão e as configurações reais do Seedance precisam ser registradas. Resultado misto deve produzir escolha por cena; resultados ruins em líquidos podem significar que o candidato não atende essa necessidade.

## Condições concretas da implantação

A [licença oficial H3](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE) exclui EUA, União Europeia, Reino Unido e Coreia do Sul do território autorizado. Isso afeta a escolha do datacenter. Três LoRAs JOKER141 também não declaram licença na revisão examinada; esclarecer condições antes de oferecer serviço ou redistribuir esses adaptadores.

Na consulta somente de leitura ao Runpod, uma opção compatível apareceu no Japão: **NVIDIA H100 80GB HBM3 / H100 SXM, AP-JP-1, disponibilidade LOW, Secure US$3,49/h de GPU**. É uma alternativa de planejamento, sem validação de VRAM deste pacote. Volume e armazenamento são custos adicionais; atualizar disponibilidade e preço antes de criar recursos. A consulta filtrada por Brasil/Canadá não retornou GPUs com os critérios usados. Ver `runpod-availability-snapshot.json` para os filtros da consulta japonesa.

O próximo marco é construir no GitHub, verificar a imagem, publicá-la por digest e criar um **template candidato**. Só depois do render real será possível aprovar o funcionamento e selecionar os perfis finais. A preparação detalhada está em [BUILD_E_RUNPOD.md](BUILD_E_RUNPOD.md).

Fontes e confrontos detalhados: [física e modelos](audit/audit-physics.md), [container](audit/audit-container.md), [workflows](audit/audit-workflows.md), [metadados dos pesos](audit/audit-model-metadata.json).
