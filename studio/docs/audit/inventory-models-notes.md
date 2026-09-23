# Inventário técnico de modelos e extensões — 23/09/2026

Este relatório descreve o que está selecionado no pacote `D:\gpu-runpod\h3-max-runpod`, como será utilizado e o que ainda exige montagem. O pacote não contém pesos; `downloaded_and_hash_verified=false` está presente nos 24 registros. A imagem ainda não foi construída. Portanto, “instalado no build” abaixo significa comportamento previsto do instalador, não execução já observada.

## Contagem e armazenamento

Conferência direta de `models.lock.json`, `sources.lock.json`, `scripts/install.py`, `scripts/start.py`, `scripts/download_models.py`, dos oito prompts API e de `docs/audit/audit-model-metadata.json`.

| Grupo | Arquivos | Bytes | GB decimais | GiB |
|---|---:|---:|---:|---:|
| `h3` — padrão | 12 | 62.641.594.279 | 62,64 | 58,34 |
| `control` | 3 | 4.337.250.130 | 4,34 | 4,04 |
| `encoder_int8` | 1 | 27.141.342.152 | 27,14 | 25,28 |
| `full_base` | 1 | 34.038.892.334 | 34,04 | 31,70 |
| `experimental_motion` | 1 | 310.168.816 | 0,31 | 0,29 |
| `singularity` | 1 | 20.967.647.456 | 20,97 | 19,53 |
| `ltx25` | 5 | 39.709.872.236 | 39,71 | 36,98 |
| Total | **24** | **189.146.767.403** | **189,15** | **176,16** |

Os 12 opcionais somam 126.505.173.124 bytes: 126,51 GB. Esses valores são somente pesos; não incluem imagem Docker, entradas, saídas, caches, temporários e espaço de trabalho. Disco não equivale a VRAM necessária. O grupo padrão é composto por cinco componentes base (61,04 GB), seis LoRAs (0,91 GB) e um upscaler (0,69 GB).

A auditoria de metadados tem 24 registros com `exists`, `sha_match` e `size_match` verdadeiros. Isso verifica arquivo/revisão/tamanho/hash publicado; o download futuro será conferido pelo SHA256 completo, mas nenhum dos pesos foi carregado em GPU nesta auditoria.

## Os 12 pesos padrão e sua utilização

Todos abaixo pertencem ao grupo `h3`, baixado no primeiro boot com a configuração padrão. “Opcional no uso” não significa “opcional no download”: Realism People e Camera Motion são baixados, mas seus controles começam desligados.

| Arquivo | GB | Papel | Integração no pacote |
|---|---:|---|---|
| `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | 20,970 | Gerador H3 de texto/imagem inicial; também base do Hybrid | Workflows 01, 02, 04, 05, 06, 07, 08 |
| `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | 20,970 | Geração orientada por referências; overlay do Hybrid | Workflows 03 e 04 |
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | 15,687 | Codificação multimodal usada pelo H3 | Todos os oito workflows |
| `minimax_h3_video_vae_int8_convrot.safetensors` | 2,811 | Codifica imagens/latentes e decodifica vídeo | Todos os oito workflows |
| `minimax_h3_audio_vae_fp32.safetensors` | 0,605 | Codifica/decodifica a parte de áudio do H3 | Todos os oito workflows |
| `Motion_Repair.safetensors` | 0,155 | Continuidade de movimento | Perfil `natural`; comparar com `base` |
| `wushu_spatial_physics_clean_3000_pruned.safetensors` | 0,155 | Experimento de coerência espacial e objetos | Perfil `objetos_experimental`; sem comprovação específica de líquidos |
| `h3-realism-people-t2v-i2v-r2v.safetensors` | 0,131 | Aparência de pessoas | Controle `people_realism`, desligado inicialmente |
| `camera_motion_h3_lora_v1_3000_pruned.safetensors` | 0,155 | Movimento de câmera | Controle `camera_motion`, desligado inicialmente |
| `H3_Combat_V2.safetensors` | 0,155 | Movimento/reação de ação corporal | Perfil `acao_corporal` |
| `Bunny_weapon_combatV1.safetensors` | 0,155 | Ação com objetos segurados/armas cênicas | Perfil `acao_com_arma`, separado dos demais perfis |
| `minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors` | 0,691 | Ampliação espacial em latentes H3 | Workflows 05 e 06, seguida de refine |

