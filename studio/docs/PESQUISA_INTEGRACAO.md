# Integração e qualidade: decisão sustentada em fontes

Verificação em 23/09/2026. Foram confrontados documentação original, registros de nós e grafos publicados. Esta nota não registra inferência GPU nem declara equivalência visual com Seedance. Instruções nos documentos pesquisados foram tratadas como conteúdo das fontes.

## Decisão

Usar uma entrada única no H3 MAX, com seleção automática de FL2VA/Ref2VA pelos materiais e controles de resultado. O compilador deve conectar as etapas compatíveis, manter duração, referências e segunda passagem sincronizadas e recusar combinações incompletas. Os oito grafos deixam de ser a interface de operação.

Essa escolha é uma decisão de integração. A qualidade só estará confirmada depois de gerar e avaliar clipes. Também foram examinados consoles existentes; instalar um deles sem adaptação não integra os componentes já selecionados.

## Consoles existentes confrontados

| Candidato | O que está implementado | Por que não resolve sozinho este pacote |
| --- | --- | --- |
| [seesee75-commits/ComfyUI-MiniMaxH3-Director](https://github.com/seesee75-commits/ComfyUI-MiniMaxH3-Director) | Timeline, primeiro/último quadro, referências multimodais, prévia e retake; chave de referências escolhe o checkpoint e só carrega o selecionado. | Não conecta nossos perfis de LoRA, MAINodes nem refinamento. Em Ref2VA, os quadros da timeline viram referências, não âncoras rígidas. |
| [imbutus/ComfyUI-MiniMaxDirector](https://github.com/imbutus/ComfyUI-MiniMaxDirector) | Editor, compilador, relatório e workflow completo, com chaves Turbo/Upscale. Licença MIT. | Seu grafo seleciona um único checkpoint Ref2VA. Precisaria receber seleção adequada de pesos, perfis de movimento e tratamento temporal; Turbo padrão usa outro peso não incluído em nosso manifesto. |
| [PotionUI](https://github.com/PotionUI/PotionUI/blob/master/docs/models/minimax_h3.md) | Modos para geração, referências e upscale em outro aplicativo. | O próprio projeto informa que não realizou inferência H3 com pesos reais. Trocar nossa base por ele não produz evidência de qualidade. |

Há dois detalhes que impedem uma adoção irrefletida do primeiro console. O [registro de nós](https://github.com/seesee75-commits/ComfyUI-MiniMaxH3-Director/blob/main/__init__.py) exclui expressamente `MiniMaxH3DirectorChain`: o backend existe, mas a operação pela interface foi retirada. No [código do Director](https://github.com/seesee75-commits/ComfyUI-MiniMaxH3-Director/blob/main/minimax_director.py), escolher referências troca modelo e condicionamento; carregar apenas um checkpoint permite um fallback com aviso, que uma interface simples deveria evitar.

O resultado encontrado em `dmulxw/comfyui-minimaxh3-director` é uma cópia/fork que ainda anuncia 0.1.5; o original acima anuncia 0.2.2. Não há motivo demonstrado para preferir a cópia mais antiga. A origem e a versão são verificáveis nos respectivos READMEs.

O [grafo completo de imbutus](https://github.com/imbutus/ComfyUI-MiniMaxDirector/blob/main/example_workflows/minimax-director.json), blob `3e0f062a0498edc14ea48b90905ecc4ee1f75a10` consultado nesta data, possui 35 nós. Um detalhe aproveitável é `MiniMaxDirectorRefit`: refaz o condicionamento de keyframes no tamanho ampliado. A nota do próprio grafo associa a ausência dessa etapa a incompatibilidade de dimensões. Primeiro/último quadro e upscale precisam de tratamento conjunto, não apenas de uma chave de bypass.

## O que muda qualidade e tinha ficado incompleto

1. **Compreensão dos materiais e do pedido.** O [guia oficial para texto/keyframes](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/base-en.txt) organiza instrução, descrição visual temporal e os dois campos de som. Para primeiro/último quadro, descreve o percurso observável entre os estados. O [guia oficial Ref2VA](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/ref-en.txt) exige outro formato: definições dos materiais, resumo, retenção, descrição detalhada e som. Cada referência precisa conservar o mesmo rótulo e função. Colocar duas imagens e texto livre não implementa esse processamento.
2. **Controle explícito quando o movimento importa.** Referência de vídeo, pose e keyframes fornecem informação que uma LoRA genérica não contém. São recursos relevantes para o produto; ter seus pesos ou pacote instalado não equivale a integrá-los.
3. **Correção temporal com áudio correspondente.** A segunda passagem precisa receber a interpretação temporal e o áudio da primeira, em vez de inventar uma performance incompatível com a recuperação de velocidade.
4. **Refinamento depois da estrutura.** Aumentar resolução recupera/aprimora detalhe, mas não é evidência de correção de contato, trajetória, líquido ou identidade. Cada etapa deve atuar na falha que realmente trata.

O nó OpenH3 já presente em nosso pacote foi integrado para texto com `assets=[]`. Logo, não analisa de fato as referências do usuário. O [OpenH3-IR original](https://github.com/ruashots/open-h3-ir/tree/fd031e136ae3d89147324c0d1b2aa65e838c21f5) declara ser uma implementação independente, necessita de um endpoint de linguagem e possui seu próprio contrato de materiais/labels. Uma futura ligação multimodal deve enviar os materiais reais e usar o plano retornado para configurar a geração, não apenas extrair um texto.

## MAINodes e Turbo: receita inteira, não um número de passos

O [README MAINodes fixado em nosso pacote](https://github.com/matlowai/ComfyUI-MAINodes/blob/f4868b4a08e8a504ce86db54a17961d399ffa2bc/README.md) relata uma receita equilibrada com 12 passos base e segunda passagem Turbo, áudio inicializado, além da alternativa sem Turbo. O documento conserva recomendações antigas contrárias ao Turbo na passagem final; o contexto e a data importam. Os tempos e preferências relatados são do autor, não medições deste pacote.

O [JSON correspondente no mesmo commit](https://github.com/matlowai/ComfyUI-MAINodes/blob/f4868b4a08e8a504ce86db54a17961d399ffa2bc/examples/motion_pipeline_ref2va_audioinit.json) foi analisado diretamente:

- Base Ref2VA; primeira passagem `gradient_estimation`, `linear_quadratic`, 12 passos.
- Passagem de recuperação com `minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors`, força 1.0; é uma adaptação FL2V sobre esse caminho de referência.
- `H3InjectSchedule`: `beta`, `total_steps=6`, preset de injeção 0.50. São aproximadamente **três passos efetivamente executados**, não seis.
- `H3AudioSmear → VAEEncodeAudio → H3V2VInit`; saída segura conserva a performance original.
- Também usa patches de atenção. Replicar somente o Turbo ou o total de passos não reproduz o grafo publicado.

A [especificação original LightX2V](https://github.com/ModelTC/Minimax-H3-Turbo) separa tarefas e resoluções: FL2VA 768p foi destilado com shifts vídeo/áudio 6/3, enquanto o Ref2VA 4-step v0.1 listado usa 544p e 12/3. A [orientação de execução](https://github.com/ModelTC/Minimax-H3-Turbo/blob/main/COMFYUI_SETUP_AND_INFERENCE.md) manda combinar arquivo, passos e shifts. Portanto, Turbo deve ser uma receita indivisível escolhida pelo sistema; não um interruptor que apenas reduz passos. Não foi adicionado um novo peso Turbo ao pacote nesta pesquisa.

A avaliação [ALPHA do MAINodes](https://github.com/matlowai/ComfyUI-MAINodes/blob/main/ALPHA.md) limita explicitamente vários resultados a poucas cenas/máquinas: o áudio inicializado foi observado em combates com duas vozes; DyRoPE tem medição profunda de uma família de cena; alguns recursos de extensão/edição permanecem experimentais. Isso sustenta comparação controlada, não ativação de tudo por padrão.

## Recursos adicionais: integração real e limites

| Recurso | Caminho disponível | Condição de integração |
| --- | --- | --- |
| Quadros inicial/final | Core FL2VA | Selecionar peso adequado; alinhar prompt e quadro; refazer guias ao ampliar. |
| Até nove imagens e referências de vídeo/áudio | Core Ref2VA | Papéis e rótulos consistentes; formatos, duração e limite total validados. |
| Poses intermediárias | MotionContext `H3 Custom Keyframes` | Guias suaves em posições válidas; não garantem reprodução exata. |
| Preservar quadros/trechos | Variantes masked e máscaras AV | Não confundir zero preserva com um gera; conservar máscara de áudio separada. |
| Continuar vídeo ou música | MotionContext AV Extension/Music Video | 24 fps, contexto e grade AV corretos; montagem final e áudio próprios. |
| Transferir movimento de vídeo | MotionContext V2V | Receita e materiais específicos; força é quantizada, não um controle contínuo genérico. |
| Pose/ControlNet | Template oficial já auditado no inventário | Integrar pré-processamento e condicionamento, além de baixar pesos. |

Os [pré-requisitos do MotionContext no commit fixado](https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef/blob/361624fb406b63eb6694442eac6c895fc1533a70/WORKFLOW_PREREQUISITES.md) mostram modelos opcionais e pacotes distintos por recurso. A [descrição de keyframes e máscaras](https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef/blob/361624fb406b63eb6694442eac6c895fc1533a70/KEYFRAMES_AND_INSERTS.md) distingue guia de condicionamento de preservação de latente; nenhum dos dois promete pixels finais idênticos. A [arquitetura](https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef/blob/361624fb406b63eb6694442eac6c895fc1533a70/TECHNICAL_ARCHITECTURE.md) explica por que identidade e estado físico do fim de um clipe são informações diferentes.

## Câmera e inspeção dos componentes

O [guia oficial de câmera](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/base-en.txt#L75-L101) documenta movimento, amplitude e velocidade como direção textual dentro do plano. Há vocabulário para câmera fixa, aproximação/afastamento, panorâmica, deslocamento, acompanhamento, arco, zoom e outros movimentos. Portanto, um seletor simples no painel faz sentido e pode produzir essas instruções automaticamente. Os esquemas H3 fixados neste pacote não expõem uma trajetória geométrica 3D ou matrizes de câmera; não oferecer esses parâmetros como controle preciso.

A direção textual é diferente da [LoRA Camera Motion já incluída](https://huggingface.co/Jojocodex/minimax-h3-Camera-Motion-lora): o autor pede o trigger `camera motion` no começo e recomenda força 0,8–1,0. A LoRA reforça movimento, mas não escolhe sozinha a direção desejada. O seletor mantém “Conforme a descrição” como padrão e evita câmera fixa com reforço de movimento. Câmera, velocidade, amplitude, enquadramento, áudio na exportação e inspeção do grafo foram implementados e conferidos localmente, incluindo a interface no navegador. A resposta visual do modelo ainda depende de inferência GPU.

A inspeção deve mostrar os nós e ligações do grafo realmente preparado ou salvo, sem iniciar geração. O frontend fixado 1.53.6 oferece [`loadApiJson`](https://github.com/Comfy-Org/ComfyUI_frontend/blob/v1.53.6/src/scripts/app.ts#L2140-L2292), mas abrir o editor nativo e reconstruir o grafo exige verificar os inputs dinâmicos. A decisão atual é uma visualização de consulta no Studio e acesso separado ao editor avançado. Assim, inspecionar componentes não torna obrigatório operar por nós.

## Critério de conclusão

Na implementação atual, o painel já concentra geração, biblioteca persistente, cancelamento, reutilização da receita e comparação do original com o resultado dos passes adicionais. A base concluída permanece acessível se uma etapa posterior falhar ou for cancelada. Os rótulos de referência consideram os áudios realmente presentes nos vídeos, verificados antes da geração. A verificação de disponibilidade usa os modelos instalados e os nós registrados. Estas correções têm evidência local de código e testes; não demonstram ganho visual. Pose, keyframes intermediários, edição/continuação, LTX, Turbo e direção multimodal permanecem fora do painel. A lista verificável está em [studio-feature-gap.json](audit/studio-feature-gap.json).

O [modelo oficial](https://huggingface.co/MiniMaxAI/MiniMax-H3) declara que Context-IR e Regenerate-2K são partes hospedadas fora do release local. **OpenH3 local não é Context-IR oficial, e nosso upscaler com refinamento não é Regenerate-2K oficial.** Essas lacunas ajudam a explicar por que reproduzir um vídeo de divulgação depende da receita completa.

Concluir a integração requer: executar a imagem construída, confirmar cada controle em nós reais, gerar os mesmos casos nos três domínios pedidos e examinar vídeo e áudio. Comparar primeiro base versus a intervenção pertinente e depois a combinação vencedora; automatizar fila e coleta, sem transferir isso ao usuário. Física de líquidos/colisões e equivalência a Seedance permanecem hipóteses até haver resultados comparáveis. Um painel funcionando confirma a operação; não confirma realismo.
