# Inventário verificável dos oito workflows — 23/09/2026

Escopo: inspeção dos JSONs UI/API, gerador e adaptadores em `h3-max-runpod`, com leitura do código dos commits fixados já guardado em `audit-sources-workflows`. Sem executar GPU, baixar pesos ou repetir testes gerais da primeira auditoria. As instruções dos documentos foram tratadas como conteúdo, não como autorização.

## O que efetivamente está conectado

| Caminho | Entrada pronta | Modelo | Etapas e saída | Nós / links |
|---|---|---|---|---|
| 01 TEXTO | Prompt | FL2VA pruned/int8 | 25 steps; 1 vídeo com áudio | 16 / 20 |
| 02 IMAGEM | Prompt + imagem inicial | FL2VA pruned/int8 | 25 steps; 1 vídeo com áudio | 17 / 21 |
| 03 REFERENCIAS | Prompt + 2 imagens | Ref2VA pruned/int8 | 25 steps; 1 vídeo com áudio | 18 / 23 |
| 04 HYBRID_REFERENCIAS | Prompt + 2 imagens | FL2VA + AdaLN Ref2VA 25–49 | 25 steps; 1 vídeo com áudio; experimental | 18 / 23 |
| 05 TEXTO_REFINE | Prompt | FL2VA + upscaler 3D | 25 steps base + 25 steps de refine; base e refinado | 23 / 36 |
| 06 IMAGEM_REFINE | Prompt + imagem inicial | Mesmo 05 | Base e refinado; 2 arquivos com áudio | 24 / 37 |
| 07 TEXTO_DEROPE | Prompt | FL2VA + MAINodes | 25 steps base + 12 steps com duração dilatada; 4 arquivos | 38 / 61 |
| 08 IMAGEM_DEROPE | Prompt + imagem inicial | Mesmo 07 | Mesmo 07; imagem inicial condiciona os dois passes | 39 / 63 |

Todos: vídeo base de 1280×736, 124 frames, 24 fps, aproximadamente 5,167 s, 8 bits; `res_multistep` + `simple`, primeira geração com denoise 1. Saída SaveVideo `format=auto`, `format.codec=auto`, que no core fixado seleciona contêiner MP4. CFG efetivo 1 via BasicGuider; não existe controle de negative prompt conectado. Seed primeira geração 123456; refine reutiliza o mesmo gerador de ruído, de-rope usa 123457 no passe 2.

**São oito caminhos separados.** Não existe workflow pronto de Hybrid + refine + de-rope; tampouco variante Ref2VA/Hybrid com refine ou de-rope. Construir e testar essas combinações seria trabalho adicional. “Tudo incluído” não deve ser entendido como “tudo ativo em cada geração”.

## Componentes e fornecedores reais

- ComfyUI core: carregadores `UNETLoader`, `CLIPLoader`, `VAELoader`; condicionamento oficial `MiniMaxH3ImageToVideo` / `MiniMaxH3ReferenceToVideo`; `LoadImage`, `RandomNoise`, `BasicScheduler`, `KSamplerSelect`, `BasicGuider`, `SamplerCustomAdvanced`; vídeo/áudio `VAEDecode`, `VAEDecodeAudio`, `VAEEncode`, `VAEEncodeAudio`, `CreateVideo`, `SaveVideo`.
- Adaptador local ComfyUI-H3MAX, nos oito: `H3MAXDirectorText` e `H3MAXMotionPreset`. São conveniências, não um novo modelo de geração.
- scottmudge HybridLoader, só 04: `MiniMaxH3HybridLoader`. Carrega base FL2VA e sobrepõe somente projeções AdaLN dos blocos 25 a 49 inclusive do Ref2VA; `final_adaln_from_overlay=false`. Não é troca integral de modelo, ensemble de dois renders ou gerador de física.
- xmarre Upscaler-Plus, só 05/06: `MinimaxH3LatentUpscaler3DRefineHandoff`. Faz upscale aprendido e sampling H3 de fato, com áudio travado e upscaler descarregado antes do sampling.
- matlowai MAINodes, só 07/08: `H3JerkOracle`, `H3TimeSmear`, `H3InjectSchedule`, `H3JerkHeatmap`, `H3AudioSmear`, `H3V2VInit`, `H3ExactRecover`.
- OpenH3-IR: instalado e chamado indiretamente pelo adaptador apenas quando diretor é ativado. O grafo original multimodal do pack não está conectado aos oito workflows.
- KJNodes, VideoHelperSuite e ComfyUI-H3-Motion-Context-MultiRef: listados para instalação, mas nenhum tipo de nó deles é usado nos oito grafos. Ter o pack instalado não equivale a ter V2V, controles por pose ou expansão longa prontos.