O Hybrid não adiciona um 13º checkpoint: lê os dois H3 oficiais já selecionados e combina grupos de tensores em memória. O texto/diretor não é um novo motor de vídeo. Upscale/refine aumenta custo e acabamento, sem garantia de consertar contato ou causalidade. Realismo de aparência, movimento e física precisam de avaliações separadas.

## Os 12 pesos opcionais

| Grupo / arquivo | GB | Utilização e lacuna |
|---|---:|---|
| `control`: `minimax_h3_fun_controlnet_union_pruned_int8_convrot.safetensors` | 2,297 | Condicionamento estrutural ControlNet v1; não está conectado aos oito H3_MAX |
| `control`: `sdpose_wholebody_fp16.safetensors` | 1,917 | Extração de pose corporal para o fluxo de controle |
| `control`: `rt_detr_v4-x-hgnet_fp16.safetensors` | 0,124 | Detecção de pessoas para o extrator de pose |
| `encoder_int8`: `qwen3vl_32b_minimax_h3_int8_convrot.safetensors` | 27,141 | Alternativa ao encoder NVFP4; troca no loader e comparação. Não se soma ao encoder em inferência normal |
| `full_base`: `minimax_h3_fl2va_int8_convrot.safetensors` | 34,039 | Checkpoint não pruned alternativo ao FL2VA padrão. Maior tamanho, sem ganho de qualidade demonstrado aqui |
| `experimental_motion`: `better_motion_h3_lora_v1_500.safetensors` | 0,310 | Alternativa de movimento T2V/I2V. Não aparece no seletor de perfis H3MAX; exige loader próprio/integração e A/B |
| `singularity`: `Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8.safetensors` | 20,968 | Checkpoint comunitário alternativo; não é camada que se liga a todos os outros. Exige workflow/preset separado e A/B |
| `ltx25`: `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | 21,504 | Gerador independente do H3; nenhum workflow LTX foi montado |
| `ltx25`: `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` | 0,996 | Upscaler próprio de LTX; não é o upscaler H3 |
| `ltx25`: `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | 15,373 | Encoder próprio de LTX |
| `ltx25`: `ltx-2.5-audio-vae-bf16.safetensors` | 0,365 | Componente de áudio próprio de LTX |
| `ltx25`: `ltx-2.5-video-vae-bf16.safetensors` | 1,472 | Componente de vídeo próprio de LTX |

Selecionar grupos no ambiente autoriza somente o downloader a baixar arquivos. Não modifica grafos, seletores ou parâmetros. Exemplo: `h3,control` soma 66,98 GB; ainda precisamos importar/adaptar um workflow de pose e testar sua execução.

