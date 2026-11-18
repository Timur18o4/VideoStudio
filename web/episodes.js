"use strict";
// The server owns references and recipes; the browser only keeps an editable draft.
let library = {characters: [], episodes: [], clips: []};
let episode = {title: 'Meine erste Episode', shots: Array.from({length: 5}, () => newShot())};
let characterImage = '', extractedFrame = null, timelineKey = '', libraryBusy = false;
let fieldSequence=0;
function newShot() { return {kind:'generate', scene:'', speech:'', sounds:'', seconds:6, images:[], character:'', direct_prompt:true, start:0, audio:true}; }
function outputValues() { return {aspect:$('output-aspect').value, resolution:Number($('output-resolution').value), fps:Number($('output-fps').value), container:$('output-container').value}; }
function setOutput(values = {}) { for(const key of ['aspect','resolution','fps','container']) if(values[key] != null) $('output-'+key).value=String(values[key]); }
function episodeError(message='') { $('episode-error').textContent=message; $('episode-error').hidden=!message; }
function persistEpisode() {
  episode.title=$('episode-title').value;
  episode.output=outputValues();
  try {localStorage.setItem('video-studio-episode',JSON.stringify(episode));localStorage.setItem('video-studio-output',JSON.stringify(episode.output));} catch(_) {}
  updateTotals();
}
function updateTotals() {
  const fps=outputValues().fps;
  const frames=episode.shots.reduce((total,shot)=>total+Math.round((Number(shot.seconds)||0)*fps),0);
  $('episode-total').textContent=`${Number((frames/fps).toFixed(3))} Sekunden · ${episode.shots.length} Szenen`;
}
function options(select, records, empty, selected='') {
  select.replaceChildren(new Option(empty,''));
  for(const item of records) select.add(new Option(item.name || item.title,item.id));
  select.value=selected;
}
async function reloadLibrary() {
  library=await api('/api/library');
  options($('saved-episodes'),library.episodes,'Gespeicherte Episode wählen …',episode.id);
  options($('character-select'),library.characters,'Neuen Charakter anlegen …',$('character-select').value);
  options($('frame-clip'),library.clips,'Clip wählen …',$('frame-clip').value);
}
async function uploadImage(file) {
  if(!file || !/^image\/(jpeg|png|webp)$/.test(file.type) || file.size>12*1024*1024) throw new Error('Verwende JPG, PNG oder WebP mit höchstens 12 MB.');
  return api('/api/images',{image:await encode(file)});
}
function imageURL(id) {return `/library/images/${id}.jpg`;}
function node(tag, className, content) {const item=document.createElement(tag);if(className)item.className=className;if(content!=null)item.textContent=content;return item;}
function field(labelText, input) {const wrapper=node('div','scene-field');const label=node('label','field-label',labelText);input.id='scene-field-'+(++fieldSequence);label.htmlFor=input.id;wrapper.append(label,input);return wrapper;}
function textInput(value, placeholder, limit, multiline=false) {
  const input=document.createElement(multiline?'textarea':'input');input.value=value||'';input.placeholder=placeholder;input.maxLength=limit;
  if(multiline) input.rows=3;return input;
}
function renderCards(openIndex=0) {
  const list=$('scene-list');list.replaceChildren();
  episode.shots.forEach((shot,index)=>{
    const card=node('details','scene-card');card.open=index===openIndex;
    const summary=node('summary');const title=node('span');
    const updateTitle=()=>{title.textContent=`Szene ${index+1} · ${shot.seconds} s · ${shot.kind==='clip'?'Vorhandener Clip':(shot.scene?.slice(0,55)||'Neue Aufnahme')}`;};
    updateTitle();summary.append(title);card.append(summary);
    const body=node('div','scene-body');card.append(body);
    const controls=node('div','scene-controls');
    for(const [name,delta] of [['↑ Nach oben',-1],['↓ Nach unten',1]]) {
      const button=node('button','quiet',name);button.type='button';button.disabled=index+delta<0||index+delta>=episode.shots.length;
      button.onclick=()=>{[episode.shots[index],episode.shots[index+delta]]=[episode.shots[index+delta],episode.shots[index]];persistEpisode();renderCards(index+delta);};controls.append(button);
    }
    const remove=node('button','quiet','Entfernen');remove.type='button';remove.disabled=episode.shots.length===1;
    remove.onclick=()=>{episode.shots.splice(index,1);persistEpisode();renderCards(Math.max(0,index-1));};controls.append(remove);body.append(controls);
    const kind=document.createElement('select');options(kind,[{id:'generate',name:'Neue KI-Aufnahme'},{id:'clip',name:'Fertigen Clip verwenden'}],'Szenentyp wählen',shot.kind);
    kind.onchange=()=>{shot.kind=kind.value;persistEpisode();renderCards(index);};body.append(field('Quelle dieser Szene',kind));
    if(shot.kind==='clip') {
      const clips=document.createElement('select');options(clips,library.clips,'Clip auswählen …',shot.clip);
      clips.onchange=()=>{shot.clip=clips.value;const match=library.clips.find(item=>item.id===clips.value);if(match && shot.seconds>match.duration){shot.seconds=Number(match.duration.toFixed(3));duration.value=shot.seconds;}persistEpisode();updateTitle();};body.append(field('Clip',clips));
      const start=document.createElement('input');start.type='number';start.min='0';start.step='0.01';start.value=shot.start||0;
      start.oninput=()=>{shot.start=Number(start.value);persistEpisode();};body.append(field('Ausschnitt beginnt bei Sekunde',start));
      const audio=document.createElement('input');audio.type='checkbox';audio.checked=shot.audio!==false;audio.onchange=()=>{shot.audio=audio.checked;persistEpisode();};body.append(field('Originalton übernehmen',audio));
    } else {
      const character=document.createElement('select');options(character,library.characters,'Kein gespeicherter Charakter',shot.character);
      character.onchange=()=>{shot.character=character.value;persistEpisode();renderCards(index);};body.append(field('Hauptcharakter · optional',character));
      const preview=node('div','scene-images');
      const characterRecord=library.characters.find(item=>item.id===shot.character);
      for(let number=0;number<2;number++) {
        const wrapper=node('div');const id=shot.images?.[number] || (number===0 ? characterRecord?.image : '');
        if(id) {const image=document.createElement('img');image.src=imageURL(id);image.alt=number?'Schlussbild':'Startbild';wrapper.append(image);}
        const input=document.createElement('input');input.type='file';input.accept='image/jpeg,image/png,image/webp';
        input.onchange=async()=>{if(!input.files[0])return;try {episodeError();input.disabled=true;const asset=await uploadImage(input.files[0]);shot.images=shot.images||[];if(number===1&&!shot.images[0]){if(characterRecord)shot.images[0]=characterRecord.image;else throw new Error('Wähle zuerst ein Startbild.');}shot.images[number]=asset.id;persistEpisode();renderCards(index);}catch(exc){episodeError(exc.message);input.disabled=false;}};
        wrapper.append(field(number?'Schlussbild · optional':(characterRecord&&!shot.images?.[0]?'Startbild aus Charaktervorlage':'Startbild'),input));
        if(shot.images?.[number]) {const clear=node('button','quiet','Bild entfernen');clear.type='button';clear.onclick=()=>{if(number===0)shot.images=[];else shot.images.splice(1,1);persistEpisode();renderCards(index);};wrapper.append(clear);}
        preview.append(wrapper);
      }
      body.append(preview);
      const scene=textInput(shot.scene,'Kamera, Handlung und Bewegung dieser Aufnahme …',4000,true);
      scene.oninput=()=>{shot.scene=scene.value;persistEpisode();updateTitle();};body.append(field('Regieanweisung',scene));
      const audio=node('details','scene-audio');audio.append(node('summary',null,'Sprache & Geräusche · optional'));
      for(const [key,label,limit] of [['speech','Gesprochener Text',8000],['sounds','Geräusche und Atmosphäre',600]]) {
        const input=textInput(shot[key],key==='speech'?'Nur Worte, die gesprochen werden sollen.':'Zum Beispiel: Wind, Schritte, knarrende Tür',limit,key==='speech');
        input.oninput=()=>{shot[key]=input.value;persistEpisode();};audio.append(field(label,input));
      }
      body.append(audio);
      const direct=document.createElement('input');direct.type='checkbox';direct.checked=shot.direct_prompt!==false;direct.onchange=()=>{shot.direct_prompt=direct.checked;persistEpisode();};body.append(field('Beschreibung unverändert verwenden',direct));
    }
    const duration=document.createElement('input');duration.type='number';duration.min=String(1/outputValues().fps);duration.step='any';duration.value=shot.seconds;
    duration.oninput=()=>{shot.seconds=Number(duration.value);persistEpisode();updateTitle();};body.append(field('Dauer dieser Szene in Sekunden',duration));list.append(card);
  });
  updateTotals();
}
function setMode(mode) {
  $('create-form').hidden=mode==='episode';$('episode-editor').hidden=mode!=='episode';
  $('mode-single').setAttribute('aria-selected',String(mode!=='episode'));$('mode-episode').setAttribute('aria-selected',String(mode==='episode'));
  try{localStorage.setItem('video-studio-mode',mode);}catch(_){}
}
async function episodeAction(render) {
  if(sending)return;
  sending=true;updateButton();window.episodes.updateState();episodeError();persistEpisode();
  try {
    const result=await api(render?'/api/generate-episode':'/api/save-episode',{...episode,output:outputValues()});
    if(!render){episode.id=result.id;persistEpisode();await reloadLibrary();$('episode-message').textContent='Episode gespeichert. Du kannst sie später laden und als neue Folge weiterverwenden.';}
    else {await refresh();$('episode-message').textContent='Die Episode wird Szene für Szene erstellt.';}
  } catch(exc){episodeError(exc.message);}finally{sending=false;updateButton();window.episodes.updateState();}
}
function selectCharacter() {
  const selected=library.characters.find(item=>item.id===$('character-select').value);
  $('character-name').value=selected?.name||'';$('character-description').value=selected?.description||'';
  characterImage=selected?.image||'';showCharacterImage();
}
function showCharacterImage() {$('character-preview').hidden=!characterImage;if(characterImage)$('character-preview').src=imageURL(characterImage);}
function updateTimeline() {
  const job=state?.job;
  const key=JSON.stringify([job?.id,job?.shots]);
  if(key!==timelineKey) {
    timelineKey=key;$('shot-progress').replaceChildren();
    for(const [index,shot] of (job?.shots||[]).entries()) {
      const row=node('div','shot-row');
      const labels={queued:'Wartet',running:'Wird erstellt',done:'Fertig',cancelled:'Abgebrochen',interrupted:'Unterbrochen'};
      row.append(node('span',null,`Szene ${index+1} · ${shot.seconds} s · ${labels[shot.state]||shot.state}`));
      if(shot.video) {
        const play=node('button','quiet','Ansehen');play.type='button';play.onclick=()=>showVideo(shot.video,shot.seconds);row.append(play);
        const download=node('a','quiet','Speichern');download.href=shot.video+'?download=1';download.download=`Szene-${index+1}.mp4`;row.append(download);
        const use=node('button','quiet','Für neue Szene');use.type='button';use.onclick=async()=>{try{const asset=await api('/api/frame',{clip:`${job.id}-${String(index+1).padStart(3,'0')}`,at:Math.max(0,shot.seconds-0.2)});episode.shots.push({...newShot(),images:[asset.id]});persistEpisode();setMode('episode');renderCards(episode.shots.length-1);}catch(exc){episodeError(exc.message);}};row.append(use);
      }
      $('shot-progress').append(row);
    }
  }
  const preview=job?.live_preview;
  $('render-preview').hidden=!preview || !active();
  if(preview && $('render-preview-image').getAttribute('src')!==preview) $('render-preview-image').src=preview;
  $('render-preview-note').textContent=job?.preview_note||(active()?'Während die KI lädt, gibt es noch keine Zwischenbilder. Fertige Szenen kannst du hier sofort ansehen.':'');
}
window.episodes={
  outputValues,
  updateState() {
    $('episode-generate').disabled=sending||active()||libraryBusy||state?.setup?.state==='running'||(!state?.ready&&episode.shots.some(shot=>shot.kind!=='clip'));
    $('episode-save').disabled=sending||libraryBusy;
    if(state?.job?.title===episode.title && !active()) {
      if(state.job.state==='done') $('episode-message').textContent='Episode fertig. Du kannst das Gesamtvideo und die einzelnen Szenen speichern.';
      else if(['cancelled','error','interrupted'].includes(state.job.state)) $('episode-message').textContent='Erstellung beendet. Bereits fertige Szenen bleiben rechts verfügbar.';
    }
    updateTimeline();
  },
  async init() {
    try {
      const draft=JSON.parse(localStorage.getItem('video-studio-episode')||'null');
      if(draft&&Array.isArray(draft.shots)&&draft.shots.length)episode=draft;
      setOutput(JSON.parse(localStorage.getItem('video-studio-output')||'{}'));
      setMode(localStorage.getItem('video-studio-mode')||'single');
    }catch(_){}
    $('episode-title').value=episode.title;await reloadLibrary();renderCards();
  }
};
for(const key of ['aspect','resolution','fps','container']) $('output-'+key).onchange=()=>{persistEpisode();};
$('mode-single').onclick=()=>setMode('single');$('mode-episode').onclick=()=>setMode('episode');
$('episode-title').oninput=persistEpisode;
$('scene-add').onclick=()=>{episode.shots.push(newShot());persistEpisode();renderCards(episode.shots.length-1);};
$('episode-distribute').onclick=()=>{
  const fps=outputValues().fps,frames=Math.round(Number($('episode-duration').value)*fps),count=episode.shots.length;
  if(!Number.isSafeInteger(frames)||frames<count){episodeError('Die Gesamtlänge muss für mindestens ein Bild pro Szene reichen.');return;}
  episodeError();episode.shots.forEach((shot,index)=>shot.seconds=(Math.floor(frames/count)+(index<frames%count?1:0))/fps);persistEpisode();renderCards();
};
$('episode-save').onclick=()=>episodeAction(false);$('episode-generate').onclick=()=>episodeAction(true);
$('episode-load').onclick=()=>{const saved=library.episodes.find(item=>item.id===$('saved-episodes').value);if(!saved)return;episode=structuredClone(saved);$('episode-title').value=episode.title;setOutput(episode.output);persistEpisode();renderCards();$('episode-message').textContent='Episode geladen. Bilder und Anweisungen können geändert werden.';};
$('episode-new').onclick=()=>{delete episode.id;$('episode-title').value=episode.title+' · nächste Folge';persistEpisode();$('saved-episodes').value='';$('episode-message').textContent='Neue Folge mit denselben Charakteren und Szenenvorlagen. Jetzt Anweisungen und Bilder anpassen.';};
$('character-select').onchange=selectCharacter;
$('character-image').onchange=async event=>{try{const image=await uploadImage(event.target.files[0]);characterImage=image.id;showCharacterImage();}catch(exc){episodeError(exc.message);}};
$('character-save').onclick=async()=>{try{const saved=await api('/api/characters',{id:$('character-select').value,name:$('character-name').value,description:$('character-description').value,image:characterImage});await reloadLibrary();$('character-select').value=saved.id;renderCards();$('library-message').textContent='Charakter gespeichert. Er steht jetzt in jeder Szene zur Auswahl.';}catch(exc){episodeError(exc.message);}};
$('clip-import').onchange=async event=>{
  const file=event.target.files[0];if(!file)return;
  if(file.size>1024**3){episodeError('Der Clip darf höchstens 1 GB groß sein.');return;}
  libraryBusy=true;window.episodes.updateState();$('library-message').textContent='Clip wird lokal importiert …';
  try{
    const session=await fetch('/api/session');token=(await session.json()).token;
    const response=await fetch('/api/import-clip',{method:'POST',headers:{'X-Studio-Token':token,'X-Clip-Name':encodeURIComponent(file.name),'Content-Type':'application/octet-stream'},body:file});
    const result=await response.json();if(!response.ok)throw new Error(result.error);
    await reloadLibrary();$('frame-clip').value=result.id;$('frame-clip').dispatchEvent(new Event('change'));renderCards();$('library-message').textContent='Clip importiert. Du kannst ihn als Szene einsetzen oder ein Referenzbild übernehmen.';
  }catch(exc){episodeError(exc.message);$('library-message').textContent='Import fehlgeschlagen.';}finally{libraryBusy=false;window.episodes.updateState();}
};
$('frame-clip').onchange=()=>{const clip=library.clips.find(item=>item.id===$('frame-clip').value);$('source-clip').hidden=!clip;if(clip)$('source-clip').src=clip.url;};
$('source-clip').onseeked=()=>{$('frame-at').value=$('source-clip').currentTime.toFixed(2);};
$('frame-extract').onclick=async()=>{try{extractedFrame=await api('/api/frame',{clip:$('frame-clip').value,at:Number($('frame-at').value)});$('frame-image').src=extractedFrame.url;$('frame-result').hidden=false;}catch(exc){episodeError(exc.message);}};
$('frame-character').onclick=()=>{if(extractedFrame){characterImage=extractedFrame.id;showCharacterImage();$('character-name').focus();}};
$('frame-scene').onclick=()=>{if(extractedFrame){episode.shots.push({...newShot(),images:[extractedFrame.id]});persistEpisode();renderCards(episode.shots.length-1);}};
