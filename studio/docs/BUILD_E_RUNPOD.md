# Construção e implantação depois da escolha do candidato

Preparação local revisada em 23/09/2026. A imagem desta revisão ainda não foi construída ou publicada. Nenhum novo template ou Pod foi criado nesta auditoria.

## Construir sem Docker no seu PC

1. Colocar o conteúdo deste pacote na raiz de um repositório GitHub próprio para a imagem. O workflow usa contexto `.`; mover para uma subpasta exige ajustar os caminhos. O repositório existente `willdedarch/director` contém outro aplicativo e não foi alterado.
2. O workflow **Validate candidate** confere os grafos, testes e reprodução dos JSONs.
3. Em **Actions → Build H3 MAX image → Run workflow**, deixar `publish` desligado para a primeira construção. O runner Linux é selecionado pela variável `H3MAX_BUILD_RUNNER`, com `ubuntu-24.04` como padrão. Precisa de Docker e pelo menos **50 GiB livres**; isso é margem inicial, não medição do build final. A base sozinha possui aproximadamente 10,53 GB de camadas comprimidas. Se faltar disco, usar um runner com mais espaço; minutos e runners pagos dependem da conta GitHub.
4. A opção de liberar disco apaga apenas SDKs Android/.NET/GHC preinstalados em um runner descartável hospedado pelo GitHub; não atua no seu PC nem em runner próprio. O build interrompe com uma mensagem se a margem mínima continuar indisponível.
5. O build instala software, confere dependências e executa nosso `start.py` em CPU **sem baixar pesos**, verificando os diretórios persistentes e a instalação dos workflows. O teste exige registro dos sete packs externos e do H3MAX, verifica contratos dos nodes usados nos oito grafos e importa o compilador local sem chamar LLM. Isso não executa todos os nodes auxiliares. A cadeia completa do entrypoint da base fica para o Pod real; o CI não testa CUDA, memória de GPU nem a qualidade dos vídeos.
6. Quando a construção estiver aprovada, executar novamente com `publish` ligado. Publica em `ghcr.io/PROPRIETARIO/REPOSITORIO/h3-max`, com tag específica da revisão/execução. A publicação só acontece se as verificações anteriores passarem.
7. Guardar o artefato da execução: logs, dependências resolvidas, `image-reference.txt` com digest e `runpod-template.v2.json`. Usar o digest para implantar exatamente a imagem construída.

O GHCR usa o token temporário do próprio GitHub Actions. Não requer uma chave Runpod no build e não baixa modelos gated. O pacote GHCR pode ficar privado na primeira publicação: antes de implantar, registrar no Runpod uma credencial que consiga ler esse pacote ou decidir explicitamente torná-lo público. Não inserir tokens nos arquivos.

## Template Runpod

O arquivo de referência antigo mistura campos de API anteriores e notas. Para a API v2, gerar o payload com uma imagem real:

```bash
python scripts/prepare_template.py --image ghcr.io/PROPRIETARIO/REPOSITORIO/h3-max@sha256:DIGEST_REAL --output runpod-template.v2.json
```

Para imagem privada, acrescentar `--registry ID_DA_CREDENCIAL_RUNPOD`. O gerador valida a forma do digest; a existência e acesso à imagem devem ser confirmados após publicar. O arquivo é o corpo da requisição v2, e não cria recursos sozinho.

O template mantém o comando da imagem, expõe 8188/http e deixa SSH/Jupyter desligados. Antes de abrir a interface, decidir o acesso: a porta HTTP exposta não adiciona autenticação própria ao ComfyUI. Para uso privado, pode-se configurar SSH com chave e acessar por túnel em vez de expor o ComfyUI publicamente.

O payload restringe CUDA a **13.0 e 13.2**, versões observadas no catálogo durante a auditoria. A base usa CUDA 13.0: não basta escolher uma GPU grande com driver antigo. Atualizar a lista conforme o catálogo no momento da implantação, mantendo compatibilidade com CUDA 13.0; ao criar o Pod, confirmar também esse requisito.