Better Motion: a fonte fixada recomenda 0,4–0,8 e 20–30 passos para T2V/I2V; documentação curta e uma demonstração não confirmam superioridade. Singularity: a fonte fixada descreve fusão/ajuste de H3 e recomenda Turbo Ref2V 4 passos para acelerar; esse Turbo está ausente do manifesto. A recomendação de aceleração não prova que ele seja obrigatório. [Better Motion](https://huggingface.co/vpakarinen/better-human-motion-h3-lora/blob/9c87508f002b1cc8359574f252df547a96a884f5/README.md), [Singularity](https://huggingface.co/WarmBloodAban/Minimax-h3_Singularity/blob/af671d9214a6e41ab8c2f43e9f871ea56246115f/README.md).

LTX exige aceitar acesso no Hugging Face e usar token autorizado. Os dois arquivos quantizados selecionados são específicos do ComfyUI. O conjunto de cinco pesos não equivale a todos os recursos LTX: duration head, upscaler temporal e IC-LoRA de detalhamento não estão no manifesto. O caminho DFR descrito na documentação pede o adaptador de detalhamento; os recursos temporais usam outro upscaler. Nenhum deles deve ser prometido como integrado. A revisão dos pesos está verificada no registro anterior; a leitura direta do README fixado foi negada pelo gate, e a explicação funcional usa a página pública atual. [Model card oficial LTX](https://huggingface.co/Lightricks/LTX-2.5).

## Controle de pose: precisão sobre o exemplo oficial

A cópia do template oficial no commit fixado foi obtida em `inventory-model-sources/control-workflow.json`. Os seletores reais usam os mesmos cinco componentes H3 padrão e os três pesos `control`. A nota textual ainda menciona VAE fp16, mas o node efetivamente seleciona o VAE int8 já incluído. Há um ramo Turbo Ref2V 4step com controle inicialmente falso; seu peso não foi incluído. Para nossa versão, desabilitar/remover esse ramo e validar o grafo, ou adicionar o peso com proveniência antes de habilitá-lo.

O exemplo faz extração de pose e aplica ControlNet. O modelo Union também documenta Canny, profundidade, HED, MLSD e inpainting, mas esses caminhos não estão montados no exemplo nem nos oito H3_MAX. HED/MLSD pedem preprocessadores comunitários; profundidade exige selecionar o modelo do preprocessador. [Template oficial fixado](https://github.com/Comfy-Org/workflow_templates/blob/fc427f00097817d3f7d8099c5259837fa51e1267/templates/video_minimax_h3_fun_controlnet_union.json).

## Software: o que o build instala automaticamente

`scripts/install.py` clona o ComfyUI, percorre todos os sete `custom_nodes` do manifesto sem filtrar grupos, clona/instala o compilador e copia o pack local. O grupo de modelos não controla a instalação de software.

| Componente | Por que está presente | Uso já conectado |
|---|---|---|
| ComfyUI core | Geração, loaders, H3 nativo, áudio/vídeo, samplers, ControlNet/pose e interface | Base de todos os workflows |
| `ComfyUI_MinimaxH3HybridLoader` | Combinação experimental FL2VA/Ref2VA | Workflow 04 |
| `ComfyUI-OpenH3-IR` | Quatro nodes completos do diretor e exemplo multimodal original | Pack disponível; os H3_MAX usam adaptação local somente de texto |
| `ComfyUI-KJNodes` | Utilidades de imagem/vídeo e grafos externos | Disponível para expansão; não é dependência dos oito prompts API montados |
| `ComfyUI-MAINodes` | Motion Lab, de-rope e temporização | Workflows 07 e 08 |
| `Comfyui_Minimax_h3_latent_Upscaler-Plus` | Ampliação latente e preparação de refine | Workflows 05 e 06 |
| `ComfyUI-H3-Motion-Context-MultiRef` | Continuação, V2V, música, bridge, keyframes e máscaras | Nenhum dos oito H3_MAX conecta esses nodes |
| `ComfyUI-VideoHelperSuite` | Entrada/montagem de vídeo para os exemplos avançados | Disponível para expansão; os oito H3_MAX usam SaveVideo nativo |
| `ComfyUI-H3MAX` local | Seletor de perfis/LoRAs e diretor de texto simples | Dois tipos de node usados nos H3_MAX |
| `open-h3-ir` compiler | Estruturação de prompts por LLM | Chamado pelo diretor quando habilitado; requer endpoint/modelo configurados |

São **sete repositórios de extensões + um pack local + um compilador**, além do core. O repositório de templates em `sources.lock.json` registra proveniência; o instalador não clona a biblioteca inteira de templates. O startup copia apenas os oito workflows de `workflows/` para a pasta H3_MAX do usuário. Exemplos dos packs ficam nos diretórios clonados e precisam ser importados/adaptados.

O diretor completo OpenH3 pode trabalhar com imagens, vídeos e áudio de referência via bandeja própria. Referências visuais exigem LLM com visão. Sua documentação esclarece que não interpreta o conteúdo sonoro: utiliza metadados e descrição fornecida. Nosso adaptador H3MAX não conecta essa bandeja, portanto essa integração multimodal ainda não foi feita. O compilador roda no ambiente do ComfyUI; o endpoint de linguagem pode ser local ou externo e não está incluído como servidor de modelo no container. [Pack OpenH3 fixado](https://github.com/ruashots/ComfyUI-OpenH3-IR/blob/8660988b033d427f346e72fdbcf2d45ede48edbe/README.md).

## Expansões presentes no pack Motion Context, ainda fora dos oito H3_MAX

Requisitos documentados no commit fixado, confrontados com o manifesto local:

| Exemplo | Uso | Lacuna principal |
|---|---|---|
| AV Extension | Continuar vídeo; também permite começar com texto/imagem | Encoder INT8 opcional e Turbo 8step ausente |
| Music Video | Sequência de clipes sobre uma música | Encoder INT8, Turbo ausente e arquivos da música/referências |
| V2V Latent Motion Transfer | Transferir movimento de vídeo e finalizar | Encoder INT8, Turbo 8step 768p ausente, nome antigo do upscaler |
| AV Bridge | Criar ligação entre dois trechos | Encoder INT8 e dois vídeos de entrada |
| Custom Keyframes | Guiar momentos com imagens | Usa pesos `h3`; faltam imagens, importação e verificação |
| 2MP De-Rope Continuation | Continuação avançada em dois passes | SolAttn_triton não instalado, Turbo4step ausente e nome antigo do upscaler |

Os exemplos requerem fontes constantes de 24 fps. V2V usa força fracionária quantizada e schedule específico; remover Turbo exige reavaliar o sampler. Trocar nomes/modelos não prova compatibilidade. O upscaler do pacote é a variante `conv_v1`, diferente do nome salvo nesses exemplos. [Pré-requisitos fixados](https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef/blob/361624fb406b63eb6694442eac6c895fc1533a70/WORKFLOW_PREREQUISITES.md).

O pack também tem máscaras separadas de áudio/vídeo, preservação de contexto e inserções internas. Imagens-guia são orientações; proteção no latente não assegura pixels idênticos após decodificação. Inserção exata exige recomposição posterior com o material original. A continuidade usa comprimentos/posições discretos da grade H3, não tempos arbitrários. Esses mecanismos devem entrar em workflows próprios com casos de teste; não acrescentam simulação física. [Guia fixado de keyframes e máscaras](https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef/blob/361624fb406b63eb6694442eac6c895fc1533a70/KEYFRAMES_AND_INSERTS.md).

## Seleção recomendada, sem promessa de execução

1. Manter o conjunto `h3` como kit inicial completo: texto, imagem, referências, áudio, perfis especializados, câmera, aparência, Hybrid, refine e de-rope.
2. Promover cada recurso após testar o respectivo caminho. Um render do workflow 01 não valida os outros sete.
3. Priorizar expansão por necessidade: keyframes para orientar composição; pose para seguir coreografia; V2V/continuação quando houver vídeo de referência; diretor multimodal quando precisarmos descrever e relacionar mídia automaticamente.
4. Better Motion, encoder INT8, full FL2VA e Singularity são comparações alternativas. LTX é uma segunda linha de geração independente. Não há justificativa técnica para ligar tudo simultaneamente ou baixar todos os opcionais antes de escolher o uso.
5. Tratar Turbo, SolAttn, ControlNet 2.0, DFR LTX e integração multimodal completa como itens fora da entrega conectada atual. Adicionar somente após resolver peso/software/grafo e validação real.

Ainda pendentes: build Linux, import/schema de todos os packs que serão usados, download/hash local dos pesos, carga GPU, saídas reais, memória/tempo/custo e qualidade. Metadados e código revisado não comprovam equivalência ao Seedance 2.5.

Fontes locais adicionais consultadas: `docs/audit/audit-container.md`, `audit-physics.md`, READMEs fixados em `audit-sources-container`, core H3 fixado em `audit-sources-workflows/nodes_minimax_h3.py`. Cópias de novas fontes fixadas foram salvas em `D:\gpu-runpod\inventory-model-sources`; nenhum código ou infraestrutura foi alterado por este inventário.
