class XparkleLevelCard extends HTMLElement {
  constructor() {
    super(); this.attachShadow({mode:'open'}); this.shadowRoot.innerHTML=TEMPLATE;
    this._view='front'; this._pending=false; this._online=false; this._latest=-Infinity;this._lastReceived=-Infinity;this._lastSequence=-1;this._blockedThrough=-Infinity;
    this._paints=[]; this._renderCount=0;this._acceptedSamples=0;this._coalescedSamples=0;
    const q=id=>this.shadowRoot.getElementById(id); this.q=q;
    for(const view of ['front','rear','top']) q('xp-view-'+view).addEventListener('click',()=>{this._view=view;this._closeCalibration();this._render();});
    q('xp-session').addEventListener('click',()=>this._action('switch',this._isOn()||this._nonManualBusy()?'turn_off':'turn_on',this._config?.measurement_switch));
    q('xp-renew').addEventListener('click',()=>this._action('button','press',this._config?.renew_button));
    q('xp-kind').addEventListener('change',()=>{const value=q('xp-kind').value;if(['caravan','tandem','motorhome','van'].includes(value))this._action('select','select_option',this._config?.vehicle_select,{option:value});});
    q('xp-tolerance').addEventListener('change',()=>{const value=this._number(q('xp-tolerance').value);if(value>=0.05&&value<=5)this._action('number','set_value',this._config?.tolerance_number,{value});else{q('xp-action-error').hidden=false;q('xp-action-error').textContent='Anna toleranssi väliltä 0,05–5 cm.';}});
    q('xp-cal-open').addEventListener('click',()=>{q('xp-cal-check').checked=false;q('xp-cal-confirm').hidden=false;q('xp-cal-open').setAttribute('aria-expanded','true');});
    q('xp-cal-cancel').addEventListener('click',()=>{this._closeCalibration();q('xp-cal-open').focus();});
    q('xp-settings-details').addEventListener('toggle',event=>{if(!event.currentTarget.open)this._closeCalibration();});
    this.shadowRoot.addEventListener('keydown',event=>{if(event.key==='Escape'&&!q('xp-cal-confirm').hidden){this._closeCalibration();q('xp-cal-open').focus();}});
  }
  setConfig(config) {
    const appearance=config.appearance??'native';
    if(!['native','mint'].includes(appearance))throw Error('Appearance must be native or mint');
    this.setAttribute('appearance',appearance);
    const domains={level_sensor:'sensor',measurement_switch:'switch',renew_button:'button',tolerance_number:'number',vehicle_select:'select'};
    for(const [key,domain] of Object.entries(domains))if(typeof config[key]!=='string'||!new RegExp('^'+domain+'\\.[a-z0-9_]+$').test(config[key]))throw Error('Missing or invalid '+key);
    this._config={...config}; this._source=null;this._latest=-Infinity;this._lastReceived=-Infinity;this._lastSequence=-1;this._blockedThrough=-Infinity;this._pendingSample=null;this._queueRender();
  }
  set hass(hass) {
    const previousSource=this._source;
    this._hass=hass;
    if(this._connection!==hass.connection){this._unbind();this._connection=hass.connection;this._bind();}
    this._online=hass.connected!==false&&hass.connection?.connected!==false;
    const source=hass.states[this._config?.level_sensor];const updated=Date.parse(source?.last_updated);
    if(source&&Number.isFinite(updated)&&updated>=this._latest){
      const a=source.attributes||{},received=Date.parse(a.received_at),sequence=a.sequence;
      const validMetadata=Number.isFinite(received)&&received<=Date.now()+100&&Number.isInteger(sequence)&&sequence>=0&&typeof a.session_id==='string'&&a.session_id.length>0&&a.session_id.length<=64;
      if(source.state==='ready'&&!validMetadata){this._source=null;this._latest=updated;}
      else if(source.state!=='ready'||(received>=this._lastReceived&&(a.session_id!==this._sessionId||sequence>=this._lastSequence))){
        this._source=source;this._latest=updated;
        if(source.state==='ready'){
          if(a.session_id!==this._sessionId||sequence!==this._lastSequence){
            if(this._pendingSample)this._coalescedSamples++;
            this._pendingSample={eventAt:performance.now()};this._acceptedSamples++;
          }
          this._lastReceived=received;this._lastSequence=sequence;this._sessionId=a.session_id;
        }
      }
    }
    if(!source||!Number.isFinite(updated)){this._source=null;}
    const uiKey=[this._online,hass.language,hass.states[this._config?.measurement_switch]?.state,hass.states[this._config?.tolerance_number]?.state,hass.states[this._config?.vehicle_select]?.state].join('|');
    if(this._source!==previousSource||uiKey!==this._uiKey){this._uiKey=uiKey;this._queueRender();}
  }
  connectedCallback(){this._bind();if(!this._ageTimer)this._ageTimer=setInterval(()=>this._render(),250);this._queueRender();}
  disconnectedCallback(){this._unbind();clearInterval(this._ageTimer);this._ageTimer=null;if(this._raf)cancelAnimationFrame(this._raf);if(this._paintRaf)cancelAnimationFrame(this._paintRaf);this._raf=this._paintRaf=null;if(this._pendingSample){this._coalescedSamples++;this._pendingSample=null;}this._closeCalibration();}
  _bind(){if(this._bound||!this.isConnected||!this._connection?.addEventListener)return;this._offline=()=>{this._online=false;this._blockedThrough=this._lastReceived;this._closeCalibration();this._render();};this._ready=()=>{this._online=true;this._queueRender();};this._connection.addEventListener('disconnected',this._offline);this._connection.addEventListener('ready',this._ready);this._bound=true;}
  _unbind(){if(this._bound){this._connection.removeEventListener('disconnected',this._offline);this._connection.removeEventListener('ready',this._ready);}this._bound=false;}
  _queueRender(){if(this._raf||!this.isConnected)return;this._raf=requestAnimationFrame(()=>{this._raf=null;const sample=this._pendingSample;this._pendingSample=null;this._render();if(sample){if(this._paintRaf){cancelAnimationFrame(this._paintRaf);this._coalescedSamples++;}this._paintRaf=requestAnimationFrame(()=>{this._paintRaf=null;this._paints.push(performance.now()-sample.eventAt);if(this._paints.length>256)this._paints.shift();});}});}
  _closeCalibration(){this.q('xp-cal-confirm').hidden=true;this.q('xp-cal-check').checked=false;this.q('xp-cal-open').setAttribute('aria-expanded','false');}
  _number(value){if(typeof value==='number')return Number.isFinite(value)?value:NaN;if(typeof value!=='string'||!/^[-+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)$/.test(value.trim()))return NaN;return Number(value.trim().replace(',','.'));}
  _isOn(){return this._hass?.states[this._config?.measurement_switch]?.state==='on';}
  _nonManualBusy(){const a=this._source?.attributes||{};return a.mode!=='manual'&&['connecting','measuring'].includes(a.session_status);}
  async _action(domain,service,entity,extra={}) {
    if(!this._online||this._pending||!this._config||!entity)return;
    this._closeCalibration();this._pending=true;this.q('xp-action-error').hidden=true;this._render();
    try{await this._hass.callService(domain,service,{entity_id:entity,...extra});}
    catch{this.q('xp-action-error').textContent='Toiminto ei onnistunut. Tarkista yhteys ja mittauksen tila.';this.q('xp-action-error').hidden=false;}
    finally{this._pending=false;this._render();}
  }
  _render(){
    if(!this._config||!this._hass)return;
    this._renderCount++;
    const q=this.q,a=this._source?.attributes||{},now=Date.now();
    const received=Date.parse(a.received_at),age=(now-received)/1000;
    const ttl=this._number(a.fresh_timeout_seconds),tol=this._number(a.level_tolerance_cm),p=this._number(a.longitudinal_mm),r=this._number(a.transverse_mm),width=this._number(a.width_cm),length=this._number(a.length_cm);
    const toleranceValid=Number.isFinite(tol)&&tol>=0.05&&tol<=5;
    // The backend supports at most 45 degrees. Allow only floating-point noise
    // at that boundary; visual saturation must not admit impossible geometry.
    const plausible=(gap,span)=>Number.isFinite(gap)&&Math.abs(gap)<=span*10*(Math.SQRT1_2+1e-12);
    const valid=this._source?.state==='ready'&&this._online&&this._isOn()&&a.session_status==='measuring'&&a.mode==='manual'&&a.directions_confirmed===true&&Number.isFinite(age)&&age>=-0.1&&age<=ttl&&received>this._blockedThrough&&ttl>=1&&ttl<=10&&toleranceValid&&width>=1&&width<=500&&length>=1&&length<=2000&&plausible(p,length)&&plausible(r,width)&&['front','rear','left','right'].includes(a.mount_position)&&Date.parse(a.expires_at)>now;
    const level=valid&&toleranceValid?(Math.abs(p)<=tol*10&&Math.abs(r)<=tol*10?'ok':'adjust'):'unknown';
    const fmt=new Intl.NumberFormat(this._hass.language||'fi',{maximumFractionDigits:1});
    const magnitude=value=>Math.abs(value)>0&&Math.abs(value)<.05?'<'+fmt.format(.1):fmt.format(Math.abs(value));
    const move=value=>!valid?'—':value===0?'0 mm':(value>0?'↑ ':'↓ ')+magnitude(value)+' mm';
    const describe=value=>!valid?'Ei ajantasaista korjausta':value===0?'Ei korjausta':(value>0?'Nosta ':'Laske ')+magnitude(value)+' millimetriä';
    const correction=(id,value)=>{const node=q(id);node.textContent=move(value);node.dataset.motion=!valid?'unknown':value>0?'up':value<0?'down':'zero';node.setAttribute('aria-label',describe(value));};
    const frontView=this._view==='front',topView=this._view==='top';
    for(const [id,value] of Object.entries({'xp-front-value':-p,'xp-rear-value':p,'xp-left-value':-r,'xp-right-value':r,'xp-front-inline':-p,'xp-rear-inline':p}))correction(id,value);
    const gauge=(axis,gap,span,negative,positive,sign)=>{
      const node=q('xp-gauge-'+axis),bubble=q('xp-bubble-'+axis),label=q('xp-gauge-'+axis+'-value');
      node.dataset.level=!valid?'unknown':Math.abs(gap)<=tol*10?'ok':'adjust';bubble.hidden=!valid;
      // Fixed physical axes: bubble points to the HIGH end, not the end to raise.
      // One percent slope fills the illustrative travel; no calibrated scale.
      const offset=valid?Math.max(-1,Math.min(1,sign*gap/(span*10)/.01))*40:0;
      bubble.style.left=(50+offset)+'%';
      const text=!valid?'Ei ajantasaista tietoa':gap===0?'Ei korkeuseroa':(gap<0?negative:positive)+' ylempänä · '+magnitude(gap)+' mm';
      label.textContent=text;node.setAttribute('aria-label',(axis==='transverse'?'Sivukallistus. ':'Pituuskallistus. ')+text+(valid?(node.dataset.level==='ok'?'. Toleranssin sisällä.':'. Tasausta tarvitaan.'):'') );
    };
    gauge('transverse',r,width,'Oikea','Vasen',-1);gauge('longitudinal',p,length,'Perä','Keula',1);
    const kind=['caravan','tandem','motorhome','van'].includes(a.vehicle_type)?a.vehicle_type:'caravan';
    const plot=this.shadowRoot.querySelector('.xp-plot'),elevation=this.shadowRoot.querySelector('.xp-elevation'),vehicle=this.shadowRoot.querySelector('.xp-vehicle');
    vehicle.dataset.kind=kind;elevation.dataset.kind=kind;plot.dataset.level=elevation.dataset.level=level;elevation.dataset.view=this._view;
    plot.hidden=!topView;elevation.hidden=topView;q('xp-top-arrow').hidden=!topView;q('xp-longitudinal').hidden=topView;
    for(const view of ['front','rear','top'])q('xp-view-'+view).setAttribute('aria-pressed',String(view===this._view));
    q('xp-face-left-label').textContent=frontView?'Vaunun oikea':'Vaunun vasen';q('xp-face-right-label').textContent=frontView?'Vaunun vasen':'Vaunun oikea';
    correction('xp-face-left-value',frontView?r:-r);correction('xp-face-right-value',frontView?-r:r);
    const mount=a.mount_position;this.shadowRoot.querySelector('.xp-marker').dataset.side=mount;
    const faceMarker=q('xp-face-marker');faceMarker.hidden=!['left','right'].includes(mount);faceMarker.dataset.side=frontView?(mount==='right'?'left':'right'):mount;
    const tilt=valid?Math.asin(Math.max(-1,Math.min(1,r/(width*10))))*180/Math.PI:0;
    this.shadowRoot.querySelector('.xp-face').style.setProperty('--xp-tilt',(frontView?-tilt:tilt)+'deg');
    q('xp-facing-note').textContent=topView?'Sivut kulkusuuntaan katsottuna.':frontView?'Edestä: kuvan vasen = vaunun oikea.':'Takaa: kuvan vasen = vaunun vasen.';
    const text=valid?`Keula: ${describe(-p)}, perä: ${describe(p)}, vaunun vasen: ${describe(-r)}, vaunun oikea: ${describe(r)}.`:'Ei ajantasaista tasausohjetta.';
    plot.setAttribute('aria-label','Ajoneuvo ylhäältä. '+text);elevation.setAttribute('aria-label','Ajoneuvo '+(frontView?'edestä. ':'takaa. ')+text);
    q('xp-overall').dataset.level=level;
    const statuses={dimensions_missing:'Syötä laskennan mitat asetuksissa',mount_missing:'Valitse anturin asennuspaikka',directions_unconfirmed:'Vahvista anturin nykyiset suunnat',unsupported_angle:'Kulma tuetun alueen ulkopuolella'};
    const sessionLabels={connecting:'Yhdistetään anturiin…',stopping:'Suljetaan yhteyttä…',cleanup_unknown:'Yhteyden sulkeutumista ei vahvistettu',error:'Mittaus päättyi virheeseen'};
    const diagnosticBusy=this._nonManualBusy();
    q('xp-overall').textContent=!this._online?'Yhteys Home Assistantiin katkennut':diagnosticBusy?(a.mode==='speed_test'?'Rajattu nopeustesti käynnissä':'Paristotietojen haku käynnissä'):sessionLabels[a.session_status]||statuses[this._source?.state]||(!this._isOn()?'Mittaus suljettu':!toleranceValid?'Tarkista tasaustoleranssi':!valid?'Odotetaan tuoretta lukemaa':(level==='ok'?'Suorassa':'Tasausta tarvitaan')+' · toleranssi ±'+new Intl.NumberFormat(this._hass.language||'fi',{maximumFractionDigits:2}).format(tol)+' cm');
    q('xp-session').querySelector('span').textContent=this._pending?'Odota…':diagnosticBusy?(a.mode==='speed_test'?'Lopeta nopeustesti':'Lopeta haku'):this._isOn()?'Lopeta mittaus':'Aloita mittaus';
    const sw=this._hass.states[this._config.measurement_switch];q('xp-session').disabled=!this._online||this._pending||!sw||!['on','off'].includes(sw.state)||['stopping','cleanup_unknown'].includes(a.session_status);
    q('xp-renew').disabled=!this._online||this._pending||!this._isOn()||a.mode!=='manual'||a.session_status!=='measuring';
    const remaining=(Date.parse(a.expires_at)-now)/1000;
    q('xp-session-label').textContent=Number.isFinite(age)&&age>=0?'Lukema '+fmt.format(age)+' s vanha':'Ei vastaanotettua lukemaa';
    q('xp-session-label').nextElementSibling.textContent=this._isOn()&&Number.isFinite(remaining)?'Sulkeutuu '+Math.max(0,Math.ceil(remaining/60))+' min kuluttua':'Automaattinen sulku 10 min';
    if(this.shadowRoot.activeElement!==q('xp-tolerance'))q('xp-tolerance').value=toleranceValid?String(tol).replace('.',','):'';
    q('xp-kind').value=kind;q('xp-kind').disabled=q('xp-tolerance').disabled=!this._online||this._pending;
    q('xp-width').value=Number.isFinite(width)?width:'';q('xp-length').value=a.length_cm||'';q('xp-mount').value=mount||'';
    q('xp-cal-final').disabled=true;
  }
  getCardSize(){return 8;}
  getGridOptions(){return {columns:12,rows:'auto',min_columns:6};}
  getRenderDiagnostics(){return {version:'0.5.0',renderCount:this._renderCount,acceptedSamples:this._acceptedSamples,coalescedSamples:this._coalescedSamples,acceptedSampleToFrameOpportunityMs:[...this._paints],metric:'accepted_coherent_sample_to_second_requestAnimationFrame_not_physical_pixel_latency'};}
}
if(!customElements.get('xparkle-level-card'))customElements.define('xparkle-level-card',XparkleLevelCard);
window.customCards=window.customCards||[];
if(!window.customCards.some(card=>card.type==='xparkle-level-card'))window.customCards.push({type:'xparkle-level-card',name:'Xparkle RV level',description:'Fast, user-controlled RV levelling with physical views.'});
