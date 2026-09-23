# Auditoria dos workflows H3 MAX — 23/09/2026

Escopo: leitura dos oito workflows, seis APIs originais, gerador, custom nodes e validadores; confronto com código público nos commits do manifesto. O original em `candidate-original/h3-max-runpod` foi preservado. Correções em `h3-max-runpod`. Nenhum peso/modelo foi executado nesta auditoria; nenhuma equivalência de qualidade com Seedance foi demonstrada.

## Bloqueios concretos encontrados e corrigidos

### 1. P0 — chamada errada no carregador LoRA: o padrão `natural` quebrava antes do sampling

- Original: `custom_nodes/ComfyUI-H3MAX/__init__.py:58` chama `LoraLoaderModelOnly().load_lora(model, filename, strength)`.
- No ComfyUI fixado, `load_lora` é o método herdado que recebe cinco argumentos além de `self`; o wrapper correto é `load_lora_model_only(model, lora_name, strength_model)`.
- Resultado original: `TypeError` em todo perfil ativo, inclusive o padrão `natural`; também quando realismo/câmera opcionais são ativados.
- Corrigido em `h3-max-runpod/custom_nodes/ComfyUI-H3MAX/__init__.py:61`.
- Regressão testada com a assinatura real dos métodos do commit, não um mock que aceita a chamada errada. O resultado anterior `Mocked native LoRA loader verified...` não comprovava compatibilidade com a implementação nativa.
- Evidência: [ComfyUI nodes.py fixado, linhas 735–769](https://github.com/Comfy-Org/ComfyUI/blob/912fca4f39b875a0360f2c5170568176ea813ded/nodes.py#L735).

### 2. P1 — os prompts API originais não satisfazem o `SaveVideo` fixado

- Original: `scripts/build_workflows.py:44` exporta `format` e `codec` no mesmo nível.
- O core fixado usa DynamicCombo: escolher `format=auto` ativa um campo requerido `format.codec`. Existe um campo `codec` legado opcional, mas ele não supre o requerido aninhado.
- Resultado: a validação do ComfyUI rejeita os prompts antes de gerar. A checagem original só verificava registro dos nomes dos nós; portanto passaria sem detectar o erro.
- Corrigido em `scripts/build_workflows.py:44`, regenerando os prompts com `format.codec`.
- Evidências: [SaveVideo schema fixado](https://github.com/Comfy-Org/ComfyUI/blob/912fca4f39b875a0360f2c5170568176ea813ded/comfy_extras/nodes_video.py#L135); [expansão DynamicCombo](https://github.com/Comfy-Org/ComfyUI/blob/912fca4f39b875a0360f2c5170568176ea813ded/comfy_api/latest/_io.py#L1255); [validação de entradas](https://github.com/Comfy-Org/ComfyUI/blob/912fca4f39b875a0360f2c5170568176ea813ded/execution.py#L880).

## Cobertura de validação corrigida

O README original declarava corretamente que não houve build, GPU ou comparação Seedance. Não se trata de alegação de GPU validada; o problema era uma validação estática incapaz de encontrar os bloqueios acima.

- `check_runtime.py` original, linhas 26–37: verificava nomes registrados e apenas UNET/CLIP/VAE. Não confrontava required inputs, tipos, posições das saídas, DynamicCombo/Autogrow, modelos Hybrid/upscaler nem LoRAs carregadas dentro do preset.
- O novo `validate_prompt_schema` confronta todos os inputs/links dos oito prompts com `/object_info`, incluindo campos dinâmicos. `--nodes-only` pula apenas disponibilidade de arquivos e não enfileira geração: serve para CI CPU sem pesos. Combos de dtype/sampler, inputs obrigatórios e tipos continuam sendo verificados.
- A verificação normal também verifica escolhas de modelos Hybrid/upscaler e presença das LoRAs do grupo principal. Imagens de exemplo só são verificadas como arquivos disponíveis quando um smoke com `--image` é solicitado.
- Os workflows 07/08 agora também possuem API exportada; o gerador tem mapeamentos explícitos dos widgets MAINodes nos commits fixados.
- `validate.py` original não lia os prompts API. Agora exige correspondência 1:1 entre os oito arquivos UI/API e identidade de parâmetros/links exportados; verifica nomes de pesos também no custom node, hashes/revisões hexadecimais e rejeita posições negativas de links.
- O smoke aceita seleção de workflow, perfil e imagens. Nos caminhos de-rope, mantém o vínculo da duração dilatada e reduz apenas a duração inicial. No refine, usa alvo menor para smoke. Retorno `success` sem arquivo de saída também falha.
- Leituras/escritas do gerador e do validador agora explicitam UTF-8 para reprodução Windows/Linux.

## Ajustes de receita baseados nos autores — ainda precisam de A/B real

- Motion Repair: o pacote reutilizava 0,90 no primeiro e segundo passes. Foram criados controles independentes de segundo passe nos workflows 05–08, partindo do modelo original, com natural 0,25 (multiplicador `0.25/0.9`), sem empilhar sobre a LoRA de 0,90. A intensidade menor segue a indicação do autor para refine/de-rope; não prova que esta seja a melhor receita para toda cena. [Model card Motion Repair](https://huggingface.co/JOKER141/MiniMax-H3-General-Motion-Continuity-Repair).
- MAINodes: `inject` passou a 0,48 com preset `custom`, alinhado ao README atual do commit selecionado revisado pela auditoria física. Apenas mudar o número mantendo `balanced 0.70` seria inócuo: o código sobrescreve o número pelo preset. [Código H3InjectSchedule](https://github.com/matlowai/ComfyUI-MAINodes/blob/f4868b4a08e8a504ce86db54a17961d399ffa2bc/motion.py#L3285); [README fixado](https://github.com/matlowai/ComfyUI-MAINodes/blob/f4868b4a08e8a504ce86db54a17961d399ffa2bc/README.md).
- Weapon Combat: o preset adiciona `BUNNY` quando ativo, evitando duplicação e não adicionando quando o multiplicador é zero. [Model card Weapon Combat](https://huggingface.co/JOKER141/MiniMax-H3-Weapon-Combat-LoRA).
- Manter o perfil/triggers do primeiro e segundo passes coerentes ao editar o workflow. No refine, o condicionamento textual continua sendo o do primeiro passe; no de-rope cada passe possui seu condicionamento.

## Interfaces conferidas sem incompatibilidade estática encontrada

- `MiniMaxH3ImageToVideo` aceita primeiro/último frame opcionais: o workflow só texto via FL2VA é suportado pelo node. Duração 124 e smoke 39 seguem grade 17k+5; 1280×736 e 640×384 seguem o alinhamento espacial.
- `MiniMaxH3ReferenceToVideo` usa as chaves API `ref_images.ref_image_0/1`, conforme Autogrow no core fixado.
- Hybrid: campos/preset `block_range_adaln`, faixa 25–49, base FL2VA e overlay REF2VA têm correspondência com a interface fixada. Isso confirma contrato, não qualidade nem consumo de RAM.
- Upscaler + Refine: nome de registro `MinimaxH3LatentUpscaler3DRefineHandoff`, campos, modelo/positive explícitos e audio_latent opcional são compatíveis. O código fixado aceita LATENT audiovisual nativo, executa sampling parcial real e preserva áudio quando `lock_audio=true`; o pacote não está só fazendo upscale sem refine.
- Diretor: assinaturas de `build_payload` e `compile_here` são compatíveis com o adaptador. Continua sendo integração apenas textual; multimodal/serviço LLM ligado não foram executados.
- De-rope: conserva áudio final do passe 1 e não exige vídeo externo. Os nós de áudio temporal do segundo passe continuam experimentais e podem elevar custo/memória; contratos estáticos não comprovam execução numérica correta.

Fontes fixadas adicionais: [nodes_minimax_h3.py](https://github.com/Comfy-Org/ComfyUI/blob/912fca4f39b875a0360f2c5170568176ea813ded/comfy_extras/nodes_minimax_h3.py); [upscaler refine](https://github.com/xmarre/Comfyui_Minimax_h3_latent_Upscaler-Plus/blob/620165a311de9b28a36260219fb5cd370a304e3c/nodes/minimax_h3_refine.py); [Hybrid loader](https://github.com/scottmudge/ComfyUI_MinimaxH3HybridLoader/blob/a44c69b02242e41fbd01e22abe2a492adc853038/minimaxh3.py); [OpenH3 compiler adapter](https://github.com/ruashots/ComfyUI-OpenH3-IR/blob/8660988b033d427f346e72fdbcf2d45ede48edbe/compiler.py).

## Validação realmente executada

- Regeneração dos oito workflows e oito APIs; verificação estática passou: 193 nós, 284 links.
- Suite integrada no Python 3.11 local: 29 testes, 28 passaram, um teste de symlink pulado por falta de privilégio Windows. Onze testes de runtime/regressão e quatro de integridade dos workflows foram incluídos nesta auditoria.
- Fontes públicas foram baixadas em `D:/gpu-runpod/audit-sources-workflows` para leitura. Não foi importado o runtime completo do ComfyUI.

Próximos gates: construir a imagem; executar imports + schema check CPU contra `/object_info` real; baixar/verificar pesos; smoke GPU de cada caminho que será usado; finalmente comparar movimento humano, ação/contato e objetos/líquidos com amostras equivalentes. Até isso ocorrer, o status é candidato corrigido, sem qualidade ou equivalência confirmadas.