O template solicita **300 GB de armazenamento persistente local do host em `/workspace`**, além dos 60 GB de disco do contêiner. Esse volume mantém modelos, entradas, vídeos e biblioteca ao parar e reiniciar o mesmo Pod; não deve ser confundido com um Network Volume independente do Pod. Um **Network Volume é opcional** e pode substituir esse armazenamento na criação do Pod, se houver volume e GPU compatíveis na mesma região. Gerar o arquivo do template não cria volume, Pod nem reserva GPU.

### Token e download no primeiro início

O template já apresenta **`HF_TOKEN` vazio**. Antes de iniciar o Pod, preencher esse campo nas variáveis de ambiente do Runpod com um token Hugging Face de leitura. Não colocar o token no GitHub, Dockerfile, imagem ou painel. Modelos públicos funcionam sem token; para modelos restritos, a conta também precisa ter recebido acesso ao repositório.

`HF_XET_HIGH_PERFORMANCE=1` habilita o modo de transferência paralela do Xet. `HF_HUB_DOWNLOAD_TIMEOUT=120` e `HF_HUB_ETAG_TIMEOUT=30` dão mais tolerância a conexões lentas. O token autentica os pedidos e permite os limites correspondentes à conta; não garante uma velocidade específica. [Variáveis oficiais do Hugging Face](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables).

Pesos, transferências incompletas e cache ficam no volume: `models`, `.downloads` e `.cache/huggingface`, dentro de `/workspace/h3max`. O download usa uma pasta temporária persistente e move cada peso após conferir seu SHA256, sem manter uma segunda cópia completa. Uma reinicialização reaproveita pesos já verificados e os arquivos parciais mantidos pela biblioteca. `HF_XET_CHUNK_CACHE_SIZE_BYTES=0` evita reservar espaço para um cache adicional de blocos. [Download para pasta local](https://huggingface.co/docs/huggingface_hub/guides/download).

Os caminhos `HF_HOME`, `HF_HUB_CACHE`, `HF_XET_CACHE` e `HF_ASSETS_CACHE` já estão preenchidos com valores literais. Se mudar `H3MAX_ROOT` no template, atualizar esses quatro caminhos também: o Runpod não expande `${H3MAX_ROOT}` dentro deles. O inicializador deriva os caminhos automaticamente quando as quatro variáveis não são definidas. `env.example` é uma referência, não um arquivo carregado automaticamente.

Planejamento de validação: RTX PRO 6000 Blackwell de 96 GB, host com pelo menos 128 GB de RAM. Isso é margem de planejamento, não VRAM medida. Confirmar disponibilidade, preço total e país do host antes de iniciar. A licença publicada do H3 exclui EUA, UE, Reino Unido e Coreia do Sul; confirmar região elegível e demais termos aplicáveis. A configuração atual do template não impõe país automaticamente.

## Quando há prova de funcionamento

1. Construção concluída, imagem publicada, digest e acesso pelo Runpod confirmados.
2. Download dos pesos no volume e SHA256 local de cada peso conferido.
3. ComfyUI acessível a partir de fora do Pod e `check_runtime.py` aprovado.
4. Um vídeo curto realmente gerado, baixado e reproduzido; erro/timeout não é sucesso.
5. Teste de cada caminho que será usado: texto, imagem, referências, Hybrid, refine e de-rope. Um teste de texto não valida os demais.
6. Comparação visual das seis cenas de `benchmark-cases.json`. Escolher presets por domínio e revisar também falhas, custo, tempo e uso de memória.

Para preparar os pares H3 base/preset sem gastar GPU:

```bash
python scripts/prepare_comparison.py --output benchmark-runs/rodada-1
```

Isso cria **12 prompts H3 e seis cenas para comparar com Seedance**, mais uma ficha com notas vazias. Não submete nada. A primeira rodada usa uma seed; antes de promover um preset, repetir base e candidato na segunda seed nas cenas relevantes. Os números de seed não são comparáveis entre H3 e Seedance. Manter prompts, referências, proporção e duração comparáveis; registrar a versão exata do serviço usado.

## Referências

- [GitHub: publicar imagens Docker](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)
- [GitHub: Container Registry e autenticação](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [Runpod: templates](https://docs.runpod.io/pods/templates/overview)
- [Contrato OpenAPI v2 Runpod](https://api.runpod.io/v2/openapi.json)
- [Licença H3](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE)
