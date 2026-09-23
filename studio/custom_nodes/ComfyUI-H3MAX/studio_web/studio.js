(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const form = $('creation-form');
  const storageKey = 'h3studio:settings:v1';
  const activeJobKey = 'h3studio:job:v1';
  const toggleKeys = ['motion', 'people_realism', 'camera_motion', 'refine', 'temporal', 'director'];
  const featureLabels = {motion:'Ajuste de movimento', people_realism:'Realismo de pessoas', camera_motion:'Câmera', refine:'Mais definição', temporal:'Continuidade experimental', director:'Assistente de direção'};
  const modelLabels = {fl2va:'H3 · texto e quadros', ref2va:'H3 · referências', hybrid:'H3 · híbrido'};
  const sceneLabels = {natural:'Natural', action:'Ação corporal', objects:'Objetos e líquidos', weapon:'Ação com arma'};
  const cameraLabels = {auto:'Conforme a descrição',locked:'Fixa',push_in:'Aproxima',pull_out:'Afasta',tracking:'Acompanha',pan_left:'Pan para a esquerda',pan_right:'Pan para a direita',orbit:'Órbita'};
  const framingLabels = {auto:'Seguir descrição',wide:'Plano aberto',medium:'Plano médio',closeup:'Close'};
  const sceneNotes = {
    natural:'Prioriza movimentos humanos naturais quando o ajuste de movimento está ligado.',
    action:'Usa o ajuste de ação corporal. Descreva cada ação e contato na ordem em que devem ocorrer.',
    objects:'Ajuste experimental para relações espaciais. Líquidos e colisões ainda podem sair inconsistentes.',
    weapon:'Usa o ajuste específico para ação com arma. Descreva posição, trajetória e contato com clareza.'
  };
  const scenePreferences = Object.fromEntries(Object.keys(sceneLabels).map((scene) => [scene,
    Object.fromEntries(toggleKeys.map((key) => [key, key === 'motion' && scene !== 'objects']))
  ]));
  const mediaConfig = {
    first_frame:{list:'first-frame-list', slot:'first-frame-slot', input:'first-frame', max:1, kind:'image'},
    last_frame:{list:'last-frame-list', slot:'last-frame-slot', input:'last-frame', max:1, kind:'image'},
    references:{list:'references-list', input:'reference-images', max:9, kind:'image'},
    video_references:{list:'video-references-list', input:'reference-videos', max:3, kind:'video'},
    audio_references:{list:'audio-references-list', input:'reference-audio', max:3, kind:'audio'}
  };
  const media = Object.fromEntries(Object.keys(mediaConfig).map((key) => [key, []]));
  let capabilities = null;
  let busy = false;
  let uploadCount = 0;
  let lastSeed = null;
  let pollTimer = null;
  let activeJob = null;
  let displayedJob = null;
  let selectedJob = null;
  let libraryJobs = [];
  const referenceAudioByFile = new Map();
  let cancelling = false;
  let inspectorBusy = false;
  let inspectorGraph = null;
  let configurationRevision = 0;
  let resultFiles = [];
  let pollFailures = 0;
  let configurationChecked = false;
  const previewRequested = new URLSearchParams(window.location.search).get('preview') === '1';
  const clientId = (window.crypto && window.crypto.randomUUID) ? window.crypto.randomUUID() : `h3studio-${Date.now()}-${Math.random().toString(36).slice(2)}`;

  function storedRead(key) { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (_) { return null; } }
  function storedWrite(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* Storage is optional. */ } }
  function storedRemove(key) { try { localStorage.removeItem(key); } catch (_) { /* Storage is optional. */ } }
  function radio(name) { return form.querySelector(`input[name="${name}"]:checked`).value; }
  function hasReferences() { return media.references.length + media.video_references.length + media.audio_references.length > 0; }
  function hasFrames() { return media.first_frame.length + media.last_frame.length > 0; }
  function selectedModel() { return $('model').value === 'auto' ? (hasReferences() ? 'ref2va' : 'fl2va') : $('model').value; }
  function isPreview() { return previewRequested || Boolean(capabilities && capabilities.preview); }
  function modelState(model) {
    const state = capabilities && capabilities.models && capabilities.models[model];
    return typeof state === 'boolean' ? {available:state} : state || {available:true};
  }

  function errorMessage(payload, fallback) {
    if (typeof payload === 'string') return payload;
    if (payload && typeof payload.message === 'string') return payload.message;
    if (payload && typeof payload.error === 'string') return payload.error;
    if (payload && payload.error && typeof payload.error.message === 'string') return payload.error.message;
    if (payload && typeof payload.detail === 'string') return payload.detail;
    if (payload && payload.node_errors) {
      const errors = Object.values(payload.node_errors).flatMap((item) => item.errors || []);
      if (errors.length) return errors.map((item) => item.details || item.message || 'Configuração incompatível.').join('\n');
    }
    return fallback;
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, {...options, credentials:'same-origin'});
    let data;
    try { data = await response.json(); } catch (_) { throw new Error('O servidor respondeu de forma inesperada. Verifique se o ambiente do Studio está aberto.'); }
    // A persisted job can legitimately contain its execution error.
    if (!response.ok || (data && data.error && !data.id)) {
      const error = new Error(errorMessage(data, `O servidor não concluiu a solicitação (${response.status}).`));
      error.status = response.status; throw error;
    }
    return data;
  }

  function setError(message) {
    $('form-error').textContent = message || '';
    $('form-error').hidden = !message;
  }

  function setStatus(title, detail, state = '') {
    $('session-title').textContent = title;
    $('session-detail').textContent = detail;
    $('session-status').className = `session-status ${state}`;
  }

  function featureState(key) {
    const features = (capabilities && capabilities.features) || {};
    let feature = features[key];
    if (typeof feature === 'boolean') feature = {available:feature};
    if (!feature) {
      if (key === 'director') return {available:Boolean(capabilities && capabilities.director_available), reason:'Conecte o assistente de direção no ambiente para habilitar.'};
      if (key === 'video_references' || key === 'audio_references') return {available:false, reason:'Recurso ainda não integrado neste ambiente.'};
      feature = {available:true};
    }
    if (key === 'director' && hasReferences()) return {...feature, available:false, reason:'O assistente ainda não analisa referências. Desligue-o para usar suas mídias.'};
    if (key === 'camera_motion' && $('camera').value === 'locked') return {...feature,available:false,reason:'Câmera fixa: o reforço de movimento fica desligado. Sua preferência será recuperada ao escolher outra direção.'};
    if (key === 'motion' && capabilities && capabilities.scenes) {
      const scene = capabilities.scenes[radio('scene')];
      if (scene === false || (scene && scene.available === false)) return {available:false, reason:scene.reason || 'O ajuste deste tipo de cena ainda não está disponível neste ambiente. Você pode gerar com o modelo base.'};
    }
    if (key === 'director' && (!capabilities || !capabilities.director_available)) return {...feature, available:false, reason:feature.reason || 'Assistente de direção não configurado neste ambiente.'};
    if (key === 'temporal' && media.last_frame.length) return {...feature, available:false, reason:'A imagem final precisa manter sua posição; este reparo temporal ainda não preserva essa âncora.'};
    if (['people_realism','camera_motion'].includes(key) && radio('scene') === 'weapon' && $('motion').checked) return {...feature, available:false, reason:'Desligado neste perfil: o ajuste de ação com arma é usado sozinho. Sua preferência nos outros perfis foi mantida.'};
    if (Array.isArray(feature.models) && !feature.models.includes(selectedModel())) return {...feature, available:false, reason:feature.reason || 'Este ajuste não está disponível para o modelo escolhido.'};
    return {available:feature.available !== false, reason:feature.reason || '', ...feature};
  }

  function updateCompatibility() {
    $('camera-detail-controls').hidden = ['auto','locked'].includes($('camera').value);
    for (const option of $('model').options) {
      const state = modelState(option.value);
      option.disabled = state.available === false;
      option.title = state.reason || '';
    }
    toggleKeys.forEach((key) => {
      const state = featureState(key);
      const row = document.querySelector(`[data-feature="${key}"]`);
      const reason = row.querySelector('.feature-reason');
      // The visible switch and submitted value always match. Preferences are
      // retained separately for each scene, so compatibility needs no cleanup.
      $(key).checked = state.available && scenePreferences[radio('scene')][key];
      $(key).disabled = !state.available;
      row.classList.toggle('unavailable', !state.available);
      reason.textContent = state.reason || 'Desligado nesta configuração por incompatibilidade.';
      reason.hidden = state.available;
    });
    for (const [key, config] of Object.entries(mediaConfig)) {
      const available = featureState(key).available;
      $(config.input).disabled = !available;
    }
    const videoAvailable = featureState('video_references').available;
    const audioAvailable = featureState('audio_references').available;
    $('video-reference-group').hidden = !capabilities;
    $('audio-reference-group').hidden = !capabilities;
    $('extra-references').hidden = !capabilities;
    for (const kind of ['video','audio']) {
      const state = featureState(`${kind}_references`);
      $(`${kind}-reference-reason`).hidden = state.available;
      $(`${kind}-reference-reason`).textContent = state.reason || 'Este tipo de referência ainda não está pronto neste ambiente.';
    }
    $('reference-media-note').hidden = !videoAvailable && !audioAvailable;
    const warnings = [];
    const selectedState = modelState(selectedModel());
    if (selectedState.available === false) warnings.push(selectedState.reason || 'O modelo necessário para esta cena não está disponível no ambiente.');
    if (hasReferences() && hasFrames()) warnings.push('Há quadros definidos e referências ao mesmo tempo. Remova um dos grupos para continuar; seus arquivos foram preservados.');
    if ($('model').value === 'fl2va' && hasReferences()) warnings.push('As referências exigem H3 referências ou híbrido. Escolha Automático para o Studio ajustar o modelo.');
    if (['ref2va', 'hybrid'].includes($('model').value) && hasFrames()) warnings.push('Este modelo usa referências, não imagens de começo e fim. Escolha Automático ou remova os quadros.');
    if (['ref2va', 'hybrid'].includes($('model').value) && !hasReferences()) warnings.push('Adicione uma referência para usar este modelo ou escolha Automático.');
    if (media.audio_references.length && !media.references.length && !media.video_references.length) warnings.push('Áudio de referência precisa acompanhar pelo menos uma imagem ou um vídeo de referência.');
    if (media.references.length + media.video_references.length + media.audio_references.length > 12) warnings.push('Use no máximo 12 referências no total. Remova os arquivos excedentes para continuar.');
    $('media-warning').textContent = warnings.join(' ');
    $('media-warning').hidden = !warnings.length;
  }

  function saveSettings() {
    const settings = {prompt:$('scene-prompt').value, scene:radio('scene'), aspect:radio('aspect'), duration:$('duration').value, model:$('model').value, camera:$('camera').value, camera_speed:$('camera-speed').value, camera_amount:$('camera-amount').value, framing:$('framing').value, output_audio:$('output-audio').checked, seed:$('seed').value, scene_preferences:scenePreferences};
    toggleKeys.forEach((key) => { settings[key] = $(key).checked; });
    storedWrite(storageKey, settings);
  }

  function restoreSettings() {
    const settings = storedRead(storageKey);
    if (!settings || typeof settings !== 'object') return;
    if (typeof settings.prompt === 'string') $('scene-prompt').value = settings.prompt.slice(0, 12000);
    ['scene','aspect'].forEach((key) => {
      const match = Array.from(form.querySelectorAll(`input[name="${key}"]`)).find((input) => input.value === settings[key]);
      if (match) match.checked = true;
    });
    ['duration','model'].forEach((key) => { if (Array.from($(key).options).some((option) => option.value === settings[key])) $(key).value = settings[key]; });
    for (const key of ['camera','camera_speed','camera_amount','framing']) { const field = $(key.replaceAll('_','-')); if (Array.from(field.options).some((option) => option.value === settings[key])) field.value = settings[key]; }
    if (typeof settings.output_audio === 'boolean') $('output-audio').checked = settings.output_audio;
    if (typeof settings.seed === 'string' && /^\d{0,16}$/.test(settings.seed)) $('seed').value = settings.seed;
    if (settings.scene_preferences && typeof settings.scene_preferences === 'object') {
      for (const scene of Object.keys(sceneLabels)) {
        const preferences = settings.scene_preferences[scene];
        if (preferences && typeof preferences === 'object') toggleKeys.forEach((key) => { if (typeof preferences[key] === 'boolean') scenePreferences[scene][key] = preferences[key]; });
      }
    } else {
      toggleKeys.forEach((key) => { if (typeof settings[key] === 'boolean') scenePreferences[radio('scene')][key] = settings[key]; });
    }
  }

  function updateButton() {
    const canCheck = capabilities && (capabilities.runtime_ready || isPreview());
    $('generate-button').disabled = Boolean(busy || uploadCount || !canCheck);
    $('export-recipe').disabled = Boolean(uploadCount);
    $('import-recipe').disabled = Boolean(uploadCount);
    $('cancel-job').hidden = !activeJob || !busy || isPreview() || !['queued','running'].includes(activeJob.status);
    $('cancel-job').disabled = cancelling;
    $('cancel-job').textContent = cancelling ? 'Cancelando…' : 'Cancelar esta geração';
    updateInspectorButtons();
    $('generate-label').textContent = busy ? 'Acompanhando geração' : uploadCount ? 'Enviando referências' : isPreview() ? 'Verificar configuração' : 'Gerar vídeo';
    if (busy) $('submit-note').textContent = 'Você pode preparar os ajustes do próximo vídeo enquanto acompanha este.';
    else if (isPreview()) $('submit-note').textContent = 'Confira os controles nesta prévia. A geração requer o ambiente com GPU.';
    else if (capabilities && capabilities.runtime_ready) $('submit-note').textContent = 'O vídeo será gerado neste ambiente. A duração depende dos ajustes e da GPU.';
    else $('submit-note').textContent = (capabilities && capabilities.message) || 'A geração será habilitada quando o ambiente com GPU estiver pronto.';
  }

  function updateSummary() {
    configurationRevision += 1;
    if (inspectorGraph && inspectorGraph.source === 'prepared') clearInspector('Configuração alterada. Use Ver configuração atual para atualizar as etapas e os nós.');
    if (configurationChecked && isPreview()) setStatus('Configuração alterada.', 'Verifique a nova configuração para conferir o modelo e os ajustes escolhidos.');
    configurationChecked = false;
    updateCompatibility();
    const model = selectedModel();
    const scene = radio('scene');
    const aspect = radio('aspect');
    const duration = $('duration').value;
    $('prompt-count').textContent = `${$('scene-prompt').value.length.toLocaleString('pt-BR')} / 12.000`;
    $('scene-note').textContent = scene === 'objects' && !$('motion').checked ? 'O ajuste espacial é experimental e começa desligado. Você pode ligá-lo em Ajustar movimento; não garante colisões ou líquidos corretos.' : sceneNotes[scene];
    $('recipe-model').textContent = modelLabels[model];
    $('recipe-scene').textContent = $('motion').checked && featureState('motion').available ? sceneLabels[scene] : 'Modelo base';
    $('recipe-output').textContent = `${aspect} · ~${duration} segundos`;
    const sizes = $('refine').checked && featureState('refine').available ? {'16:9':[1664,960], '9:16':[960,1664], '1:1':[1248,1248]} : {'16:9':[1280,736], '9:16':[736,1280], '1:1':[960,960]};
    $('recipe-resolution').textContent = sizes[aspect].join(' × ');
    if (!activeJob && !resultFiles.length) $('monitor-format').textContent = `${sizes[aspect].join(' × ')} · ~${duration} s`;
    $('recipe-tags').replaceChildren();
    const enabled = toggleKeys.filter((key) => $(key).checked && featureState(key).available);
    for (const key of enabled) { const chip = document.createElement('span'); chip.textContent = featureLabels[key]; $('recipe-tags').append(chip); }
    if ($('camera').value !== 'auto') { const chip = document.createElement('span'); chip.textContent = `Câmera: ${cameraLabels[$('camera').value]}`; $('recipe-tags').append(chip); }
    if ($('framing').value !== 'auto') { const chip = document.createElement('span'); chip.textContent = framingLabels[$('framing').value]; $('recipe-tags').append(chip); }
    if (!$('output-audio').checked) { const chip = document.createElement('span'); chip.textContent = 'Sem faixa de áudio'; $('recipe-tags').append(chip); }
    if (!enabled.length) { const chip = document.createElement('span'); chip.textContent = 'Modelo base'; $('recipe-tags').append(chip); }
    $('model-explanation').textContent = $('model').value === 'auto' ? 'O Studio escolhe o modelo a partir das imagens e referências.' : 'Modelo fixado por você. A compatibilidade é conferida antes da geração.';
    $('recipe-label').textContent = 'Configuração';
    $('recipe-note').textContent = $('model').value === 'auto' ? 'A escolha automática acompanha suas referências.' : 'A escolha manual será preservada.';
    $('prepared-details').hidden = true;
    if (lastSeed !== null) $('reuse-seed').textContent = 'Reutilizar a semente da configuração anterior';
    updateButton();
  }

  function formatSize(size) { return size < 1024 * 1024 ? `${Math.ceil(size / 1024)} KB` : `${(size / 1024 / 1024).toFixed(1)} MB`; }
  function inputMediaUrl(filename) {
    const slash = filename.lastIndexOf('/');
    return `/view?${new URLSearchParams({filename:filename.slice(slash + 1), subfolder:slash < 0 ? '' : filename.slice(0, slash), type:'input'})}`;
  }
  function releaseMedia(item) { if (item.url && item.url.startsWith('blob:')) URL.revokeObjectURL(item.url); }
  function rememberReferenceMetadata(summary) {
    const videos = summary && summary.reference_media && summary.reference_media.video_references;
    if (Array.isArray(videos)) for (const item of videos) {
      if (item && typeof item.filename === 'string' && typeof item.has_audio === 'boolean') referenceAudioByFile.set(item.filename, item.has_audio);
    }
  }
  function videoHasAudio(item) { return typeof item.has_audio === 'boolean' ? item.has_audio : referenceAudioByFile.get(item.uploaded); }
  function referenceTags(key, index) {
    if (key === 'references') return [`<Picture ${index + 1}>`];
    if (key === 'video_references') {
      const tags = [`<Video ${index + 1}>`];
      const previous = media.video_references.slice(0, index).map(videoHasAudio);
      if (videoHasAudio(media.video_references[index]) === true && previous.every((value) => typeof value === 'boolean')) tags.push(`<Audio ${previous.filter(Boolean).length + 1}>`);
      return tags;
    }
    if (key === 'audio_references') {
      const soundtracks = media.video_references.map(videoHasAudio);
      return soundtracks.every((value) => typeof value === 'boolean') ? [`<Audio ${soundtracks.filter(Boolean).length + index + 1}>`] : [];
    }
    return [];
  }
  function refreshReferenceLabels() {
    for (const key of ['references','video_references','audio_references']) renderMedia(key);
    $('reference-label-note').hidden = !hasReferences();
    const unknownAudio = media.audio_references.length && media.video_references.some((item) => typeof videoHasAudio(item) !== 'boolean');
    $('reference-label-note').textContent = unknownAudio ? 'Use os rótulos exibidos na descrição. O número dos áudios será confirmado após verificar o som dos vídeos; esta receita ainda não tem essa informação.' : 'Use estes rótulos na descrição para indicar cada referência. Ex.: a pessoa de <Picture 1> segue o movimento de <Video 1>. Áudios dos vídeos entram na numeração antes dos áudios separados.';
  }
  function referenceTagSnapshot() {
    const snapshot = new Map();
    for (const key of ['references','video_references','audio_references']) media[key].forEach((item,index) => snapshot.set(item,referenceTags(key,index)));
    return snapshot;
  }
  function warnReferenceRenumbering(before) {
    const after = referenceTagSnapshot();
    const prompt = $('scene-prompt').value;
    const changed = [...before].some(([item,tags]) => tags.some((tag,index) => prompt.includes(tag) && (!after.has(item) || after.get(item)[index] !== tag)));
    if (changed) setError('As referências mudaram de número e sua descrição ainda menciona um rótulo anterior. Confira os rótulos nos arquivos; o texto da cena foi preservado.');
  }
  function renderMedia(key) {
    const config = mediaConfig[key];
    const list = $(config.list);
    list.replaceChildren();
    for (const [index, item] of media[key].entries()) {
      const row = document.createElement('div'); row.className = `media-item${item.error ? ' media-error' : ''}`;
      const filename = item.file ? item.file.name : item.uploaded.split('/').pop();
      if (config.kind === 'image') { const thumbnail = document.createElement('img'); thumbnail.src = item.url; thumbnail.alt = `Referência: ${filename}`; row.append(thumbnail); }
      else { const icon = document.createElement('span'); icon.className = 'media-placeholder'; icon.textContent = config.kind === 'video' ? 'VÍDEO' : 'ÁUDIO'; row.append(icon); }
      const info = document.createElement('span'); info.className = 'media-info';
      const tags = referenceTags(key,index);
      if (tags.length) { const labels = document.createElement('span'); labels.className = 'reference-tags'; for (const tag of tags) { const label = document.createElement('code'); label.textContent = tag; labels.append(label); } info.append(labels); }
      const name = document.createElement('strong'); name.textContent = filename;
      const status = document.createElement('small'); status.textContent = item.error || (item.uploading ? 'Enviando…' : item.uploaded ? (item.file ? `${formatSize(item.file.size)} · Enviado` : 'Já enviado neste ambiente') : 'Prévia local · não enviado');
      info.append(name, status); row.append(info);
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'media-remove'; remove.textContent = '×'; remove.setAttribute('aria-label', `Remover ${filename}`);
      remove.addEventListener('click', () => { const before = referenceTagSnapshot(); media[key] = media[key].filter((candidate) => candidate !== item); releaseMedia(item); renderMedia(key); refreshReferenceLabels(); warnReferenceRenumbering(before); updateSummary(); });
      row.append(remove); list.append(row);
    }
    if (config.slot) $(config.slot).classList.toggle('has-media', Boolean(media[key].length));
  }

  async function uploadItem(key, item) {
    const config = mediaConfig[key];
    if (isPreview()) return;
    item.uploading = true; uploadCount += 1; renderMedia(key); updateButton();
    try {
      const body = new FormData();
      if (config.kind === 'image') {
        const extension = item.file.name.split('.').pop().toLowerCase();
        const uploadName = `h3studio_${Date.now()}_${Math.random().toString(36).slice(2)}.${extension}`;
        body.append('image', item.file, uploadName);
      } else body.append('file', item.file);
      body.append('type', 'input'); body.append('overwrite', 'false');
      const result = await fetchJson(config.kind === 'image' ? '/upload/image' : '/h3max/api/upload', {method:'POST', body});
      if (!result || typeof result.name !== 'string') throw new Error('O envio não retornou um arquivo válido. Remova o arquivo e tente novamente.');
      item.uploaded = result.subfolder ? `${result.subfolder}/${result.name}` : result.name;
      if (typeof result.has_audio === 'boolean') { item.has_audio = result.has_audio; referenceAudioByFile.set(item.uploaded,result.has_audio); }
    } catch (error) { item.error = error.message; setError(error.message); }
    finally { item.uploading = false; uploadCount -= 1; renderMedia(key); refreshReferenceLabels(); updateSummary(); }
  }

  async function addMedia(key, files) {
    const config = mediaConfig[key];
    setError('');
    if (files.length + media[key].length > config.max) { setError(`Este campo aceita no máximo ${config.max} ${config.kind === 'image' ? 'imagem(ns)' : 'arquivo(s)'}. Remova um arquivo antes de adicionar mais.`); return; }
    for (const file of files) {
      const maxSize = config.kind === 'image' ? 30 * 1024 * 1024 : 256 * 1024 * 1024;
      if (file.size > maxSize) { setError(`O arquivo ${file.name} excede o limite de ${config.kind === 'image' ? '30 MB' : '256 MB'} deste painel.`); continue; }
      if (file.type && !file.type.startsWith(`${config.kind}/`)) { setError(`O arquivo ${file.name} não tem o tipo esperado para este campo.`); continue; }
      const item = {file, url:URL.createObjectURL(file), uploaded:null, uploading:false, error:null};
      media[key].push(item); renderMedia(key); refreshReferenceLabels(); updateSummary();
      await uploadItem(key, item);
    }
  }

  function buildRequest() {
    const prompt = $('scene-prompt').value.trim();
    if (!prompt) throw new Error('Descreva a cena antes de continuar.');
    if (hasFrames() && hasReferences()) throw new Error('Use imagens inicial/final ou referências nesta geração. Remova um dos grupos para continuar.');
    if (!$('media-warning').hidden) throw new Error($('media-warning').textContent);
    const unavailable = toggleKeys.filter((key) => $(key).checked && !featureState(key).available);
    if (unavailable.length) throw new Error(`O ajuste “${featureLabels[unavailable[0]]}” foi preservado, mas está indisponível nesta configuração. Escolha uma configuração compatível ou desmarque-o antes de continuar.`);
    const request = {prompt, model:$('model').value, camera:$('camera').value, camera_speed:$('camera-speed').value, camera_amount:$('camera-amount').value, framing:$('framing').value, output_audio:$('output-audio').checked, scene:radio('scene'), aspect:radio('aspect'), duration:Number($('duration').value)};
    toggleKeys.forEach((key) => { request[key] = $(key).checked; });
    if ($('seed').value !== '') {
      const seed = Number($('seed').value);
      if (!Number.isSafeInteger(seed) || seed < 0) throw new Error('Use uma semente inteira de 0 a 9007199254740991 ou deixe o campo vazio.');
      request.seed = seed;
    }
    for (const [key, items] of Object.entries(media)) {
      if (items.some((item) => !item.uploaded)) throw new Error(isPreview() ? 'Os arquivos desta prévia ainda não foram enviados. Para conferir uma configuração com mídias, abra o Studio no ambiente com GPU.' : 'Há arquivos que não terminaram de enviar. Remova os arquivos com erro e envie-os novamente.');
      request[key] = mediaConfig[key].max === 1 ? (items[0] ? items[0].uploaded : null) : items.map((item) => item.uploaded);
    }
    return request;
  }

  function applyPreparedSummary(summary, request, preview) {
    configurationChecked = true;
    const data = summary && typeof summary === 'object' ? summary : {};
    rememberReferenceMetadata(data); refreshReferenceLabels();
    const model = data.engine || data.model || data.selected_model || selectedModel();
    $('recipe-model').textContent = modelLabels[model] || model;
    $('recipe-scene').textContent = request.motion ? (sceneLabels[request.scene] || 'Natural') : 'Modelo base';
    $('recipe-tags').replaceChildren();
    const applied = toggleKeys.filter((key) => request[key] === true);
    for (const key of applied) { const chip = document.createElement('span'); chip.textContent = featureLabels[key]; $('recipe-tags').append(chip); }
    if (request.camera && request.camera !== 'auto') { const chip = document.createElement('span'); chip.textContent = `Câmera: ${data.camera_label || cameraLabels[request.camera] || request.camera}`; $('recipe-tags').append(chip); }
    if (request.framing && request.framing !== 'auto') { const chip = document.createElement('span'); chip.textContent = framingLabels[request.framing] || request.framing; $('recipe-tags').append(chip); }
    if (request.output_audio === false) { const chip = document.createElement('span'); chip.textContent = 'Sem faixa de áudio'; $('recipe-tags').append(chip); }
    if (!applied.length) { const chip = document.createElement('span'); chip.textContent = 'Modelo base'; $('recipe-tags').append(chip); }
    if (data.width && data.height) $('recipe-resolution').textContent = `${data.width} × ${data.height}`;
    if (typeof data.seconds === 'number') $('recipe-output').textContent = `${request.aspect || radio('aspect')} · ${data.seconds.toLocaleString('pt-BR', {maximumFractionDigits:2})} segundos`;
    if (data.width && data.height && typeof data.seconds === 'number') $('monitor-format').textContent = `${data.width} × ${data.height} · ${data.seconds.toLocaleString('pt-BR', {maximumFractionDigits:2})} s`;
    const seed = data.seed !== undefined ? data.seed : request.seed;
    lastSeed = Number.isSafeInteger(Number(seed)) && seed !== undefined && seed !== null ? Number(seed) : null;
    $('reuse-seed').hidden = lastSeed === null;
    $('recipe-label').textContent = preview ? 'Conferida localmente' : 'Enviada para geração';
    $('recipe-note').textContent = lastSeed === null ? 'A configuração foi conferida pelo ambiente.' : `Semente ${preview ? 'desta configuração' : 'deste vídeo'}: ${lastSeed}. Use o botão abaixo para repetir.`;
    $('reuse-seed').textContent = `Reutilizar a semente ${preview ? 'desta configuração' : 'deste resultado'}`;
    $('prepared-notes').replaceChildren();
    const notes = Array.isArray(data.notes) ? data.notes : [];
    for (const note of notes) { const item = document.createElement('li'); item.textContent = String(note); $('prepared-notes').append(item); }
    $('prepared-details').hidden = !notes.length;
  }

  async function submit(event) {
    event.preventDefault();
    if (busy || uploadCount) return;
    setError('');
    try {
      if (!capabilities || (!capabilities.runtime_ready && !isPreview())) throw new Error('O ambiente com GPU ainda não está pronto para gerar.');
      const request = buildRequest();
      busy = true; updateButton(); $('generate-label').textContent = 'Conferindo configuração';
      setStatus('Conferindo sua cena.', 'Verificando modelo, referências e ajustes antes de gerar.', 'working');
      if (isPreview() || !capabilities.runtime_ready) {
        const prepared = await fetchJson('/h3max/api/prepare', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(request)});
        applyPreparedSummary(prepared.summary, request, true);
        setStatus('Configuração conferida.', 'Esta é uma prévia local: nenhum vídeo foi gerado. A execução e a qualidade ainda precisam ser verificadas na GPU.', 'success');
        $('monitor-caption').textContent = 'Prévia da interface · geração indisponível';
        busy = false; updateButton(); return;
      }
      const queued = await fetchJson('/h3max/api/jobs', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({request, client_id:clientId})});
      if (!queued.prompt_id) throw new Error('O ambiente não confirmou a entrada do vídeo na fila.');
      activeJob = {id:queued.prompt_id, status:'queued', summary:queued.summary, request:queued.request || request, created_at:new Date().toISOString(), outputs:[]};
      selectJob(activeJob);
      applyPreparedSummary(activeJob.summary, activeJob.request, false);
      storedWrite(activeJobKey, activeJob);
      setStatus('Seu vídeo está na fila.', 'A geração começa assim que a GPU estiver disponível.', 'working');
      $('monitor-caption').textContent = 'Aguardando início da geração';
      pollFailures = 0; updateButton(); loadLibrary(); schedulePoll(800);
      if (window.matchMedia('(max-width: 820px)').matches) $('monitor-screen').scrollIntoView({behavior:'smooth', block:'center'});
    } catch (error) { busy = false; updateButton(); setError(error.message); setStatus('A geração não começou.', error.message, 'error'); }
  }

  function schedulePoll(delay = 2500) { clearTimeout(pollTimer); pollTimer = setTimeout(pollJob, delay); }
  function videoStage(file) { return /_base(?:_|\.|$)/i.test(file.filename) ? 'base' : /_final(?:_|\.|$)/i.test(file.filename) ? 'final' : 'other'; }
  function orderVideos(files) {
    const order = {base:0,other:1,final:2};
    return files.sort((left,right) => order[videoStage(left)] - order[videoStage(right)]);
  }
  function outputVideos(outputs) {
    if (Array.isArray(outputs)) return orderVideos(outputs.filter((file) => file && typeof file.filename === 'string' && /\.(mp4|webm|mov|mkv)$/i.test(file.filename)));
    const files = [];
    for (const output of Object.values(outputs || {})) {
      for (const key of ['videos','gifs','images']) {
        for (const file of (Array.isArray(output[key]) ? output[key] : [])) {
          if (file && typeof file.filename === 'string' && /\.(mp4|webm|mov|mkv)$/i.test(file.filename) && !files.some((item) => item.filename === file.filename && item.subfolder === file.subfolder)) files.push(file);
        }
      }
    }
    return orderVideos(files);
  }

  function showVideo(file, index) {
    const url = `/view?${new URLSearchParams({filename:file.filename, subfolder:file.subfolder || '', type:file.type || 'output'})}`;
    $('empty-screen').hidden = true;
    $('result-video').hidden = false;
    $('result-video').src = url;
    $('download-video').href = url;
    $('download-video').download = file.filename;
    $('download-video').textContent = /\.mp4$/i.test(file.filename) ? 'Baixar MP4 ↓' : 'Baixar vídeo ↓';
    $('download-video').hidden = false;
    const partial = displayedJob && ['error','cancelled','unknown'].includes(displayedJob.status);
    $('monitor-caption').textContent = `${partial ? 'Arquivo preservado · ' : ''}${file.filename}`;
    Array.from($('result-versions').children).forEach((button, buttonIndex) => { button.setAttribute('aria-pressed', String(buttonIndex === index)); });
  }

  function showJobOutputs(job) {
    displayedJob = job;
    selectJob(job);
    resultFiles = outputVideos(job.outputs);
    $('result-versions').replaceChildren();
    $('result-versions').hidden = resultFiles.length < 2;
    const hasBase = resultFiles.some((file) => videoStage(file) === 'base');
    resultFiles.forEach((file, index) => {
      const stage = videoStage(file);
      const label = stage === 'base' ? 'Original' : stage === 'final' ? (hasBase ? 'Com ajustes' : 'Resultado') : `Saída ${index + 1}`;
      const button = document.createElement('button'); button.type = 'button'; button.textContent = label; button.title = file.filename; button.setAttribute('aria-pressed','false'); button.addEventListener('click', () => showVideo(file, index)); $('result-versions').append(button);
    });
    if (resultFiles.length) {
      applyPreparedSummary(job.summary, job.request || {}, false);
      const namedFinalIndex = resultFiles.findIndex((file) => videoStage(file) === 'final');
      const finalIndex = namedFinalIndex < 0 ? resultFiles.length - 1 : namedFinalIndex;
      showVideo(resultFiles[finalIndex], finalIndex);
      $('recipe-label').textContent = ['error','cancelled','unknown'].includes(job.status) ? 'Execução incompleta' : 'Vídeo selecionado';
    }
    updateInspectorButtons();
  }

  function finishJob(job) {
    activeJob = job; busy = false; pollFailures = 0; storedRemove(activeJobKey);
    selectJob(job);
    if (outputVideos(job.outputs).length) showJobOutputs(job);
    if (job.status === 'success') {
      if (outputVideos(job.outputs).length) setStatus('Seu vídeo está pronto.', 'Assista, baixe ou reutilize a receita completa em Seus vídeos.', 'success');
      else setStatus('A execução terminou sem um vídeo.', 'O ambiente não retornou um arquivo de vídeo. Consulte os registros da execução.', 'error');
    } else if (job.status === 'cancelled') setStatus('Geração cancelada.', 'Os vídeos já concluídos continuam na sua biblioteca. Você pode ajustar a cena e gerar novamente.');
    else if (job.status === 'unknown') setStatus('Geração sem execução ativa.', 'O ambiente não encontrou esta geração na fila. A receita foi preservada; você pode reutilizá-la para tentar novamente.');
    else { const message = errorMessage(job.error, 'O ambiente não concluiu a geração. A receita foi preservada para tentar novamente.'); setError(message); setStatus('A geração não foi concluída.', message, 'error'); }
    updateButton();
    loadLibrary();
  }

  async function pollJob() {
    if (!activeJob || !busy) return;
    const requestedId = activeJob.id;
    try {
      const job = await fetchJson(`/h3max/api/jobs/${encodeURIComponent(requestedId)}`);
      if (!activeJob || activeJob.id !== requestedId || !busy) return;
      pollFailures = 0;
      activeJob = job; storedWrite(activeJobKey, job); updateButton();
      if (['success','error','cancelled','unknown'].includes(job.status)) { finishJob(job); return; }
      if (job.status === 'running') { setStatus('Gerando seu vídeo.', 'O tempo varia com a GPU e os ajustes. O vídeo aparece aqui quando estiver pronto.', 'working'); $('monitor-caption').textContent = 'Geração em andamento'; }
      else setStatus('Seu vídeo está na fila.', 'A geração começa assim que a GPU estiver disponível.', 'working');
      const index = libraryJobs.findIndex((item) => item.id === job.id);
      if (index >= 0) libraryJobs[index] = job; else libraryJobs.unshift(job);
      renderLibrary();
      schedulePoll();
    } catch (error) {
      if (!activeJob || activeJob.id !== requestedId || !busy) return;
      if (error.status === 404) { finishJob({...activeJob,status:'unknown'}); return; }
      pollFailures += 1;
      setStatus('Reconectando ao ambiente.', 'A geração pode continuar na GPU. Este painel tentará recuperar o resultado automaticamente.', 'working');
      schedulePoll(Math.min(15000, 2500 * pollFailures));
    }
  }

  async function cancelJob() {
    if (!activeJob || !busy || cancelling || isPreview()) return;
    const id = activeJob.id;
    cancelling = true; updateButton(); setError('');
    try {
      const result = await fetchJson(`/h3max/api/jobs/${encodeURIComponent(id)}/cancel`, {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
      setStatus(result.cancelled ? 'Cancelamento solicitado.' : 'Geração atualizada.', result.message || 'Verificando o estado final desta geração.', result.cancelled ? '' : 'working');
      if (activeJob && activeJob.id === id) schedulePoll(150);
    } catch (error) { setError(error.message); }
    finally { cancelling = false; updateButton(); }
  }

  function cleanRecipe(value) {
    const allowed = new Set(['prompt','model','scene','aspect','duration','seed','camera','camera_speed','camera_amount','framing','output_audio',...toggleKeys,...Object.keys(mediaConfig)]);
    if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some((key) => !allowed.has(key))) throw new Error('A receita contém campos não reconhecidos. Abra um arquivo salvo pelo H3 Studio.');
    if (typeof value.prompt !== 'string' || !value.prompt.trim() || value.prompt.length > 12000) throw new Error('A receita precisa conter uma cena com até 12.000 caracteres.');
    const recipe = {prompt:value.prompt.trim()};
    const choices = {model:['auto','fl2va','ref2va','hybrid'], scene:Object.keys(sceneLabels), aspect:['16:9','9:16','1:1']};
    for (const [key, options] of Object.entries(choices)) {
      if (!options.includes(value[key])) throw new Error(`A receita contém uma opção inválida para ${key}.`);
      recipe[key] = value[key];
    }
    const cameraFields = {camera:[Object.keys(cameraLabels),'auto'],camera_speed:[['slow','normal','fast'],'slow'],camera_amount:[['subtle','medium','wide'],'subtle'],framing:[Object.keys(framingLabels),'auto']};
    for (const [key,[options,fallback]] of Object.entries(cameraFields)) {
      const selected = value[key] === undefined ? fallback : value[key];
      if (!options.includes(selected)) throw new Error('A receita contém uma direção de câmera inválida.');
      recipe[key] = selected;
    }
    recipe.output_audio = value.output_audio === undefined ? true : value.output_audio;
    if (typeof recipe.output_audio !== 'boolean') throw new Error('O controle de áudio da receita precisa estar ligado ou desligado.');
    if (![5,10].includes(value.duration)) throw new Error('A duração da receita deve ser 5 ou 10 segundos.');
    recipe.duration = value.duration;
    if (value.seed !== undefined && value.seed !== null) {
      if (!Number.isSafeInteger(value.seed) || value.seed < 0) throw new Error('A semente da receita é inválida.');
      recipe.seed = value.seed;
    }
    for (const key of toggleKeys) {
      if (typeof value[key] !== 'boolean') throw new Error('A receita precisa indicar quais ajustes estão ligados.');
      recipe[key] = value[key];
    }
    const extensions = {image:/\.(png|jpe?g|webp|bmp|tiff?)$/i, video:/\.(mp4|mov|webm|mkv)$/i, audio:/\.(wav|mp3|flac|ogg|m4a|aac|opus)$/i};
    for (const [key, config] of Object.entries(mediaConfig)) {
      const files = config.max === 1 ? (value[key] == null ? [] : [value[key]]) : value[key];
      if (!Array.isArray(files) || files.length > config.max) throw new Error('A receita contém uma lista de mídias inválida.');
      for (const file of files) {
        if (typeof file !== 'string' || file.length > 240 || !extensions[config.kind].test(file) || /[^\p{L}\p{N}\p{M}_ .()/+\-]/u.test(file) || file.split('/').some((part) => !part || part === '.' || part === '..' || part.trim() !== part)) throw new Error('A receita contém um nome de mídia inválido.');
      }
      recipe[key] = config.max === 1 ? (files[0] || null) : [...files];
    }
    return recipe;
  }

  function applyRecipe(value, summary = null) {
    if (uploadCount) throw new Error('Aguarde o envio dos arquivos antes de abrir outra receita.');
    const request = cleanRecipe(value);
    rememberReferenceMetadata(summary);
    $('scene-prompt').value = request.prompt;
    for (const key of ['scene','aspect']) form.querySelector(`input[name="${key}"][value="${request[key]}"]`).checked = true;
    $('duration').value = String(request.duration); $('model').value = request.model; $('seed').value = request.seed == null ? '' : String(request.seed);
    $('camera').value = request.camera; $('camera-speed').value = request.camera_speed; $('camera-amount').value = request.camera_amount;
    $('framing').value = request.framing; $('output-audio').checked = request.output_audio;
    for (const key of toggleKeys) scenePreferences[request.scene][key] = request[key];
    for (const [key, config] of Object.entries(mediaConfig)) {
      media[key].forEach(releaseMedia);
      const files = config.max === 1 ? (request[key] ? [request[key]] : []) : request[key];
      media[key] = files.map((filename) => ({uploaded:filename, url:inputMediaUrl(filename), file:null, uploading:false, error:null}));
      renderMedia(key);
    }
    refreshReferenceLabels();
    $('references-details').open = hasReferences();
    updateSummary(); saveSettings();
    const unavailable = toggleKeys.filter((key) => request[key] && !featureState(key).available);
    if (unavailable.length) setError(`Receita aberta. Estes ajustes estão indisponíveis neste ambiente e ficaram desligados: ${unavailable.map((key) => featureLabels[key]).join(', ')}. As referências foram preservadas.`);
    else setError('');
    $('scene-prompt').focus({preventScroll:true});
    $('scene-prompt').scrollIntoView({behavior:'smooth', block:'center'});
    return request;
  }

  function exportRecipe(savedRequest = null) {
    setError('');
    try {
      const request = cleanRecipe(savedRequest || buildRequest());
      const blob = new Blob([JSON.stringify({format:'h3-studio-recipe', version:1, request}, null, 2)], {type:'application/json'});
      const url = URL.createObjectURL(blob); const link = document.createElement('a');
      link.href = url; link.download = `h3-studio-receita-${request.seed == null ? new Date().toISOString().slice(0,10) : request.seed}.json`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      if (!busy) setStatus('Receita salva.', 'O arquivo contém sua cena e os ajustes. Imagens, vídeos e áudios permanecem no ambiente onde foram enviados.');
    } catch (error) { setError(error.message); }
  }

  async function importRecipe(file) {
    if (!file) return;
    setError(''); $('import-recipe').disabled = true;
    try {
      if (file.size > 128 * 1024) throw new Error('Este arquivo é grande demais para uma receita. Abra o JSON salvo pelo Studio.');
      let payload;
      try { payload = JSON.parse(await file.text()); } catch (_) { throw new Error('Este arquivo não é uma receita JSON válida.'); }
      if (!payload || payload.format !== 'h3-studio-recipe' || payload.version !== 1 || Object.keys(payload).some((key) => !['format','version','request'].includes(key))) throw new Error('Formato de receita não reconhecido. Use um arquivo salvo pelo H3 Studio.');
      const request = cleanRecipe(payload.request);
      // Compile and inspect the recipe on the server without queueing anything.
      const prepared = await fetchJson('/h3max/api/prepare', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(request)});
      applyRecipe(request,prepared.summary);
      if (!busy) setStatus('Receita aberta.', 'A cena, os ajustes e as referências foram recuperados. Nenhuma geração foi iniciada.');
    } catch (error) { setError(error.message); }
    finally { updateButton(); }
  }

  function jobDate(value) {
    const date = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('pt-BR', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
  }

  function renderLibrary() {
    const labels = {queued:'Na fila', running:'Gerando', success:'Concluído', error:'Falhou', cancelled:'Cancelado', unknown:'Sem execução ativa'};
    $('job-list').replaceChildren();
    $('library-empty').hidden = Boolean(libraryJobs.length);
    $('library-empty').textContent = isPreview() ? 'Sua biblioteca aparecerá aqui quando você gerar no Runpod. Esta prévia não cria vídeos.' : 'Nenhum vídeo gerado neste Studio ainda.';
    for (const job of libraryJobs) {
      if (!job || typeof job.id !== 'string' || !job.request) continue;
      const card = document.createElement('article'); card.className = 'job-card';
      const heading = document.createElement('div'); heading.className = 'job-heading';
      const state = document.createElement('span'); state.className = `job-state job-state-${Object.hasOwn(labels, job.status) ? job.status : 'unknown'}`; state.textContent = labels[job.status] || labels.unknown;
      const date = document.createElement('time'); date.textContent = jobDate(job.created_at); heading.append(state,date);
      const prompt = document.createElement('p'); prompt.className = 'job-prompt'; prompt.textContent = job.request.prompt || 'Cena salva'; prompt.title = job.request.prompt || '';
      const details = document.createElement('p'); details.className = 'job-details'; details.textContent = [modelLabels[job.summary && job.summary.engine] || modelLabels[job.request.model] || 'H3', job.request.aspect, job.request.duration ? `~${job.request.duration} s` : '', job.request.seed != null ? `Semente ${job.request.seed}` : ''].filter(Boolean).join(' · ');
      const actions = document.createElement('div'); actions.className = 'job-actions';
      const reuse = document.createElement('button'); reuse.type = 'button'; reuse.className = 'secondary-button'; reuse.textContent = 'Reutilizar receita'; reuse.disabled = Boolean(uploadCount);
      reuse.addEventListener('click', () => { try { applyRecipe(job.request,job.summary); if (!busy) setStatus('Receita recuperada.', 'Cena, modelo, ajustes, semente e referências recuperados. Altere o que desejar e gere novamente.'); } catch (error) { setError(error.message); } });
      actions.append(reuse);
      const save = document.createElement('button'); save.type = 'button'; save.className = 'text-button'; save.textContent = 'Baixar receita'; save.addEventListener('click', () => exportRecipe(job.request)); actions.append(save);
      if (outputVideos(job.outputs).length) {
        const files = outputVideos(job.outputs);
        const partial = ['error','cancelled','unknown'].includes(job.status);
        const comparable = files.some((file) => videoStage(file) === 'base') && files.some((file) => videoStage(file) === 'final');
        const watch = document.createElement('button'); watch.type = 'button'; watch.className = 'text-button'; watch.textContent = partial ? 'Assistir arquivo salvo' : comparable ? 'Assistir e comparar' : 'Assistir';
        watch.addEventListener('click', () => { showJobOutputs(job); if (!busy) {
          if (partial) setStatus(`${labels[job.status]} · arquivo preservado.`, 'A geração não foi concluída. Este arquivo foi salvo antes da interrupção e continua disponível para assistir e baixar.', job.status === 'error' ? 'error' : '');
          else setStatus(comparable ? 'Original e resultado com ajustes.' : 'Vídeo da biblioteca.', comparable ? 'Alterne entre Original e Com ajustes abaixo do vídeo para comparar esta geração.' : 'Use Reutilizar receita para recuperar todos os ajustes e as referências desta geração.');
        } $('monitor-screen').scrollIntoView({behavior:'smooth',block:'center'}); }); actions.append(watch);
        const savedFile = files.find((file) => videoStage(file) === 'final') || files[0];
        const download = document.createElement('a'); download.className = 'text-button'; download.href = `/view?${new URLSearchParams({filename:savedFile.filename,subfolder:savedFile.subfolder || '',type:savedFile.type || 'output'})}`; download.download = savedFile.filename; download.textContent = videoStage(savedFile) === 'base' ? 'Baixar original' : 'Baixar vídeo'; actions.append(download);
      }
      if (['queued','running'].includes(job.status)) {
        const follow = document.createElement('button'); follow.type = 'button'; follow.className = 'text-button'; follow.textContent = activeJob && activeJob.id === job.id && busy ? 'Acompanhando' : 'Acompanhar'; follow.disabled = busy;
        follow.addEventListener('click', () => { activeJob = job; selectJob(job); busy = true; storedWrite(activeJobKey,job); applyPreparedSummary(job.summary,job.request,false); updateButton(); schedulePoll(100); renderLibrary(); }); actions.append(follow);
      }
      card.append(heading,prompt,details,actions); $('job-list').append(card);
    }
  }

  async function loadLibrary() {
    $('refresh-library').disabled = true;
    try {
      if (isPreview()) libraryJobs = [];
      else { const response = await fetchJson('/h3max/api/jobs'); libraryJobs = Array.isArray(response.jobs) ? response.jobs : []; }
      renderLibrary();
    } catch (_) { $('library-empty').hidden = false; $('library-empty').textContent = 'Não foi possível carregar o histórico. Use Atualizar para tentar novamente.'; }
    finally { $('refresh-library').disabled = false; }
  }

  function inspectorJob() { return selectedJob || activeJob; }
  function clearInspector(message) {
    inspectorGraph = null; $('graph-viewport').replaceChildren(); $('graph-viewport').hidden = true;
    $('node-inspection').hidden = true; $('graph-models').hidden = true; $('download-graph').hidden = true;
    $('inspector-status').textContent = message;
  }
  function selectJob(job) {
    selectedJob = job;
    if (inspectorGraph && inspectorGraph.source === 'saved_job' && inspectorGraph.job_id !== job.id) clearInspector('Outra geração foi selecionada. Use Ver geração selecionada para consultar o grafo correspondente.');
  }
  function updateInspectorButtons() {
    $('inspect-current').disabled = inspectorBusy || Boolean(uploadCount) || !capabilities;
    $('inspect-job').disabled = inspectorBusy || !inspectorJob() || isPreview();
  }
  function graphLinks(value, path, knownIds, result) {
    if (Array.isArray(value)) {
      if (value.length === 2 && typeof value[0] === 'string' && knownIds.has(value[0]) && Number.isInteger(value[1])) result.push({source:value[0],slot:value[1],input:path});
      else value.forEach((item,index) => graphLinks(item,`${path}[${index}]`,knownIds,result));
    } else if (value && typeof value === 'object') {
      Object.entries(value).forEach(([key,item]) => graphLinks(item,path ? `${path}.${key}` : key,knownIds,result));
    }
  }
  function graphStructure(prompt) {
    if (!prompt || typeof prompt !== 'object' || Array.isArray(prompt)) throw new Error('O ambiente não retornou um grafo válido.');
    const ids = Object.keys(prompt);
    if (!ids.length || ids.length > 2000 || ids.some((id) => !prompt[id] || typeof prompt[id].class_type !== 'string' || !prompt[id].inputs || typeof prompt[id].inputs !== 'object')) throw new Error('O grafo retornado não pode ser exibido neste painel.');
    const knownIds = new Set(ids); const edges = [];
    for (const id of ids) { const inputs = []; graphLinks(prompt[id].inputs,'',knownIds,inputs); inputs.forEach((link) => edges.push({...link,target:id})); }
    const depths = new Map(ids.map((id) => [id,0]));
    const parents = new Map(ids.map((id) => [id,new Set(edges.filter((edge) => edge.target === id).map((edge) => edge.source))]));
    const outgoing = new Map(ids.map((id) => [id,new Set(edges.filter((edge) => edge.source === id).map((edge) => edge.target))]));
    const pending = new Map([...parents].map(([id,items]) => [id,items.size]));
    const queue = ids.filter((id) => pending.get(id) === 0);
    for (let index = 0; index < queue.length; index += 1) {
      const id = queue[index];
      for (const target of outgoing.get(id)) {
        depths.set(target,Math.max(depths.get(target),depths.get(id) + 1));
        pending.set(target,pending.get(target) - 1); if (!pending.get(target)) queue.push(target);
      }
    }
    if (queue.length !== ids.length) throw new Error('O grafo contém uma conexão circular e não pode ser organizado.');
    return {ids,edges,depths};
  }
  function svgElement(tag, attributes = {}, text = null) {
    const element = document.createElementNS('http://www.w3.org/2000/svg',tag);
    for (const [key,value] of Object.entries(attributes)) element.setAttribute(key,String(value));
    if (text !== null) element.textContent = text;
    return element;
  }
  function renderGraph(payload, source) {
    const structure = graphStructure(payload.prompt);
    inspectorGraph = {prompt:payload.prompt,summary:payload.summary || {},required_models:Array.isArray(payload.required_models) ? payload.required_models : [],source,job_id:payload.job_id};
    const levels = [];
    structure.ids.forEach((id) => { const level = structure.depths.get(id); (levels[level] ||= []).push(id); });
    const nodeWidth = 204; const nodeHeight = 52; const gapX = 24; const gapY = 42; const padding = 24;
    const width = Math.max(440,...levels.map((level) => level.length * (nodeWidth + gapX) - gapX + padding * 2));
    const height = levels.length * (nodeHeight + gapY) - gapY + padding * 2;
    const positions = new Map();
    levels.forEach((level,index) => level.forEach((id,column) => positions.set(id,{x:(width - (level.length * (nodeWidth + gapX) - gapX))/2 + column * (nodeWidth + gapX),y:padding + index * (nodeHeight + gapY)})));
    const svg = svgElement('svg',{width,height,viewBox:`0 0 ${width} ${height}`,'aria-label':`${structure.ids.length} nós e ${structure.edges.length} conexões reais`});
    const defs = svgElement('defs'); const marker = svgElement('marker',{id:'node-arrow',markerWidth:7,markerHeight:7,refX:5,refY:3,orient:'auto'}); marker.append(svgElement('path',{d:'M0,0 L6,3 L0,6 Z',fill:'#7d8576'})); defs.append(marker); svg.append(defs);
    for (const edge of structure.edges) {
      const from = positions.get(edge.source); const to = positions.get(edge.target);
      const x1 = from.x + nodeWidth / 2; const y1 = from.y + nodeHeight; const x2 = to.x + nodeWidth / 2; const y2 = to.y;
      const line = svgElement('path',{d:`M${x1},${y1} C${x1},${y1 + 22} ${x2},${y2 - 22} ${x2},${y2}`,class:'graph-edge','marker-end':'url(#node-arrow)'});
      line.append(svgElement('title',{},`Nó ${edge.source}, saída ${edge.slot} → nó ${edge.target}, ${edge.input}`)); svg.append(line);
    }
    const selectNode = (id, element) => {
      svg.querySelectorAll('[role="button"]').forEach((node) => node.setAttribute('aria-pressed','false'));
      element.setAttribute('aria-pressed','true');
      $('node-title').textContent = `Nó ${id} · ${payload.prompt[id].class_type}`;
      const links = structure.edges.filter((edge) => edge.target === id).map((edge) => `${edge.input} ← nó ${edge.source}, saída ${edge.slot}`);
      $('node-inputs').textContent = (links.length ? `CONEXÕES\n${links.join('\n')}\n\nENTRADAS\n` : 'ENTRADAS\n') + JSON.stringify(payload.prompt[id].inputs,null,2);
      $('node-inspection').hidden = false;
    };
    for (const id of structure.ids) {
      const point = positions.get(id); const node = payload.prompt[id];
      const group = svgElement('g',{transform:`translate(${point.x} ${point.y})`,class:'graph-node',role:'button',tabindex:0,'aria-pressed':'false','aria-label':`Nó ${id}: ${node.class_type}`});
      group.append(svgElement('rect',{width:nodeWidth,height:nodeHeight,rx:6}),svgElement('text',{x:12,y:18,class:'graph-node-id'},`NÓ ${id}`),svgElement('text',{x:12,y:37,class:'graph-node-name'},node.class_type.length > 27 ? `${node.class_type.slice(0,26)}…` : node.class_type),svgElement('title',{},node.class_type));
      group.addEventListener('click',() => selectNode(id,group)); group.addEventListener('keydown',(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectNode(id,group); } }); svg.append(group);
    }
    $('graph-viewport').replaceChildren(svg); $('graph-viewport').hidden = false; $('node-inspection').hidden = true;
    $('graph-model-list').replaceChildren();
    const classes = [...new Set(structure.ids.map((id) => payload.prompt[id].class_type))];
    for (const model of inspectorGraph.required_models) { const row = document.createElement('li'); row.textContent = `${model.folder || 'Modelo'} / ${model.filename || ''}`; $('graph-model-list').append(row); }
    for (const name of classes) { const row = document.createElement('li'); row.textContent = `Componente: ${name}`; $('graph-model-list').append(row); }
    $('graph-models').hidden = false; $('download-graph').hidden = false;
    const stages = {generate:'Geração',temporal:'Continuidade',refine:'Definição'};
    const steps = Array.isArray(inspectorGraph.summary.stages) ? inspectorGraph.summary.stages.map((stage) => stages[stage] || stage).join(' → ') : '';
    const states = {queued:'na fila',running:'em execução',success:'concluída',error:'falhou',cancelled:'cancelada',unknown:'sem execução ativa'};
    $('inspector-status').textContent = `${source === 'saved_job' ? `Grafo registrado da geração${states[payload.status] ? ` · ${states[payload.status]}` : ''}` : 'Configuração preparada · nenhuma geração iniciada'}. ${structure.ids.length} nós · ${structure.edges.length} conexões.${steps ? ` ${steps}.` : ''}`;
  }
  async function inspectGraph(saved) {
    if (inspectorBusy) return;
    inspectorBusy = true; updateInspectorButtons(); $('graph-inspector').open = true;
    $('inspector-status').textContent = 'Carregando as conexões e os componentes desta configuração…';
    const revision = configurationRevision;
    try {
      const job = saved ? inspectorJob() : null;
      if (saved && !job) throw new Error('Selecione uma geração na biblioteca.');
      const payload = saved ? await fetchJson(`/h3max/api/jobs/${encodeURIComponent(job.id)}/graph`) : await fetchJson('/h3max/api/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(buildRequest())});
      if (!saved && revision !== configurationRevision) { clearInspector('Configuração alterada durante a consulta. Use Ver configuração atual para atualizar o grafo.'); return; }
      if (saved && (!inspectorJob() || inspectorJob().id !== job.id)) { clearInspector('Outra geração foi selecionada durante a consulta. Abra o grafo da geração selecionada.'); return; }
      renderGraph(payload,saved ? 'saved_job' : 'prepared');
    } catch (error) {
      inspectorGraph = null; $('graph-viewport').hidden = true; $('node-inspection').hidden = true; $('graph-models').hidden = true; $('download-graph').hidden = true; $('inspector-status').textContent = error.message;
    } finally { inspectorBusy = false; updateInspectorButtons(); }
  }
  function downloadGraph() {
    if (!inspectorGraph) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(inspectorGraph.prompt,null,2)],{type:'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = `h3-studio-grafo-${inspectorGraph.job_id || 'configuracao'}.json`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url),1000);
  }

  async function loadCapabilities() {
    try {
      capabilities = await fetchJson('/h3max/api/capabilities');
      const preview = isPreview();
      $('open-comfy').hidden = preview;
      $('comfy-preview-note').hidden = !preview;
      $('connection').className = `connection ${preview ? 'preview' : capabilities.runtime_ready ? 'ready' : 'warning'}`;
      $('connection-label').textContent = preview ? 'Prévia local' : capabilities.runtime_ready ? 'GPU disponível' : 'Ambiente em preparação';
      if (preview) {
        $('environment-banner').hidden = false;
        $('environment-banner').textContent = 'Prévia da interface · geração indisponível neste computador';
      } else if (!capabilities.runtime_ready) {
        $('environment-banner').hidden = false;
        $('environment-banner').textContent = capabilities.message || 'O ambiente ainda não está pronto para gerar. Você já pode preparar sua cena.';
      }
      updateSummary();
      loadLibrary();
      const previousJob = storedRead(activeJobKey);
      if (!preview && capabilities.runtime_ready && previousJob && typeof previousJob.id === 'string') {
        activeJob = previousJob; selectJob(previousJob); busy = true; applyPreparedSummary(previousJob.summary, previousJob.request || {}, false); updateButton(); setStatus('Recuperando sua última geração.', 'Consultando o resultado no ambiente.', 'working'); schedulePoll(100);
      }
    } catch (error) {
      $('connection').className = 'connection warning'; $('connection-label').textContent = 'Sem conexão com o ambiente';
      $('environment-banner').hidden = false; $('environment-banner').textContent = 'Não foi possível conectar ao Studio. Reabra esta página no endereço do ambiente com GPU.';
      setStatus('Ambiente indisponível.', error.message, 'error'); updateSummary();
    }
  }

  form.addEventListener('submit', submit);
  form.addEventListener('input', (event) => {
    if (event.target.type !== 'file') {
      if (toggleKeys.includes(event.target.id)) scenePreferences[radio('scene')][event.target.id] = event.target.checked;
      updateSummary(); saveSettings();
    }
  });
  form.addEventListener('change', (event) => {
    if (event.target.dataset.media) { const files = Array.from(event.target.files || []); event.target.value = ''; addMedia(event.target.dataset.media, files); }
    else { updateSummary(); saveSettings(); }
  });
  $('reuse-seed').addEventListener('click', () => { if (lastSeed !== null) { $('seed').value = String(lastSeed); document.querySelector('.advanced-details').open = true; updateSummary(); saveSettings(); $('seed').focus(); } });
  $('cancel-job').addEventListener('click', cancelJob);
  $('inspect-current').addEventListener('click',() => inspectGraph(false));
  $('inspect-job').addEventListener('click',() => inspectGraph(true));
  $('download-graph').addEventListener('click',downloadGraph);
  $('refresh-library').addEventListener('click', loadLibrary);
  $('export-recipe').addEventListener('click', () => exportRecipe());
  $('import-recipe').addEventListener('click', () => $('recipe-file').click());
  $('recipe-file').addEventListener('change', (event) => { const file = event.target.files[0]; event.target.value = ''; importRecipe(file); });
  window.addEventListener('beforeunload', () => { Object.values(media).flat().forEach(releaseMedia); });
  restoreSettings(); updateSummary(); loadCapabilities();
})();
