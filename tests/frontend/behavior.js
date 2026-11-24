(async()=>{
 const results=document.getElementById('results'),calls=[],card=document.getElementById('card');
 const connection=new EventTarget();connection.connected=true;
 const config={type:'custom:xparkle-level-card',level_sensor:'sensor.synthetic_level',measurement_switch:'switch.synthetic_measurement',renew_button:'button.synthetic_renew',tolerance_number:'number.synthetic_tolerance',vehicle_select:'select.synthetic_vehicle'};
 let sequence=0,updated=Date.now(),current,assertions=0,controlStart=0;
 const frame=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
 const check=(value,label)=>{if(!value)throw Error(label);assertions++;};
 const states={};states[config.measurement_switch]={state:'on'};
 const hass={states,language:'fi',connected:true,connection,callService:async(domain,service,data)=>{
   calls.push({domain,service,data});
   if(domain==='number')current.attributes.level_tolerance_cm=data.value;
   if(domain==='select')current.attributes.vehicle_type=data.option;
   if(domain==='switch'){states[config.measurement_switch]={state:service==='turn_off'?'off':'on'};}
   current={...current,last_updated:new Date(++updated).toISOString()};states[config.level_sensor]=current;card.hass={...hass};
 }};
 function sample(p=2,r=2,overrides={}){const time=Date.now();updated=Math.max(updated+1,time);current={state:'ready',last_updated:new Date(updated).toISOString(),attributes:{session_id:'synthetic-session',sequence:++sequence,received_at:new Date(time).toISOString(),expires_at:new Date(time+600000).toISOString(),fresh_timeout_seconds:1.5,poll_interval_seconds:.5,session_status:'measuring',mode:'manual',directions_confirmed:true,vehicle_type:'tandem',mount_position:'right',width_cm:220,length_cm:500,longitudinal_mm:p,transverse_mm:r,level_tolerance_cm:.25,...overrides}};states[config.level_sensor]=current;card.hass={...hass};}
 const q=id=>card.shadowRoot.getElementById(id),status=()=>q('xp-overall').dataset.level;
 try{
  card.setConfig(config);check(card.getAttribute('appearance')==='native','Default appearance is native');
  states[config.measurement_switch]={state:'off'};sample();await frame();
  const primary=q('xp-session'),settings=q('xp-settings-details'),guidance=q('xp-guidance');
  check(!primary.disabled&&primary.querySelector('span').textContent==='Aloita mittaus','Start is available in idle');
  check(guidance.hidden&&q('xp-overall').hidden&&q('xp-renew').hidden&&!settings.open,'Idle hides readings and secondary controls');
  check(primary.getBoundingClientRect().bottom<=settings.getBoundingClientRect().top,'Primary action sits above settings');
  check(q('xp-session-icon').getAttribute('icon')==='mdi:bluetooth'&&settings.querySelector('ha-icon').getAttribute('icon')==='mdi:cog-outline','Native control icons');
  primary.click();await frame();
  check(calls.length===1&&calls[0].service==='turn_on'&&calls[0].data.entity_id===config.measurement_switch,'Explicit Start uses the bound switch once');
  check(!guidance.hidden&&q('xp-view-top').getAttribute('aria-pressed')==='true'&&q('xp-session-icon').getAttribute('icon')==='mdi:stop','Top view and Stop appear during measurement');
  check(!q('xp-renew').hidden&&q('xp-renew').getAttribute('aria-label')==='Jatka mittausta 10 min','Renew has an accessible label and appears only while measuring');
  q('xp-view-rear').click();sample();await frame();
  check(q('xp-view-rear').getAttribute('aria-pressed')==='true'&&calls.length===1,'View selection persists across samples without a service call');
  for(const theme of [
    {'--primary-color':'rgb(3, 169, 244)','--primary-text-color':'rgb(33, 33, 33)','--ha-card-background':'rgb(255, 255, 255)'},
    {'--primary-color':'rgb(179, 136, 255)','--primary-text-color':'rgb(235, 235, 235)','--ha-card-background':'rgb(28, 28, 28)'}]){
    for(const [key,value] of Object.entries(theme))card.style.setProperty(key,value);
    await frame();check(getComputedStyle(q('xp-session')).backgroundColor===theme['--primary-color'],'Native action follows current HA accent');
    check(getComputedStyle(card.shadowRoot.querySelector('.xp-app')).color===theme['--primary-text-color'],'Native text follows light/dark theme');
    check(getComputedStyle(q('xp-kind')).backgroundColor===theme['--ha-card-background'],'Missing secondary background falls back to current card background');
    check(getComputedStyle(q('xp-kind')).color===theme['--primary-text-color'],'Select text remains visible in minimal theme');
    sample(2,2);await frame();
    check(getComputedStyle(q('xp-view-front')).backgroundColor===theme['--ha-card-background'],'Selected tab background follows minimal theme');
    check(getComputedStyle(q('xp-overall')).backgroundColor===theme['--ha-card-background'],'Ready status surface follows minimal theme');
    sample(4,4);await frame();
    check(getComputedStyle(q('xp-overall')).backgroundColor===theme['--ha-card-background'],'Adjust status surface follows minimal theme');
  }
  card.setConfig({...config,appearance:'mint'});await frame();check(card.getAttribute('appearance')==='mint','Mint is explicit per-card opt-in');
  check(getComputedStyle(q('xp-session')).backgroundColor!=='rgb(179, 136, 255)','Mint retains own isolated appearance');
  let invalid=false;try{card.setConfig({...config,appearance:'global'});}catch{invalid=true;}check(invalid,'Unknown appearance rejected');
  card.setConfig(config);sample();await frame();check(status()==='ok','2mm green');
  const axes=['transverse','longitudinal'],bubble=q('xp-cross-bubble'),target=q('xp-cross-target'),gauge=axis=>q('xp-gauge-'+axis);
  const cornerIds=['xp-front-left','xp-front-right','xp-rear-left','xp-rear-right'];
  const arrowIds=[...cornerIds,'xp-front-inline','xp-rear-inline','xp-face-left-value','xp-face-right-value'];
  function unavailable(label){
    for(const axis of axes)check(bubble.hidden&&target.hidden&&gauge(axis).dataset.level==='unknown'&&gauge(axis).textContent.includes('Ei ajantasaista'),label+' unavailable '+axis);
    check(arrowIds.every(id=>q(id).dataset.motion==='unknown'&&q(id).textContent==='—'),label+' no stale direction');
  }
  for(const p of [-35,0,35])for(const r of [-27,0,27])for(const view of ['front','rear','top']){
    sample(p,r);q('xp-view-'+view).click();await frame();
    const height=[p+r,p-r,-p+r,-p-r],highest=Math.max(...height);
    const values=[...height.map(h=>(highest-h)/2),-p,p,view==='front'?r:-r,view==='front'?-r:r];
    check(arrowIds.every((id,i)=>q(id).dataset.motion===(values[i]>0?'up':values[i]<0?'down':'zero')),'All correction signs '+[p,r,view]);
    check(Math.sign(parseFloat(bubble.style.left)-50)===-Math.sign(r),'Bubble points to high physical side '+[r,view]);
    check(Math.sign(parseFloat(bubble.style.top)-50)===-Math.sign(p),'Bubble points to high end '+[p,view]);
    check(['Keula','Perä','Vasen','Oikea'].every(label=>q('xp-cross').textContent.includes(label)),'Fixed labelled axes '+view);
    if(p||r)check(gauge(p?'longitudinal':'transverse').textContent.includes('ylempänä'),'Readable high-side description');
  }
  sample(-0,-0);await frame();check(arrowIds.every(id=>q(id).dataset.motion==='zero'&&q(id).textContent==='0,00 cm'),'Negative zero is neutral');
  sample(-7.5,-10,{length_cm:805,longitudinal_tolerance_cm:2});await frame();
  check(cornerIds.map(id=>q(id).textContent).join('|')==='↑ 1,75 cm|↑ 0,75 cm|↑ 1,00 cm|0,00 cm','Reference screenshot corners');
  check(q('xp-front-left').querySelector('ha-icon').getAttribute('icon')==='mdi:arrow-up'&&q('xp-rear-right').querySelector('ha-icon').hidden,'MDI raising icon and neutral zero');
  check(gauge('transverse').textContent.includes('0,26°')&&gauge('longitudinal').textContent.includes('0,05°'),'Angles use their own spans');
  check(parseFloat(target.style.height)>parseFloat(target.style.width),'Independent angular widths for target');
  for(const gap of [-20.01,-20,20,20.01]){
    sample(gap,2.5,{length_cm:805,longitudinal_tolerance_cm:2});await frame();
    check(status()===(Math.abs(gap)<=20?'ok':'adjust')&&gauge('longitudinal').textContent.includes('2,00 cm'),'Raw longitudinal threshold '+gap);
  }
  sample(0,0,{length_cm:1,width_cm:1,level_tolerance_cm:5,longitudinal_tolerance_cm:5});await frame();
  check(target.style.width==='84%'&&target.style.height==='84%','Target saturates even when tolerance exceeds span');
  for(const [gap,label] of [[-3.75,'↑ 0,50 cm'],[-1.25,'↑ 0,25 cm'],[-1.2499,'0,00 cm'],[1.2499,'0,00 cm'],[1.25,'↓ 0,25 cm'],[3.75,'↓ 0,50 cm']]){
    sample(gap,0);await frame();check(q('xp-front-inline').textContent===label,'Quarter-centimetre boundary '+gap);
  }
  let previous=-Infinity;
  for(const p of [-35,-10,0,10,35]){sample(p,7);await frame();const x=-parseFloat(bubble.style.top);check(x>previous,'Longitudinal movement monotonic');previous=x;check(parseFloat(bubble.style.left)<50,'Other axis retains high side');}
  for(const gap of [-2.5001,-2.5,-2.4999,2.4999,2.5,2.5001]){
    sample(0,gap);await frame();check(gauge('transverse').dataset.level===(Math.abs(gap)<=2.5?'ok':'adjust')&&gauge('longitudinal').dataset.level==='ok','Independent transverse tolerance '+gap);
    sample(gap,0);await frame();check(gauge('longitudinal').dataset.level===(Math.abs(gap)<=2.5?'ok':'adjust')&&gauge('transverse').dataset.level==='ok','Independent longitudinal tolerance '+gap);
  }
  sample(4,-5,{level_tolerance_cm:.5});await frame();check(axes.every(axis=>gauge(axis).dataset.level==='ok')&&status()==='ok','Changed tolerance inclusive');
  for(const overrides of [{longitudinal_mm:Infinity},{transverse_mm:null},{longitudinal_mm:NaN},{level_tolerance_cm:0},{level_tolerance_cm:null},{width_cm:0},{width_cm:501},{length_cm:2001},{directions_confirmed:false},{mount_position:'unknown'},{mode:'battery_refresh'},{mode:'speed_test'},{session_status:'connecting'},{received_at:new Date(Date.now()-5000).toISOString()},{received_at:new Date(Date.now()+2000).toISOString()},{expires_at:new Date(Date.now()-1).toISOString()},{fresh_timeout_seconds:0},{session_id:null},{sequence:-1}]){
    card.setConfig(config);sample(-35,27);await frame();if(overrides.received_at)card.setConfig(config);sample(2,2,overrides);await frame();unavailable('Gating '+Object.keys(overrides));
  }
  for(const state of ['directions_unconfirmed','dimensions_missing','unsupported_angle','unavailable']){sample(-35,27);await frame();current={...current,state,last_updated:new Date(++updated).toISOString()};states[config.level_sensor]=current;card.hass={...hass};await frame();unavailable('Source '+state);}
  sample(-35,27);await frame();sample(0,0,{received_at:new Date(Date.now()+5000).toISOString()});await frame();unavailable('Far future frame clears guidance');sample(-35,27);await frame();check(!bubble.hidden&&gauge('longitudinal').textContent.includes('3,50 cm'),'Valid frame recovers after malformed future receipt');
  states[config.measurement_switch]={state:'off'};sample(-35,27);await frame();unavailable('Stopped');states[config.measurement_switch]={state:'on'};
  for(const sign of [-1,1]){
    sample(sign*5000*Math.SQRT1_2,sign*2200*Math.SQRT1_2);await frame();
    check(!bubble.hidden&&bubble.style.left===(50-sign*42)+'%'&&bubble.style.top===(50-sign*42)+'%'&&gauge('transverse').textContent.includes('45,00° · yli asteikon'),'45-degree angle with bubble clamped at scale limit');
    sample(sign*5000*(Math.SQRT1_2+1e-8),0);await frame();unavailable('Beyond45 longitudinal');
    sample(0,sign*2200*(Math.SQRT1_2+1e-8));await frame();unavailable('Beyond45 transverse');
  }
  const clock=Date.now,now=clock();
  try{Date.now=()=>now;sample(2,2);await frame();Date.now=()=>now+1500;card._render();check(!bubble.hidden,'TTL inclusive');Date.now=()=>now+1501;card._render();unavailable('Timer expiry');}finally{Date.now=clock;}
  sample(-35,27);await frame();const coherentLeft=bubble.style.left,coherentEnd=bubble.style.top;
  const newer=current;current={...newer,last_updated:new Date(++updated).toISOString(),attributes:{...newer.attributes,sequence:1,longitudinal_mm:0,transverse_mm:0}};states[config.level_sensor]=current;card.hass={...hass};await frame();
  check(bubble.style.left===coherentLeft&&bubble.style.top===coherentEnd&&q('xp-front-inline').dataset.motion==='up','Out-of-order frame cannot mix gauges and corrections');
  for(let i=0;i<20;i++)sample(-i,i);await frame();check(q('xp-front-inline').textContent==='↑ 2,00 cm'&&gauge('transverse').textContent.includes('2,00 cm')&&gauge('longitudinal').textContent.includes('2,00 cm'),'Burst preserves final coherent frame');
  connection.connected=false;connection.dispatchEvent(new Event('disconnected'));unavailable('Disconnected');connection.connected=true;connection.dispatchEvent(new Event('ready'));await frame();unavailable('Reconnected old frame');sample();await frame();
  const ctx=document.createElement('canvas').getContext('2d');
  const lum=color=>{ctx.fillStyle=color;ctx.fillRect(0,0,1,1);const v=[...ctx.getImageData(0,0,1,1).data].slice(0,3).map(x=>x/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);return v[0]*.2126+v[1]*.7152+v[2]*.0722;};
  const ratio=(a,b)=>{const x=lum(a),y=lum(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);};
  const palettes={};
  for(const mode of ['native','minimal','mint'])for(const dark of [false,true]){
    const appearance=mode==='mint'?'mint':'native';
    card.setConfig({...config,appearance});q('xp-design').style.colorScheme=dark?'dark':'light';
    for(const [k,v] of Object.entries({'--primary-text-color':dark?'rgb(235, 235, 235)':'rgb(33, 33, 33)','--ha-card-background':dark?'rgb(28, 28, 28)':'rgb(255, 255, 255)'}))card.style.setProperty(k,v);
    card.style.setProperty('--secondary-background-color',mode==='native'?(dark?'rgb(40, 40, 40)':'rgb(245, 245, 245)'):'');
    card.style.setProperty('--secondary-text-color',mode==='native'?(dark?'rgb(180, 180, 180)':'rgb(90, 90, 90)'):'');
    for(const width of [320,390,391,520])for(const view of ['front','rear','top']){
      card.style.width=width+'px';document.getElementById('mount').style.width=width+'px';sample(-14142.1,3535.5,{width_cm:500,length_cm:2000});q('xp-view-'+view).click();await frame();
      const up=getComputedStyle(q('xp-front-inline')).color,down=getComputedStyle(q('xp-rear-inline')).color,bg=getComputedStyle(card.shadowRoot.querySelector('.xp-app')).getPropertyValue('--xp-surface');
      const probe=document.createElement('span');probe.style.color=bg;card.shadowRoot.querySelector('.xp-app').append(probe);const surface=getComputedStyle(probe).color;probe.remove();
      check(up!==down&&ratio(up,surface)>=4.5&&ratio(down,surface)>=4.5,'Distinct readable direction colors '+[mode,dark,width,view,ratio(up,surface),ratio(down,surface)]);
      check(arrowIds.every(id=>{const node=q(id),motion=node.dataset.motion;return motion==='zero'||getComputedStyle(node).color===(motion==='up'?up:down); }),'Every correction context uses direction color');
      const box=bubble.getBoundingClientRect(),track=bubble.parentElement.getBoundingClientRect(),outer=q('xp-cross').getBoundingClientRect();
      check(box.left>=track.left&&box.right<=track.right&&box.top>=track.top&&box.bottom<=track.bottom,'Bounded bubble '+width);
      check(outer.left>=card.getBoundingClientRect().left&&outer.right<=card.getBoundingClientRect().right,'Cross fits '+width);
      check(getComputedStyle(bubble).transitionDuration==='0s','No interpolation delay');
      if(view==='top')for(const id of cornerIds){
        const group=q(id).parentElement.getBoundingClientRect(),plotBox=card.shadowRoot.querySelector('.xp-plot').getBoundingClientRect();
        check(group.left>=plotBox.left&&group.right<=plotBox.right,'Corner fits '+[id,width]);
      }
      sample(0,0);await frame();const good=getComputedStyle(gauge('transverse')).color,inset=getComputedStyle(q('xp-cross').parentElement).backgroundColor;check(ratio(good,inset)>=4.5,'Readable green level text '+[mode,dark,ratio(good,inset)]);
      palettes[mode+dark]=getComputedStyle(card.shadowRoot.querySelector('.xp-app')).color+'|'+surface;
    }
  }
  check(['native','minimal','mint'].every(mode=>palettes[mode+'false']!==palettes[mode+'true']),'Light and dark tests use distinct actual palettes');
  sample(.6,-.6,{level_tolerance_cm:.05,longitudinal_tolerance_cm:.05});await frame();
  check(status()==='adjust'&&q('xp-front-inline').textContent==='0,00 cm'&&gauge('longitudinal').textContent.includes('Keula ylempänä · alle 0,25 cm'),'Tiny nonzero retains high-end direction without an arrow');
  card.dir='rtl';sample(-35,27);await frame();const labels=q('xp-cross').querySelectorAll('span[style^="grid-area"]');check(labels[1].getBoundingClientRect().left<labels[2].getBoundingClientRect().left,'Physical labels stay fixed under RTL');card.removeAttribute('dir');
  check(card.shadowRoot.querySelector('.xp-elevation').getAttribute('aria-label').includes('Nosta')&&card.shadowRoot.querySelector('.xp-elevation').getAttribute('aria-label').includes('Laske'),'Image accessible description includes correction meaning');
  sample(2,2,{level_tolerance_cm:0});await frame();check(q('xp-overall').textContent==='Tarkista toleranssit','Invalid tolerance gives actionable status');
  card.setConfig(config);sample();await frame();
  sample();const acceptedCount=card.getRenderDiagnostics().acceptedSamples;
  const busyStart=performance.now();while(performance.now()-busyStart<60){}
  for(let i=0;i<20;i++)card.hass={...hass,states:{...states,'sensor.unrelated':{state:String(i)}}};
  await frame();check(card.getRenderDiagnostics().acceptedSamples===acceptedCount,'Unrelated HA events do not become accepted samples');
  check(card.getRenderDiagnostics().acceptedSampleToFrameOpportunityMs.at(-1)>=60,'Unrelated HA events do not reset the accepted-sample timing origin');
  sample(2.5,-2.5);await frame();check(status()==='ok','Inclusive signed2.5mm boundary');
  sample(2.5001,0);await frame();check(status()==='adjust','Unrounded longitudinal threshold');
  sample(0,2.5001);await frame();check(status()==='adjust','Unrounded transverse threshold');
  sample(0,5.0001,{level_tolerance_cm:.5});await frame();check(status()==='adjust','Do not classify rounded5mm as green');
  sample(0,0);await frame();check(status()==='ok'&&q('xp-front-inline').textContent==='0,00 cm','Real zero');
  for(const overrides of [{transverse_mm:null},{longitudinal_mm:NaN},{level_tolerance_cm:0},{width_cm:0},{directions_confirmed:false},{mode:'battery_refresh'},{mode:'speed_test'},{received_at:new Date(Date.now()-5000).toISOString()},{expires_at:new Date(Date.now()-1).toISOString()},{session_id:null}]){sample(2,2,overrides);await frame();check(status()==='unknown','Invalid/unavailable gating '+JSON.stringify(overrides));}
  sample(2,2,{session_status:'cleanup_unknown'});await frame();check(q('xp-overall').textContent==='Yhteyden sulkeutumista ei vahvistettu'&&q('xp-session').disabled,'Cleanup uncertainty is visible and Start blocked');
  states[config.measurement_switch]={state:'off'};sample(2,2,{mode:'speed_test'});await frame();
  check(q('xp-overall').textContent==='Nopeustesti käynnissä'&&q('xp-session').querySelector('span').textContent==='Lopeta nopeustesti'&&!q('xp-session').disabled&&q('xp-renew').hidden,'Non-manual diagnostic has truthful busy/Stop controls');
  const diagnosticCalls=calls.length;q('xp-session').click();await frame();check(calls.length===diagnosticCalls+1&&calls.at(-1).service==='turn_off','Diagnostic Stop never sends Start');
  controlStart=calls.length;states[config.measurement_switch]={state:'on'};
  sample(-35,27);await frame();const latest={...current,attributes:{...current.attributes}};
  q('xp-view-front').click();await frame();check(q('xp-face-left-label').textContent==='Vaunun oikea'&&q('xp-face-left-value').textContent==='↑ 2,75 cm','Front mirrored physical right');
  q('xp-view-rear').click();await frame();check(q('xp-face-left-label').textContent==='Vaunun vasen'&&q('xp-face-left-value').textContent==='↓ 2,75 cm','Rear physical left');
  check(q('xp-front-inline').textContent==='↑ 3,50 cm','View does not negate pitch');
  function clearance(label){
    const elevation=card.shadowRoot.querySelector('.xp-elevation');
    const groups=elevation.querySelectorAll(':scope > .xp-correction');
    const parts=[...elevation.querySelectorAll('.xp-face,.xp-face-tire,.xp-marker')].filter(node=>node.getClientRects().length);
    const boxes=parts.map(node=>node.getBoundingClientRect());
    const left=Math.min(...boxes.map(box=>box.left)),right=Math.max(...boxes.map(box=>box.right));
    const textBox=group=>{const range=card.ownerDocument.createRange();range.selectNodeContents(group);const box=range.getBoundingClientRect();range.detach();return box;};
    check(textBox(groups[0]).right<=left-7,label+' left text has8px clearance allowing1px rounding');
    check(textBox(groups[1]).left>=right+7,label+' right text has8px clearance allowing1px rounding');
  }
  for(const width of [320,390,391,520,320,520]){
    card.style.width=width+'px';document.getElementById('mount').style.width=width+'px';
    for(const view of ['front','rear'])for(const side of [-1,1]){q('xp-view-'+view).click();sample(-35,27*side);await frame();clearance(width+'px '+view+' normal '+side);}
  }
  for(const kind of ['caravan','tandem','motorhome','van'])for(const view of ['front','rear'])for(const side of [-1,1]){
    card.style.width='320px';document.getElementById('mount').style.width='320px';q('xp-view-'+view).click();
    sample(-14142.1,3535.5*side,{vehicle_type:kind,width_cm:500,length_cm:2000});await frame();clearance('320px '+kind+' '+view+' long '+side);
  }
  card.style.width='320px';document.getElementById('mount').style.width='320px';sample(-35,27);await frame();
  current={...latest,last_updated:new Date(++updated).toISOString(),attributes:{...latest.attributes,sequence:1,received_at:new Date(Date.now()-100).toISOString(),longitudinal_mm:0,transverse_mm:0}};states[config.level_sensor]=current;card.hass={...hass};await frame();check(status()==='adjust','Reordered sample cannot turn green');
  sample();await frame();connection.connected=false;connection.dispatchEvent(new Event('disconnected'));check(status()==='unknown','Disconnect immediately neutral');
  connection.connected=true;connection.dispatchEvent(new Event('ready'));await frame();check(status()==='unknown','Reconnect waits for newer sample');
  sample();await frame();check(status()==='ok','New sample restores green');
  q('xp-view-top').click();await frame();const vehicle=card.shadowRoot.querySelector('.xp-vehicle'),first=vehicle.querySelector('.xp-wl:not(.xp-wheel-second)'),second=vehicle.querySelector('.xp-wheel-second');
  check(parseFloat(getComputedStyle(first).top)===110&&parseFloat(getComputedStyle(second).top)===145,'Tandem axles moved together');
  const before=calls.length;q('xp-cal-open').click();q('xp-cal-check').checked=true;q('xp-cal-final').click();q('xp-cal-final').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));check(q('xp-cal-final').disabled&&calls.length===before,'Calibration cannot dispatch');q('xp-cal-cancel').click();check(q('xp-cal-confirm').hidden&&!q('xp-cal-check').checked,'Calibration cancel resets');
  sample(2,4);await frame();q('xp-tolerance').value='0,5';q('xp-tolerance').dispatchEvent(new Event('change'));await frame();check(calls.at(-1).domain==='number'&&calls.at(-1).data.entity_id===config.tolerance_number,'Bound native tolerance action');check(status()==='ok','Native tolerance response updates status');
  for(const kind of ['caravan','tandem','motorhome','van']){q('xp-kind').value=kind;q('xp-kind').dispatchEvent(new Event('change'));await frame();check(vehicle.dataset.kind===kind,'Vehicle '+kind);}
  check(calls.slice(controlStart).every(c=>['number','select'].includes(c.domain)),'Rendering/view changes never start/read/renew');
  const count=calls.length;q('xp-session').click();await frame();check(calls.length===count+1&&calls.at(-1).service==='turn_off'&&status()==='unknown'&&guidance.hidden,'Explicit Stop clears the guidance');
  states[config.measurement_switch]={state:'on'};
  for(let i=0;i<24;i++){sample(2,2);await frame();}
  const timings=card.getRenderDiagnostics().acceptedSampleToFrameOpportunityMs.slice(-20).sort((a,b)=>a-b),p95=timings[Math.ceil(timings.length*.95)-1];
  check(timings.length>=20&&p95<=100,'Local event-to-visible-frame target <=100ms');
  const rootBox=card.getBoundingClientRect();check(rootBox.width<=322,'Narrow320px fixture');
  q('xp-settings-details').open=true;await frame();
  const appBox=card.shadowRoot.querySelector('.xp-app').getBoundingClientRect();
  for(const element of card.shadowRoot.querySelectorAll('button,input,select,img,.xp-correction,.xp-face')){
    const box=element.getBoundingClientRect();if(box.width&&box.height)check(box.left>=appBox.left-1&&box.right<=appBox.right+1,'Visible content fits inside320px card: '+(element.id||element.className));
  }
  const expected=card._renderCount;card.remove();await frame();check(card._ageTimer===null&&!card._bound,'Disconnect cleans timer/listeners');
  document.getElementById('mount').append(card);card.hass=hass;await frame();check(card._renderCount>expected,'Reconnect card lifecycle');
  const report={status:'PASS',assertions,acceptedSampleToSecondFrameOpportunityP95Ms:Math.round(p95*10)/10,samples:timings.length,scope:'actual Chrome local synthetic fixture, no HA/BLE; frame opportunity is not proof of actual pixel latency',version:'0.6.0'};
  results.textContent=JSON.stringify(report,null,2);document.title='PASS — Xparkle0.6.0 local browser tests';window.fixtureResult=report;
 }catch(error){results.textContent='FAIL: '+error.message;document.title='FAIL — Xparkle0.6.0 local browser tests';}
 document.getElementById('native').onclick=()=>{card.setConfig(config);sample(-35,27);};document.getElementById('mint').onclick=()=>{card.setConfig({...config,appearance:'mint'});sample(-35,27);};
 document.getElementById('front').onclick=()=>q('xp-view-front').click();document.getElementById('rear').onclick=()=>q('xp-view-rear').click();document.getElementById('top').onclick=()=>q('xp-view-top').click();
 document.getElementById('fresh').onclick=()=>sample();document.getElementById('tilted').onclick=()=>sample(-35,27);
})();