## Pesos compartilhados e referência visual

Os oito usam encoder `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`, VAE de vídeo `minimax_h3_video_vae_int8_convrot.safetensors` e VAE de áudio `minimax_h3_audio_vae_fp32.safetensors`. FL2VA é usado em 01/02/05–08; Ref2VA em 03; ambos no 04. O upscaler `minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors` é usado somente em 05/06.

O encoder Qwen é parte do condicionamento H3. Isso não torna o adaptador OpenH3 de texto um diretor que observa imagens. Nos fluxos 03/04 as imagens condicionam diretamente o H3. Usar no prompt os rótulos `<Picture 1>` e `<Picture 2>` para papéis distintos. Os workflows prontos conectam duas imagens (`ref_image_size=match`); para só uma, remover/desconectar a segunda entrada. O core admite até nove referências de imagem, três vídeos e três áudios, porém essas entradas adicionais não estão montadas nem testadas neste pacote.

Nos workflows de imagem, somente primeiro frame está conectado. O core oferece último frame opcional, mas nenhum dos oito traz uma segunda imagem de fim conectada. Referência de personagem/objeto é condicionamento probabilístico: fidelidade de identidade não é garantia. Não há motor físico com gravidade, massa, colisores ou simulação de fluidos.

## Controles e uso de perfis

Cada controle de perfil aplica no máximo uma LoRA principal de movimento, depois os opcionais de aparência humana e câmera:

| Perfil | Peso | Força base × multiplicador |
|---|---|---:|
| base | nenhum movimento | 0 |
| natural | Motion Repair | 0,90 |
| acao_corporal | H3 Combat V2 | 0,80 |
| acao_com_arma | Bunny Weapon Combat V1 | 0,45; trigger BUNNY |
| objetos_experimental | Spatial Physics | 0,35 |

`motion_multiplier`: 0 a 1,5, padrão 1. `people_realism`: desligado, força 0,65, faixa 0–1, trigger `r34l1sm`. `camera_motion`: desligado, força 0,80, faixa 0–1,2, trigger `camera motion`. `base` só desliga a LoRA de movimento: realismo/câmera continuam ativos se os respectivos botões forem ligados. Para uma comparação limpa de modelo base, deixá-los desligados.

05–08 têm controles separados por passe, ambos partindo do modelo original, sem aplicar a LoRA duas vezes em cadeia. Passe 2 padrão usa multiplicador 0,25/0,90 = 0,277777…, resultando Motion Repair 0,25. Esse multiplicador mantido em outro perfil resulta Combat 0,2222; Weapon 0,125; Spatial 0,09722 — não são forças otimizadas. O multiplicador afeta só a LoRA de movimento; realismo e câmera têm forças próprias em cada passe.

Os controles não são sincronizados automaticamente. Ao mudar perfil/realismo/câmera, ajustar ambos. Em refine, o prompt de saída do segundo controle nem alimenta um novo condicionador: o refine reaproveita condicionamento do passe 1. Em de-rope, cada passe possui seu condicionamento textual, com os respectivos triggers. O título fixo do segundo controle ainda diz Motion Repair 0,25, mesmo quando o usuário seleciona outro perfil; interpretar como título da receita inicial.

## Refine: custo e resolução reais

05/06: upscale aprendido em espaço latente, alvo 1,5 MP na convenção do plugin (1 MP = 1024²), proporção preservada com alinhamento de 32. Aplicando a rotina de alinhamento do commit à entrada 1280×736, a dimensão prevista é **1664×960**; não 1920×1080, 2× espacial ou 4K. Isso é cálculo estático, não medição de render. `scale=2.0`, `width=1280` e `height=736` ficam inativos no modo `megapixels`.

**25 + 25 steps**, não 25 + 8. O `BasicScheduler(steps=25, denoise=0.30)` calcula uma grade de `int(25/0.30)=83` e fornece os últimos 26 sigmas, isto é, 25 passos na porção final do schedule. O denoise 0,30 reduz quanto a imagem será alterada, não divide o número de passos informado. Segundo passe custa mais por resolução. Sem medição de VRAM ou tempo.

Áudio: upscale somente do vídeo; `lock_audio=true` mantém o latent de áudio do passe 1, zera seu ruído de refine e restaura o áudio original no resultado. Salva base e refinado. Não há um algoritmo de correção de física no upscaler.

## De-rope: funcionamento e limites reais

