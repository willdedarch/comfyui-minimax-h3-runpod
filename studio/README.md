# H3 Studio

Uma entrada única para MiniMax H3. O painel monta a geração e conecta as etapas selecionadas. Os oito workflows anteriores permanecem como material técnico; não são o modo de operação do Studio.

**Estado: integração local em verificação. Nenhum vídeo foi gerado neste computador e a qualidade ainda não foi aprovada em GPU.**

## Uso previsto no Runpod

Ao abrir a porta 8188, o Studio aparece automaticamente. Descreva a cena, anexe os materiais que quiser usar e gere. O modelo fica em Automático; não é preciso carregar um workflow, conectar nós ou repetir ajustes entre passagens.

- Texto e quadros inicial/final selecionam FL2VA.
- Referências selecionam Ref2VA. Imagens, vídeos com ou sem som e áudio têm entradas próprias.
- Movimento, aparência humana, câmera, detalhes e reparo temporal têm chaves independentes. O cenário escolhe a LoRA de movimento; pesos e segunda passagem ficam sincronizados.
- Câmera tem direção, velocidade e amplitude; enquadramento tem planos aberto, médio e próximo. Esses controles orientam o texto interpretado pelo H3. Câmera fixa desativa o reforço de movimento por LoRA.
- A saída pode conservar o áudio gerado ou ser salva sem faixa de áudio.
- A saída é um vídeo final com áudio, exibido no próprio painel e disponível para baixar. Semente, duração real e etapas ficam registradas para reprodução.
- Com melhoria ligada, o painel guarda o original e o resultado ajustado para comparação. Se a melhoria falhar, o original já salvo continua disponível.
- A biblioteca permite assistir, baixar, recuperar a receita inteira e cancelar uma geração específica. As receitas podem ser exportadas e reabertas; os arquivos de referência ficam no ambiente onde foram enviados.
- Materiais incompatíveis, arquivos ausentes e modelos não instalados interrompem a preparação com uma explicação. Nada é substituído silenciosamente.
- A área opcional **Etapas e nós** desenha o grafo real, permite inspecionar entradas e componentes e baixar o JSON. Não inicia uma geração ao consultar.

O ajuste de objetos, o Híbrido e o reparo temporal permanecem experimentais. A direção de texto precisa de um serviço configurado e, nesta integração, não interpreta referências. Pose/ControlNet, continuação, edição V2V e LTX não estão integrados ao painel; não são apresentados como recursos prontos por estarem no inventário.

## O que esta revisão corrigiu

Um compilador único substitui a escolha manual entre grafos. Formato, duração, sementes, referências, perfis e passes são preparados juntos. Referências de vídeo são verificadas antes da fila. O áudio final conserva a performance da geração inicial. A ampliação usa o tratamento de keyframes do upscaler fixado.

A pesquisa confrontou os dois consoles Director originais, MAINodes, a receita Turbo e os guias oficiais. A conclusão técnica e as fontes estão em [PESQUISA_INTEGRACAO.md](docs/PESQUISA_INTEGRACAO.md). OpenH3 não é o Context-IR oficial; a ampliação local não é o Regenerate-2K oficial. Não há comparação executada com Seedance 2.5.

## Construção e validação, a cargo da integração

A imagem é construída no GitHub Actions, sem Docker no computador do usuário. O build verifica dependências, inicialização em CPU, registro de nós, painel e contratos dos grafos gerados pelo Studio antes de permitir publicação. O template Runpod usa a imagem pelo digest. Os modelos e vídeos ficam no volume persistente.

O template reserva 300 GB em `/workspace` e oferece `HF_TOKEN` vazio para preencher no Runpod. Cache persistente e transferência Xet em modo de alto desempenho já vêm configurados. O token é usado apenas em tempo de execução. O primeiro download precede a abertura do painel e aparece nos registros do Pod.

A instrução técnica de publicação permanece em [BUILD_E_RUNPOD.md](docs/BUILD_E_RUNPOD.md). A execução em GPU e a avaliação visual das três famílias de cenas são etapas pendentes, não tarefas de configuração que o usuário precisa conduzir.

Para a revisão local da interface, `scripts/preview_studio.py` serve apenas a prévia em 127.0.0.1. Essa prévia prepara receitas, mas não envia arquivos, não executa modelos e não inventa vídeos de demonstração.

O inventário anterior permanece em [INVENTARIO_COMPLETO.md](docs/INVENTARIO_COMPLETO.md) como registro técnico do pacote e das omissões. Quando seus trechos descrevem operação manual dos oito workflows, referem-se à versão anterior, substituída pelo Studio.
