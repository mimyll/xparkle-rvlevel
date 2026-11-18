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
  sample();const acceptedCount=card.getRenderDiagnostics().acceptedSamples;
  const busyStart=performance.now();while(performance.now()-busyStart<60){}
  for(let i=0;i<20;i++)card.hass={...hass,states:{...states,'sensor.unrelated':{state:String(i)}}};
  await frame();check(card.getRenderDiagnostics().acceptedSamples===acceptedCount,'Unrelated HA events do not become accepted samples');
  check(card.getRenderDiagnostics().acceptedSampleToFrameOpportunityMs.at(-1)>=60,'Unrelated HA events do not reset the accepted-sample timing origin');
  sample(2.5,-2.5);await frame();check(status()==='ok','Inclusive signed2.5mm boundary');
  sample(2.5001,0);await frame();check(status()==='adjust','Unrounded longitudinal threshold');
  sample(0,2.5001);await frame();check(status()==='adjust','Unrounded transverse threshold');
  sample(0,5.0001,{level_tolerance_cm:.5});await frame();check(status()==='adjust','Do not classify rounded5mm as green');
  sample(0,0);await frame();check(status()==='ok'&&q('xp-front-value').textContent==='0 mm','Real zero');
  for(const overrides of [{transverse_mm:null},{longitudinal_mm:NaN},{level_tolerance_cm:0},{width_cm:0},{directions_confirmed:false},{mode:'battery_refresh'},{mode:'speed_test'},{received_at:new Date(Date.now()-5000).toISOString()},{expires_at:new Date(Date.now()-1).toISOString()},{session_id:null}]){sample(2,2,overrides);await frame();check(status()==='unknown','Invalid/unavailable gating '+JSON.stringify(overrides));}
  sample(2,2,{session_status:'cleanup_unknown'});await frame();check(q('xp-overall').textContent==='Yhteyden sulkeutumista ei vahvistettu'&&q('xp-session').disabled,'Cleanup uncertainty is visible and Start blocked');
  states[config.measurement_switch]={state:'off'};sample(2,2,{mode:'speed_test'});await frame();
  check(q('xp-overall').textContent==='Rajattu nopeustesti käynnissä'&&q('xp-session').querySelector('span').textContent==='Lopeta nopeustesti'&&!q('xp-session').disabled&&q('xp-renew').disabled,'Non-manual diagnostic has truthful busy/Stop controls');
  const diagnosticCalls=calls.length;q('xp-session').click();await frame();check(calls.length===diagnosticCalls+1&&calls.at(-1).service==='turn_off','Diagnostic Stop never sends Start');
  controlStart=calls.length;states[config.measurement_switch]={state:'on'};
  sample(-35,27);await frame();const latest={...current,attributes:{...current.attributes}};
  q('xp-view-front').click();await frame();check(q('xp-face-left-label').textContent==='Vaunun oikea'&&q('xp-face-left-value').textContent==='↑ 27 mm','Front mirrored physical right');
  q('xp-view-rear').click();await frame();check(q('xp-face-left-label').textContent==='Vaunun vasen'&&q('xp-face-left-value').textContent==='↓ 27 mm','Rear physical left');
  check(q('xp-front-inline').textContent==='↑ 35 mm','View does not negate pitch');
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
  const count=calls.length;q('xp-session').click();await frame();check(calls.length===count+1&&calls.at(-1).service==='turn_off'&&status()==='unknown','Explicit Stop only');
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
  const report={status:'PASS',assertions,acceptedSampleToSecondFrameOpportunityP95Ms:Math.round(p95*10)/10,samples:timings.length,scope:'actual Chrome local synthetic fixture, no HA/BLE; frame opportunity is not proof of actual pixel latency',version:'0.4.0'};
  results.textContent=JSON.stringify(report,null,2);document.title='PASS — Xparkle0.4.0 local browser tests';window.fixtureResult=report;
 }catch(error){results.textContent='FAIL: '+error.message;document.title='FAIL — Xparkle0.4.0 local browser tests';}
 document.getElementById('native').onclick=()=>{card.setConfig(config);sample(-35,27);};document.getElementById('mint').onclick=()=>{card.setConfig({...config,appearance:'mint'});sample(-35,27);};
 document.getElementById('front').onclick=()=>q('xp-view-front').click();document.getElementById('rear').onclick=()=>q('xp-view-rear').click();document.getElementById('top').onclick=()=>q('xp-view-top').click();
 document.getElementById('fresh').onclick=()=>sample();document.getElementById('tilted').onclick=()=>sample(-35,27);
})();
