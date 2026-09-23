# Auditoria de container e preparação Runpod — 23/09/2026

O candidato tem uma estrutura aproveitável: código na imagem em `/opt`, pesos e dados em `/workspace`, commits e imagem base fixados, checksums dos pesos e validação separada de geração. Não há evidência de build, inicialização dos nodes ou inferência GPU realizada. A solução pode seguir para uma imagem candidata no GitHub Actions; só um teste real confirma a execução e a qualidade.

## Fontes verificadas

- Consultei o Docker Registry público de `runpod/pytorch`. A tag `1.3.2-cu1300-torch2120-ubuntu2404` resolve exatamente para `sha256:41428c446234172cb2700630b81bb55b7077026c7a43cbd2c991fd864e454c61`. É manifesto `linux/amd64`, criado em 21/09/2026. Metadados locais: `audit-sources-container/base-image-manifest.json`, `base-image-amd64-manifest.json` e `base-image-config.json`.
- A soma das camadas comprimidas da base é **10.532.010.870 bytes** (10,53 GB). Isso não representa o espaço final expandido nem o espaço temporário necessário durante build/load. A configuração usa Python 3.12, CUDA 13.0, entrada NVIDIA e comando `/start.sh`.
- Extraí somente a camada de 1.278 bytes contendo `/start.sh` da imagem exata e confirmei seu hash `0468a0fce7238de838bd2abb656aca5a1730b94bb50d82d6476502616d032283`. O script é idêntico à [fonte Runpod consultada](https://github.com/runpod/containers/blob/main/container-template/start.sh). Ele executa nginx, SSH condicionado a `PUBLIC_KEY`, Jupyter condicionado a `JUPYTER_PASSWORD` e `/post_start.sh` de modo síncrono. Preservar ENTRYPOINT/CMD na imagem derivada é coerente com esse contrato.
- Os `requirements.txt`, `pyproject.toml` e READMEs existentes de ComfyUI e dos sete packs foram lidos nos commits de `sources.lock.json`, não apenas na branch atual. Foram salvos em `audit-sources-container/`.
- O [compiler fixado](https://github.com/ruashots/open-h3-ir/blob/fd031e136ae3d89147324c0d1b2aa65e838c21f5/pyproject.toml) declara versão 0.4.1 e Python >=3.10; isso atende à dependência `open-h3-ir>=0.4.0` do [pack fixado](https://github.com/ruashots/ComfyUI-OpenH3-IR/blob/8660988b033d427f346e72fdbcf2d45ede48edbe/requirements.txt). Isso confirma o requisito declarado, não o contrato inteiro em runtime.
- `huggingface_hub==1.32.0` existe no [PyPI oficial](https://pypi.org/project/huggingface-hub/1.32.0/) e exige Python >=3.10. Não é um número inventado.

## Achados e correções aplicadas

As mudanças foram feitas somente na cópia `D:\gpu-runpod\h3-max-runpod`; o pacote extraído em `candidate-original` permaneceu intacto.

1. **Duas distribuições disputavam o mesmo módulo cv2.** KJNodes pede `opencv-python-headless`, e VideoHelperSuite pede `opencv-python`. O [próprio projeto OpenCV](https://pypi.org/project/opencv-python/) orienta instalar uma única distribuição, recomendando a variante headless em servidores. O instalador mescla os requisitos, normaliza o requisito desktop para headless, exige uma única distribuição e testa o import de `cv2`. Os requisitos pinned não usam funcionalidades de janela como requisito declarado. A inicialização ComfyUI e o uso de vídeo continuam sendo gates do build/GPU.
2. **Instalações pip separadas dificultavam uma resolução consistente.** ComfyUI, compiler e packs passam a entrar na mesma resolução. As versões instaladas de torch, torchvision e torchaudio continuam protegidas por constraints. O build grava `requirements-merged.txt`, `pip-install-report.json` e `python-resolved.txt`, além de executar `pip check`. Um `freeze` posterior não torna as dependências transitivas um lock reproduzível: a imagem aprovada deve ser publicada e consumida por digest, e seus relatórios preservados.
3. **Cache pip herdado ocupava `/workspace` durante o build.** A base define `PIP_CACHE_DIR=/workspace/.cache/pip`. O passo de instalação agora usa `PIP_NO_CACHE_DIR=1`, evitando gravar cache que seria ocultado pelo volume e aumentaria a imagem. Não alterei o cache de uso posterior do Pod.
4. **Configuração de ComfyUI inválida só falhava depois do download completo.** `H3MAX_COMFY_ARGS` passa a ser validado antes de criar diretórios ou baixar pesos. Não pode sobrescrever porta ou diretórios que fazem parte do contrato de healthcheck/persistência. Flags de CPU/memória continuam aceitas como argumentos sem interpretação de shell.
5. **Seleção de grupos e destinos precisava de validação antecipada.** O downloader aceita espaços ao redor de grupos, rejeita seleção vazia, checksums/revisões/tamanhos inválidos e destinos absolutos ou com travessia. Todos os destinos são resolvidos antes de qualquer download; links que escapem da raiz são rejeitados.
6. **Dois bootstraps no mesmo volume podiam disputar staging/recibos.** Um lock de arquivo agora impede downloads simultâneos na mesma raiz; o sistema operacional o libera quando o processo termina. A implementação Linux usa `flock`; Windows usa `msvcrt` somente para viabilizar testes locais. Em volume de rede o suporte efetivo ao lock precisa ser confirmado no Pod; erro causa falha explícita.
7. **Recibo truncado bloqueava a recuperação, e cache merecia reforço.** Um recibo JSON ilegível agora exige rehash dos pesos existentes, sem confiar no cache. O atalho de cache também exige tamanho igual ao manifesto. Arquivos já existentes que falham no checksum continuam preservados para inspeção; downloads com checksum errado nunca são promovidos ao destino final. `--verify-only` continua recalculando os hashes.

## Persistência e acesso

- Os diretórios modelos, input, output, user e temp são redirecionados corretamente para a raiz persistente. Workflows existentes não são sobrescritos em um reinício. O diretório original de placeholders do ComfyUI é preservado em `models.from-image`.
- `volumeInGb: 300` define um volume do Pod, não demonstra que há Network Volume anexado. A [documentação Runpod](https://docs.runpod.io/pods/storage/types) distingue o volume do Pod, perdido ao terminar o Pod, de um Network Volume independente. Para preservar os pesos ao recriar o Pod, anexar esse volume durante a criação no local `/workspace`.
- A base exige compatibilidade de host com CUDA 13.0. Selecionar GPU/host compatível e não desativar `NVIDIA_REQUIRE_CUDA` para contornar erro de driver. Memória, offload, duração e desempenho precisam de medição no preset desejado.
- ComfyUI é iniciado em `0.0.0.0:8188`. O pacote não implementa autenticação. `JUPYTER_PASSWORD` protege somente o Jupyter. Antes de disponibilizar mídia sensível ou compartilhar o serviço, validar o mecanismo de acesso escolhido (proxy autenticado aplicável ou túnel SSH). Abrir somente as portas utilizadas; 8888 e 22 são opcionais.
- O healthcheck de `/system_stats` indica serviço HTTP ativo; não prova carregamento dos pesos, importação de todos os nodes nem geração válida. O período inicial de 3.600 segundos é uma tolerância de cold start e não uma promessa de tempo de download.

## Build recomendado sem Docker local

A [documentação GitHub](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images) confirma publicação em GHCR com GitHub Actions e `GITHUB_TOKEN` com permissão de packages. Recomendo fluxo manual para essa etapa candidata:

1. Validar JSON/sintaxe, testes de integridade, template e workflows no runner.
2. Checar espaço livre e construir para `linux/amd64`. A base tem 10,53 GB comprimidos; planejar inicialmente pelo menos 45–50 GiB livres é uma margem operacional estimada, não um tamanho medido da imagem final. Usar runner maior se faltar espaço, sem depender de excluir ferramentas do sistema.
3. Carregar a imagem construída e testar inicialização com `H3MAX_DOWNLOAD_MODELS=0` e `--cpu`. Verificar o endpoint e os nodes usados. Nenhum peso deve ser baixado no CI.
4. Salvar logs, `pip check`, relatório pip, freeze, manifesto de fontes e configuração final da imagem. Publicar só a imagem exata que passou nos testes, com tag de versão/commit e digest.
5. Para GHCR privado, associar credencial de leitura ao registry do Runpod. Não embutir credenciais na imagem e não tornar pacote público como efeito colateral.
6. Preparar o template com a imagem por digest e o ambiente de armazenamento. Depois, no Pod de validação, confirmar GPU/driver, baixar/validar pesos, verificar `/object_info`, fazer geração pequena e uma geração representativa de cada caminho avançado selecionado. Somente então avaliar realismo/física e selecionar preset final.

## Verificação realizada e limitações

- **8 testes do downloader passaram** no Python 3.11 Windows: downloads e revisão fixada, checksum errado, preservação de arquivo corrompido, cache truncado, rehash explícito, destino inseguro, seleção de grupos e concorrência/liberação do lock.
- **2 testes de startup passaram**: validação antecipada e encaminhamento de flags. Um terceiro, que verifica a persistência e preservação do workflow com symlink real, ficou **skipped** porque este Windows não concede a permissão de criar symlinks; deve executar no Linux do GitHub Actions.
- Os três scripts editados passaram em análise sintática. O planejamento do grupo `h3` retornou 12 arquivos e 62,64 GB sem baixar pesos.
- Não executei pip das dependências de vídeo no PC, não executei Docker, não publiquei imagem, não criei ou liguei infraestrutura e não fiz inferência GPU. O build Linux, imports dos nodes, compatibilidade CUDA real, tempo/VRAM e qualidade visual continuam sem medição.
- A validação estática existente é útil, mas não comprova que cada campo dos JSONs corresponde ao schema de cada node instalado. A auditoria dos workflows e o gate de `/object_info` devem cobrir isso separadamente.