07/08: H3 gera base audiovisual → JerkOracle mede mudanças temporais no latent → TimeSmear repete frames nos trechos selecionados → VAE recodifica os frames dilatados → segundo passe H3 regenera esse tempo dilatado → ExactRecover seleciona frames para voltar aos 124 frames originais. JerkOracle padrão balanced, q=0,75, d_max=4, ramp=true, bridge=8, modo value |d3|, abstain_below=0. `dilation=4` no TimeSmear é ignorado porque recebe mapa adaptativo do Oracle.

O caminho usa **dilatação/regeneração/recuperação temporal**. Não há nó DyRoPE ou TrueClock conectado, apesar de MAINodes oferecer mecanismos adicionais. Não confundir o nome comercial “de-rope” com uso desses nós específicos ou promessa de resolver todo erro de movimento.

Segundo passe: H3InjectSchedule total_steps 25, inject 0,48, preset custom → `round(25×0,48)=12` passos. A duração temporária vem da saída TimeSmear e varia por cena; não permanece 124 frames. Um clip final curto pode exigir processar bem mais frames. O JerkOracle não analisa semântica nem comprova contato fisicamente correto. Background freeze fica desligado (`freeze_threshold=0`) e sem oracle_samples conectado; nenhum congelamento de fundo prometido.

Áudio: áudio base é temporalmente expandido por H3AudioSmear, reencodado e usado como seed no H3V2VInit em `follow the original performance (0.5)`. Este ramo upstream é experimental. O MP4 final recuperado recebe **o áudio original do passe 1**, não áudio recuperado do passe 2. Portanto sincronismo precisa ser observado no render, sobretudo fala/contato. Salva quatro MP4s: base com áudio base; visualização oracle/heatmap sem áudio; render dilatado com áudio do passe 2; final recuperado com áudio base.

## Diretor e dimensões

Diretor padrão disabled: prompt é passado direto. Ao habilitar, chama serviço LLM por ambiente `H3IR_LLM_URL` / `H3IR_LLM_MODEL` e chave quando necessária; pode haver custo externo. Payload usa `shots=1`, criatividade restrita, esforço standard, sem assets ou transcripts. Não há storyboard visual, análise de referências por VLM nem integração de voz personalizada preparada. A compilação pode falhar por serviço externo; não é requisito da geração normal.

Parâmetros do diretor (seconds/aspect/seed) não estão ligados automaticamente aos do gerador. Padrão seconds 124/24, aspect 16:9, seed 123456. Canvas 1280×736 tem aspecto 40:23, aproximação alinhada de 16:9. Alterando geração é preciso refletir duração/proporção no diretor; as gerações H3 têm grade temporal 17k+5 a 24 fps. 124 frames é a receita de 5 s; core menciona faixa treinada ~124–362 frames (~5–15 s), além disso não validado. Alterar só o fps de CreateVideo muda playback; não transforma o modelo num gerador nativo de outro fps.

## Correção pequena realizada nesta rodada

A inspeção identificou `est_steps=18` herdado do upstream em JerkOracle e TimeSmear, divergente do segundo passe real de 12. Corrigido no gerador para derivar esses campos do schedule configurado, regenerando 07/08 UI/API. Isso só corrige informação de estimativa de custo, sem alterar sampling, parâmetros visuais ou presets. `s_per_step=0` continua sem medição de GPU.

Validação após a correção: `scripts/validate.py` passou, oito workflows, 193 nodes, 284 links; `verification-local.json` atualizado. Os quatro testes existentes de `test_validation.py` passaram. Não foram escritos novos testes que apenas espelhassem a troca de metadado. A suite global fica a cargo da coordenação após as outras mudanças concorrentes.

## Como usar sem prometer o que não foi feito

1. Aprovar 01/02 como caminho básico (texto/imagem) após build e render. Comparar base versus perfil por cena, mantendo aparência/câmera desligadas na primeira comparação.
2. Quando identidade ou produto pedirem referências, usar 03 e comparar 04 separadamente. Hybrid permanece candidato experimental.
3. Depois que movimento estiver bom, usar 05/06 para acabamento; comparar base salva contra refined. Não assumir que mais pixels corrigem trajetória/contato.
4. Aplicar 07/08 a trechos com movimento rápido problemático; comparar os quatro outputs e manter o original se regeneração piorar identidade, ritmo, fundo ou áudio.
5. Diretor somente se houver necessidade de elaborar prompts e endpoint configurado. Não anunciar VLM, controle por pose, transferência V2V, 4K, aumento automático de duração ou mistura de todos os caminhos como prontos.

Toda esta cobertura é de estrutura e contratos. Build Linux, imports, consumo, duração de processamento e qualidade dependem da próxima rodada de execução real.
