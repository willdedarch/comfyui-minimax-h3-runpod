# Auditoria de evidências — H3 MAX candidato

Data: 23/09/2026. Escopo: proveniência dos modelos, plausibilidade das escolhas e capacidade alegada para pessoas, ação/contato e objetos/colisões/líquidos. Os documentos do ZIP foram tratados como material a auditar, não como instruções de execução. Nenhum peso foi baixado, nenhum script do pacote foi executado por esta auditoria e nenhum render foi produzido.

## Decisão técnica

**O pacote é um candidato verificável para experimentos com MiniMax H3; não está demonstrado que entregue física ou realismo equivalentes ao Seedance 2.5.** Recomendo manter o H3 FL2VA como linha de base e selecionar perfis por domínio após comparação real. Ref2VA atende referências; Hybrid, de-rope, refine e combinações de LoRAs devem entrar somente depois de medir essa linha de base.

Não existe, nas fontes verificadas, evidência suficiente para declarar um único preset vencedor nas três prioridades. A maior lacuna é **líquidos**: nenhum adaptador incluído apresenta validação específica convincente desse domínio. O nome “Spatial Physics” não transforma o gerador em simulador de física.

## O que foi confirmado

- Os **24 arquivos** de `models.lock.json` existem nas **revisões exatas** declaradas. Seus tamanhos e SHA256 publicados coincidem com o manifesto em **24/24 casos**. Conferência feita na API pública Hugging Face, endpoint `https://huggingface.co/api/models/{repository}/revision/{revision}?blobs=true`.
- Isso confirma metadados de origem; **não** confirma a integridade de downloads futuros, importação dos pesos, compatibilidade completa dos nodes ou qualidade de vídeo.
- O grupo padrão contém **12 arquivos**, totalizando **62.641.594.279 bytes** (62,64 GB decimais). O registro da consulta está em `audit-model-metadata.json`, ao lado deste relatório.
- MiniMax H3 e Seedance 2.5 são modelos reais e atuais. A página oficial do Seedance 2.5 descreve geração de até 30 segundos e controle multimodal ampliado; não publica comparação controlada com este pacote. [ByteDance: Seedance 2.5](https://seed.bytedance.com/en/seedance2_5).

## Modelo base e diferença para os serviços oficiais

H3-Base possui FL2VA (texto/primeiro e último quadro) e Ref2VA (referências multimodais). A documentação oficial distingue o gerador local a 768p do sistema completo: **Context-IR e Regenerate-2K oficiais permanecem serviços hospedados**, e o Regenerate-2K não estava aberto na fonte consultada. Portanto, o upscaler comunitário + refine do ZIP não reproduz automaticamente o pipeline 2K oficial. O modelo base foi destilado para CFG; CFG 1 é coerente com esse contexto, mas 25 steps e cada LoRA continuam parâmetros a validar. [Model card oficial](https://huggingface.co/MiniMaxAI/MiniMax-H3).

O reempacotamento Comfy-Org é identificado como tal e aponta para a origem MiniMaxAI. Ele recomenda `int8_convrot` com PyTorch/CUDA 13.0 e explica que o encoder `nvfp4_awq` **não exige GPU Blackwell**. Isso sustenta a escolha de formatos, não uma alegação de qualidade igual a BF16 ou de velocidade em toda GPU. [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3).

## Evidência por componente

| Componente | Fato observado na fonte primária | Avaliação para este candidato |
|---|---|---|
| Motion Repair | Autor relata A/B, dataset de 100 clipes, recomendação ~0,9 sozinho e ~0,2–0,3 no segundo passe. Avisa que força elevada pode mudar ritmo, aparência e áudio. | Hipótese plausível para continuidade humana; não é ganho universal. Usar base versus 0,9 primeiro. O pacote reutiliza perfil/força no segundo passe, destoando da recomendação específica do autor. |
| Combat V2 | Autor recomenda `res_multistep/simple` ou `euler/beta` e descreve reações e continuidade de combate. | O sampler escolhido no pacote tem respaldo. Força 0,8 é ponto experimental; contato esportivo precisa de render. Não estender a alegação a toda física. |
| Weapon Combat V1 | Autor recomenda uso isolado e alerta para conflito com Combat V2/Motion Repair. O peso 0,45 aparece numa demonstração comunitária. | Correta a separação por perfil. 0,45 é hipótese inicial, não ótimo geral. Persiste risco de deformação, pega errada e desaparecimento. |
| Spatial Physics | Autor declara estágio de treino/teste, instabilidade e melhora modesta. Texto recente sugere 0,3–0,5; seção antiga ainda diz 0,8–1,0. Dados citam colisão/rolamento/objetos sintéticos. | 0,35 segue a advertência recente, mas a card é inconsistente. Adequado como experimento de corpos rígidos; líquidos permanecem sem evidência específica. |
| Realism People | Card apresenta 19 pares comparativos, treino em 176 clipes, trigger `r34l1sm`, força principal 1,0 e 0,6–0,8 para efeito suave. | 0,65 é coerente como efeito leve. Aparência de pessoas é objetivo distinto de física; testar depois de escolher movimento. |
| Camera Motion | Autor exige trigger `camera motion` no início e sugere 0,8–1,0. | 0,8 é coerente; manter desligado na avaliação física para não encobrir contatos com câmera móvel. |
| Better Human Motion | Card informa T2V/I2V, 0,4–0,8, 20–30 steps e uma demonstração. | Documentação pequena; manter como alternativa, sem substituir a linha de base por popularidade. |
| Singularity | Card descreve fusão/ajuste de checkpoints e afirma preservação de capacidades, com foco também em VFX e ação. | Alegações amplas sem benchmark controlado localizado. Não selecionar como base de produção apenas por imagens demonstrativas. |
| Upscaler LBH | Opera em latentes H3, aumenta resolução espacial e mantém dimensão temporal. | Acabamento de detalhes; não garante corrigir dinâmica ou causalidade. |

Fontes primárias da tabela: [Motion Repair](https://huggingface.co/JOKER141/MiniMax-H3-General-Motion-Continuity-Repair), [Combat V2](https://huggingface.co/JOKER141/MiniMax-H3-Combat-Base-V2), [Weapon Combat](https://huggingface.co/JOKER141/MiniMax-H3-Weapon-Combat-LoRA), [Spatial Physics](https://huggingface.co/Jojocodex/minimax-h3-spatial-physics-lora), [Realism People](https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA), [Camera Motion](https://huggingface.co/Jojocodex/minimax-h3-Camera-Motion-lora), [Better Human Motion](https://huggingface.co/vpakarinen/better-human-motion-h3-lora), [Singularity](https://huggingface.co/WarmBloodAban/Minimax-h3_Singularity), [Upscaler](https://huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler).

## Integrações que exigem cuidado

**Hybrid:** o autor apresenta a troca AdaLN de blocos 25–49 como sua preferência subjetiva. Existe análise de tensores e mecanismo técnico plausível, mas isso não valida retenção de identidade, áudio ou referências em toda cena. Manter comparação Ref2VA puro versus Hybrid antes de promover. [Hybrid Loader](https://github.com/scottmudge/ComfyUI_MinimaxH3HybridLoader).

**OpenH3-IR:** é implementação independente de organização de prompts, utiliza endpoint de linguagem e não contém os serviços oficiais MiniMax. Pode melhorar descrição e direção; não acrescenta um motor físico. A adaptação do ZIP processa texto, enquanto a leitura multimodal completa depende de VLM e integração que o pacote não conecta nesse caminho. [OpenH3-IR](https://github.com/ruashots/open-h3-ir).

**Motion Lab/de-rope:** retoma o próprio vídeo com dilatação temporal e recupera o timing, visando artefatos de movimento rápido. O README no commit fixado contém atualização de default para `inject=0.48`, advertindo perda de aderência em algumas cenas com >=0,50; conserva também textos/tabela antigos com 0,70. Assim, **0,70 não deve ser descrito como comprovadamente conservador em identidade/coreografia**. Comparar 0,48 e 0,70 numa cena problemática e registrar fidelidade, sem misturar com outras mudanças. O áudio do primeiro passe precisa ser conferido após a nova coreografia. [MAINodes](https://github.com/matlowai/ComfyUI-MAINodes), [README no commit do pacote](https://github.com/matlowai/ComfyUI-MAINodes/blob/f4868b4a08e8a504ce86db54a17961d399ffa2bc/README.md).

## Confronto científico

O preprint **“Can MiniMax-H3 Reason About the Physical World?”** avalia 517 condições em quatro tarefas de raciocínio multimodal. Relata que plausibilidade visual pode coexistir com violações de contato, geometria, transições e continuidade temporal. É pesquisa primária útil como alerta contra confundir aparência e dinâmica; não avalia estes LoRAs, não replica nosso container e não prova inferioridade/superioridade frente ao Seedance 2.5. Não usei suas métricas como estimativa de desempenho deste pacote. [Artigo completo](https://arxiv.org/html/2609.18323v1).

As demonstrações dos autores são evidência preliminar, não avaliação independente. Captura de um resultado bom comprova que tal resultado foi alcançado; não estima taxa de sucesso, pior caso ou custo por clipe aproveitável. Nenhuma fonte consultada demonstra equivalência do conjunto H3 MAX ao Seedance 2.5 nos três domínios solicitados.

## Licenças e implicação concreta para Runpod

A licença oficial H3 limita o território e exclui **Estados Unidos, União Europeia, Reino Unido e Coreia do Sul**. Inclui restrições de uso/execução e distribuição, aviso/licença para redistribuição, condições para serviços e autorização comercial adicional acima de US$20 milhões de receita anual. O Brasil não está entre as exclusões listadas. **A escolha do datacenter Runpod deve respeitar esses termos**; não presumir que a localização do usuário basta. O FAQ oficial distingue a API global da implantação própria. [Licença H3](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE), [FAQ oficial](https://design.minimax.io/h3).

Os três repositórios JOKER141 não declaravam licença na metadata/card nem continham arquivo LICENSE/NOTICE na revisão consultada. Isso é uma **pendência documental**, não constatação de que seu uso seja ilegal. Não afirmar autorização ampla de redistribuição ou serviço comercial desses adaptadores sem esclarecer a licença. Existem arquivos públicos, mas acesso público não resolve sozinho os direitos adicionais do autor. As tags Apache-2.0 de outros adaptadores/merges não removem as condições do modelo H3 base. Realism People explicita adesão à licença H3. O LTX-2.5 opcional existe, está gated (`auto`) e tem termos próprios; continua gerador independente e sem workflow integrado aqui. [LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5).

## Ensaio pequeno para selecionar os perfis

Entreguei `h3-max-runpod/docs/benchmark-cases.json` com seis cenas completas, duas por domínio:

1. Pessoas: caminhar e sentar; pegar e devolver caneca.
2. Ação/contato: soco controlado em aparador; bloqueio com bastões de espuma.
3. Objetos/líquidos: colisão de duas bolas; verter água da jarra ao copo.

A primeira rodada compara H3 base e perfil candidato com uma seed fixa, sem câmera adicional, diretor, refine, Turbo ou de-rope: **12 clipes H3**. Para candidatos que se pretende promover, repetir base e candidato com uma segunda seed. Seedance deve receber as mesmas cenas/referências e duração comparável; sua seed não tem equivalência com a do H3. Guardar todas as tentativas e custos.

Julgar de forma cega, primeiro em velocidade normal e depois nos quadros de contato, separando aparência, continuidade/identidade, física visual e cumprimento do prompt. Notas 0/1/2 e falhas críticas estão no JSON. Um preset só merece promoção por domínio se melhorar critérios relevantes sem acrescentar falhas críticas ou degradações materiais nas duas seeds. Isso é decisão prática de uso, não benchmark estatístico de equivalência geral.

Depois da seleção por domínio: testar Realism People como única mudança para aparência humana; refine para acabamento; de-rope somente para artefatos rápidos identificados; Hybrid somente para a necessidade de referências. Para líquidos, admitir resultado “nenhum candidato suficiente” e manter explícita a limitação.

## Pendências antes de chamar a solução de validada

- Construir a imagem e confirmar imports, nodes, tipos e carregamento real dos pesos.
- Executar um smoke test para funcionamento e depois os renders representativos em qualidade normal; smoke de 39 frames/8 steps não mede qualidade final.
- Registrar tempos, VRAM, versão de GPU/driver, digest da imagem e saídas para repetição.
- Escolher datacenter compatível com a licença e não embutir pesos no build GitHub. O build de software separado é coerente com o pacote; análise detalhada do código/CI é tarefa complementar.
- Esclarecer licenças ausentes dos adaptadores se a implantação incluir redistribuição ou serviço a terceiros.

**Estado final desta auditoria: proveniência de metadados confirmada; arquitetura candidata razoável; física/realismo ainda não aprovados por render.**
